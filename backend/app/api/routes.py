from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

from app.certificate import FixCertificate, IterationRecord, TimelineEvent
from app.config import get_settings
from app.evaluation import load_cases
from app.github_pr import (
    PullRequestError,
    PullRequestResult,
    ensure_eligible,
    parse_repository,
    publish_pull_request,
    repository_from_project,
    validate_base_branch,
    validate_token,
)
from app.llm.nebius import NebiusConfigurationError
from app.orchestrator.state import InvestigationStage, InvestigationState
from app.pipeline import factory
from app.projects import ProjectError, ProjectInfo, ProjectStore
from app.runners import get_language_runner
from app.sandbox.factory import SandboxUnavailable, get_sandbox
from app.verification.results import CheckOutcome
from app.verification.scan import ScanResult, TargetError, scan_project, validate_repro_targets

router = APIRouter(prefix="/api/v1")

_INVESTIGATIONS: dict[str, InvestigationState] = {}

EXAMPLES_ROOT = Path(__file__).resolve().parents[3] / "examples"
# Allowlist: this release repairs only bundled example repositories. Arbitrary repository
# URLs are recorded but not cloned or executed (untrusted-code policy).
_CASES = load_cases()
EXAMPLE_CASES: dict[str, list[str]] = {Path(c.source).name: c.repro_targets for c in _CASES}
EXAMPLE_ISSUES: dict[str, str] = {Path(c.source).name: c.issue for c in _CASES}
_STAGE_MAP = {
    "reproducing": InvestigationStage.REPRODUCING,
    "investigating": InvestigationStage.INVESTIGATING,
    "fixing": InvestigationStage.FIXING,
    "planning_verification": InvestigationStage.PLANNING_VERIFICATION,
    "reverifying": InvestigationStage.VERIFYING,
    "verifying": InvestigationStage.VERIFYING,
    "repairing": InvestigationStage.REPAIRING,
}


class CreateInvestigationRequest(BaseModel):
    repo_url: HttpUrl | None = None
    issue: str
    example_case: str | None = None
    project_id: str | None = None
    repro_targets: list[str] = []


class ReverifyRequest(BaseModel):
    attempt: int
    disputed: list[str]
    reason: str


class GitProjectRequest(BaseModel):
    url: str
    ref: str | None = None


class LocalProjectRequest(BaseModel):
    path: str


class PullRequestRequest(BaseModel):
    # "owner/repo" or a github.com URL. Defaults to the project's own GitHub origin.
    repository: str | None = None
    base_branch: str | None = None  # defaults to the repository's default branch


def _store() -> ProjectStore:
    return ProjectStore()


MAX_UPLOAD_BYTES_SLACK = 1024 * 1024


@router.get("/about")
def about() -> dict[str, Any]:
    settings = get_settings()
    return {
        "name": "FixProof",
        "tagline": "AI proposes the fix. Evidence earns the merge.",
        "status": "vertical_slice",
        "target_scope": "Python + pytest projects whose dependencies are in the sandbox image",
        "nebius_model": settings.nebius_model,
        "nebius_configured": bool(settings.nebius_api_key),
        "github_configured": bool(settings.github_token),
        "sandbox_mode": settings.sandbox_mode,
        "example_cases": sorted(EXAMPLE_CASES),
        "example_issues": EXAMPLE_ISSUES,
        "project_sources": {
            "zip": True,
            "git": True,
            "local": bool(settings.local_path_root_list),
        },
        "max_project_mb": settings.max_project_mb,
        "implemented_now": [
            "your own project: zip upload, GitHub URL or local folder",
            "failing-test scan, then red/green reproduction",
            "patch scope validation + apply",
            "regression run",
            "spec-grounded adversarial tests executed in sandbox",
            "bounded repair loop with counterexample feedback",
            "verdict policy v1 + sealed Fix Certificate",
            "open a GitHub pull request for a verified patch",
            "post-patch SAST security scan (SQL/CMD/Path injection, secrets, weak crypto)",
        ],
        "not_implemented": [
            "hypothesis experiments",
            "Hypothesis property tests",
            "mutation testing",
            "installing project dependencies (offline sandbox)",
            "Nebius-hosted execution",
        ],
    }


# ---------------------------------------------------------------- projects


@router.post("/projects/upload", response_model=ProjectInfo, status_code=201)
async def upload_project(request: Request) -> ProjectInfo:
    """Raw zip bytes in the body (Content-Type: application/zip), name in X-Filename."""
    limit = get_settings().max_project_mb * 1024 * 1024 + MAX_UPLOAD_BYTES_SLACK
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail="archive is too large")
    filename = request.headers.get("x-filename", "project.zip")
    try:
        return await run_in_threadpool(_store().create_from_zip, bytes(data), filename)
    except ProjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/git", response_model=ProjectInfo, status_code=201)
def project_from_git(payload: GitProjectRequest) -> ProjectInfo:
    try:
        return _store().create_from_git(payload.url, payload.ref)
    except ProjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/projects/local", response_model=ProjectInfo, status_code=201)
def project_from_local(payload: LocalProjectRequest) -> ProjectInfo:
    try:
        return _store().create_from_local(payload.path)
    except ProjectError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _project(project_id: str) -> tuple[ProjectInfo, Path]:
    try:
        return _store().get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/projects/{project_id}", response_model=ProjectInfo)
def get_project(project_id: str) -> ProjectInfo:
    return _project(project_id)[0]


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    _project(project_id)
    _store().delete(project_id)


@router.post("/projects/{project_id}/scan", response_model=ScanResult)
def scan(project_id: str) -> ScanResult:
    _, source = _project(project_id)
    try:
        sandbox = get_sandbox()
    except SandboxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return scan_project(sandbox, source)


# ------------------------------------------------------- live local file sync (kill switch)


class ProjectSyncRequest(BaseModel):
    project_id: str | None = None
    file_path: str
    content: str | None = None
    event_type: str = "modified"  # modified | created | deleted


class ProjectSyncResponse(BaseModel):
    status: str
    project_id: str
    file_path: str
    event_type: str
    language: str
    test_result: dict[str, Any] | None = None
    detail: str = ""


class SyncConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


sync_manager = SyncConnectionManager()


@router.websocket("/ws/sync")
async def websocket_sync_route(websocket: WebSocket) -> None:
    await sync_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        sync_manager.disconnect(websocket)
    except Exception:
        sync_manager.disconnect(websocket)


def _resolve_sync_project(project_id: str | None) -> tuple[str, Path]:
    store = _store()
    if project_id and project_id.strip():
        info, source = store.get(project_id.strip())
        return info.id, source
    for inv in reversed(list(_INVESTIGATIONS.values())):
        if inv.project_id:
            try:
                info, source = store.get(inv.project_id)
                return info.id, source
            except KeyError:
                continue
    projects = [p for p in store.root.iterdir() if p.is_dir() and (p / "src").is_dir()]
    if projects:
        latest = max(projects, key=lambda p: p.stat().st_mtime)
        return latest.name, latest / "src"
    raise HTTPException(status_code=404, detail="No active project found to sync")


@router.post("/project/sync", response_model=ProjectSyncResponse)
async def sync_project_file(payload: ProjectSyncRequest) -> ProjectSyncResponse:
    pid, source = _resolve_sync_project(payload.project_id)
    clean_rel = PurePosixPath(payload.file_path.replace("\\", "/").lstrip("/"))
    if ".." in clean_rel.parts or clean_rel.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid relative file path")
    dest_path = (source / clean_rel).resolve()
    if source.resolve() not in dest_path.parents and dest_path != source.resolve():
        raise HTTPException(
            status_code=400, detail="Path traversal outside project root is forbidden"
        )

    if payload.event_type == "deleted":
        if dest_path.exists():
            dest_path.unlink()
    else:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(payload.content or "", encoding="utf-8")

    await sync_manager.broadcast(
        {
            "event": "TESTS_RE_RUNNING",
            "project_id": pid,
            "file_path": str(clean_rel),
            "event_type": payload.event_type,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    runner = get_language_runner(source)
    try:
        sandbox = get_sandbox()
        test_run = await run_in_threadpool(runner.run_tests, sandbox, source)
        test_dict = test_run.to_dict()
    except Exception as exc:
        test_dict = {
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "duration_seconds": 0.0,
            "timed_out": False,
            "failures": [
                {
                    "test_name": "(sandbox_execution)",
                    "message": str(exc),
                    "file": None,
                    "line": None,
                }
            ],
        }

    await sync_manager.broadcast(
        {
            "event": "RUN_COMPLETE",
            "project_id": pid,
            "file_path": str(clean_rel),
            "language": runner.language.value,
            "result": test_dict,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    return ProjectSyncResponse(
        status="ok",
        project_id=pid,
        file_path=str(clean_rel),
        event_type=payload.event_type,
        language=runner.language.value,
        test_result=test_dict,
        detail=f"Successfully synced {clean_rel} and executed {runner.language.value} tests",
    )


# ---------------------------------------------------------------- investigations


@router.post(
    "/investigations", response_model=InvestigationState, status_code=status.HTTP_201_CREATED
)
def create_investigation(payload: CreateInvestigationRequest) -> InvestigationState:
    issue = payload.issue.strip()
    if len(issue) < 10:
        raise HTTPException(
            status_code=422, detail="Issue description must be at least 10 characters"
        )
    if len(issue) > 5000:
        raise HTTPException(status_code=422, detail="Issue description is too long (max 5000)")
    if payload.example_case and payload.project_id:
        raise HTTPException(
            status_code=422, detail="Choose an example_case or a project_id, not both"
        )
    if payload.example_case is not None and payload.example_case not in EXAMPLE_CASES:
        raise HTTPException(status_code=422, detail="Unknown example_case")
    targets = EXAMPLE_CASES.get(payload.example_case or "", [])
    project_name = None
    if payload.project_id:
        info, source = _project(payload.project_id)
        project_name = info.name
        try:
            targets = validate_repro_targets(source, payload.repro_targets)
        except TargetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    state = InvestigationState(
        repo_url=str(payload.repo_url) if payload.repo_url else "",
        issue=issue,
        example_case=payload.example_case,
        project_id=payload.project_id,
        project_name=project_name,
        repro_targets=targets,
    )
    _INVESTIGATIONS[state.id] = state
    return state


def _get(investigation_id: str) -> InvestigationState:
    try:
        return _INVESTIGATIONS[investigation_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc


@router.get("/investigations/{investigation_id}", response_model=InvestigationState)
def get_investigation(investigation_id: str) -> InvestigationState:
    return _get(investigation_id)


def _apply_certificate(state: InvestigationState, cert: FixCertificate) -> None:
    state.certificate = cert
    state.verdict = cert.verdict
    state.patch = cert.final_patch
    state.root_cause = cert.selected_root_cause or None
    state.repair_iteration = len(cert.iterations)
    state.limitations = cert.limitations
    state.stage = InvestigationStage.COMPLETED
    # Feature 4: propagate security seal to state for dashboard consumption
    state.security_seal = cert.security_seal  # type: ignore[attr-defined]
    state.security_verified = cert.security_verified  # type: ignore[attr-defined]
    # Feature 3: propagate explanation to state for dashboard display
    if cert.explanation is not None:
        try:
            state.explanation = cert.explanation.model_dump()  # type: ignore[union-attr]
        except AttributeError:
            state.explanation = dict(cert.explanation)  # type: ignore[call-overload]


def _execute(state: InvestigationState, pipeline: Any, source: Path, label: str) -> None:
    try:
        _apply_certificate(
            state,
            pipeline.run(
                source=source,
                issue=state.issue,
                repro_targets=state.repro_targets,
                investigation_id=state.id,
                source_label=label,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client, never a fake verdict
        state.error = f"{type(exc).__name__}: {exc}"
        state.stage = InvestigationStage.FAILED


def _source_for(state: InvestigationState) -> tuple[Path, str]:
    if state.project_id:
        info, source = _project(state.project_id)
        return source, f"project/{info.name}"
    if state.example_case:
        return EXAMPLES_ROOT / state.example_case, f"examples/{state.example_case}"
    raise HTTPException(
        status_code=422, detail="Choose a project or a bundled example before running."
    )


def _disputable_keys(cert: FixCertificate, attempt: IterationRecord) -> set[str]:
    """Grounded, not-yet-excluded attack tests that actually failed on this attempt's patch."""
    keys: set[str] = set()
    for test in cert.adversarial_tests:
        key = test.key
        if not key or not test.grounded or test.disputed:
            continue
        failed = attempt.test_results.get(key) == "failed" or any(
            f"test_adv_{key}" in c for c in attempt.counterexamples
        )
        if failed:
            keys.add(key)
    return keys


@router.post("/investigations/{investigation_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_investigation(investigation_id: str, background: BackgroundTasks) -> dict[str, str]:
    state = _get(investigation_id)
    source, label = _source_for(state)
    if state.stage not in (InvestigationStage.CREATED, InvestigationStage.FAILED):
        raise HTTPException(status_code=409, detail=f"Investigation is {state.stage}")

    def on_event(stage: str, message: str) -> None:
        state.events.append(TimelineEvent(stage=stage, message=message))
        if stage in _STAGE_MAP:
            state.stage = _STAGE_MAP[stage]

    try:
        pipeline = factory.build_pipeline(on_event)
    except (NebiusConfigurationError, SandboxUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    state.error = None
    state.events = []
    state.stage = InvestigationStage.REPRODUCING
    background.add_task(_execute, state, pipeline, source, label)
    return {"status": "accepted", "investigation_id": state.id}


@router.post("/investigations/{investigation_id}/reverify", status_code=status.HTTP_202_ACCEPTED)
def reverify_investigation(
    investigation_id: str, payload: ReverifyRequest, background: BackgroundTasks
) -> dict[str, str]:
    """Human review: re-run every check on one attempt's patch, excluding attack tests the
    reviewer judges wrong. Makes no model calls; the exclusion is recorded in the certificate."""
    state = _get(investigation_id)
    base = state.certificate
    if base is None or state.stage != InvestigationStage.COMPLETED:
        raise HTTPException(
            status_code=409, detail="Only a completed investigation can be re-verified"
        )
    reason = payload.reason.strip()
    if not 10 <= len(reason) <= 500:
        raise HTTPException(status_code=422, detail="Give a reason of 10-500 characters")
    attempt = next((it for it in base.iterations if it.index == payload.attempt), None)
    applied = attempt is not None and any(
        c.name == "patch_applies_in_scope" and c.outcome == CheckOutcome.PASSED
        for c in attempt.checks
    )
    if attempt is None or not attempt.diff or not applied:
        raise HTTPException(status_code=422, detail="That attempt has no applicable patch")
    allowed = _disputable_keys(base, attempt)
    bad = [k for k in payload.disputed if k not in allowed]
    if not payload.disputed or bad:
        raise HTTPException(
            status_code=422,
            detail="Only spec-grounded attack tests that failed on that attempt can be disputed"
            + (f" (not allowed: {', '.join(bad)})" if bad else ""),
        )
    source, label = _source_for(state)
    new = InvestigationState(
        repo_url=state.repo_url, issue=state.issue, example_case=state.example_case,
        project_id=state.project_id, project_name=state.project_name,
        repro_targets=state.repro_targets, parent_id=state.id,
    )  # fmt: skip

    def on_event(stage: str, message: str) -> None:
        new.events.append(TimelineEvent(stage=stage, message=message))
        if stage in _STAGE_MAP:
            new.stage = _STAGE_MAP[stage]

    try:
        pipeline = factory.build_reverifier(on_event, base.model.model_dump())
    except SandboxUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    new.stage = InvestigationStage.REPRODUCING
    _INVESTIGATIONS[new.id] = new

    def work() -> None:
        try:
            _apply_certificate(
                new,
                pipeline.reverify(
                    source=source,
                    issue=new.issue,
                    repro_targets=new.repro_targets,
                    base=base,
                    attempt=payload.attempt,
                    disputed=payload.disputed,
                    reason=reason,
                    investigation_id=new.id,
                    source_label=label,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            new.error = f"{type(exc).__name__}: {exc}"
            new.stage = InvestigationStage.FAILED

    background.add_task(work)
    return {"status": "accepted", "investigation_id": new.id}


@router.get("/investigations/{investigation_id}/certificate", response_model=FixCertificate)
def get_certificate(investigation_id: str) -> FixCertificate:
    state = _get(investigation_id)
    if state.certificate is None:
        raise HTTPException(status_code=404, detail="No certificate yet")
    return state.certificate


# ---------------------------------------------------------------- GitHub pull request

_PR_IN_PROGRESS: set[str] = set()  # blocks a double-click from racing itself


@router.post("/investigations/{investigation_id}/pull-request", response_model=PullRequestResult)
def create_pull_request(
    investigation_id: str,
    payload: PullRequestRequest,
    x_github_token: str | None = Header(default=None),
) -> Any:
    """Open a GitHub PR for a *verified* patch: branch fixproof/patch-<id>, strict apply, commit,
    push, PR with root cause, fix summary and the attack tests that passed.

    The token comes from the X-GitHub-Token header (kept in memory, never stored or logged) or
    FIXPROOF_GITHUB_TOKEN. Failures return {detail, code, details} with a stable `code`.
    """
    state = _get(investigation_id)
    cert = state.certificate
    if cert is None or state.stage != InvestigationStage.COMPLETED:
        raise HTTPException(status_code=409, detail="Only a completed investigation has a patch")
    if investigation_id in _PR_IN_PROGRESS:
        raise HTTPException(status_code=409, detail="A pull request is already being created")
    _PR_IN_PROGRESS.add(investigation_id)
    try:
        ensure_eligible(cert)
        token = validate_token(x_github_token or get_settings().github_token)
        if payload.repository and payload.repository.strip():
            owner, name = parse_repository(payload.repository)
        else:
            origin = None
            if state.project_id:
                info, _ = _project(state.project_id)
                origin = repository_from_project(info.origin, info.origin_detail)
            if origin is None:
                raise PullRequestError(
                    "REPOSITORY_REQUIRED",
                    "Enter the GitHub repository to open the pull request against "
                    "(this run is not tied to a GitHub clone).",
                    422,
                )
            owner, name, _ref = origin
        return publish_pull_request(
            cert,
            token=token,
            owner=owner,
            name=name,
            base_branch=validate_base_branch(payload.base_branch),
        )
    except PullRequestError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, "details": exc.details},
        )
    finally:
        _PR_IN_PROGRESS.discard(investigation_id)


# ---------------------------------------------------------------- benchmark results


@router.get("/benchmark")
def benchmark() -> dict[str, Any]:
    """Newest recorded benchmark report from evals/results, or available=false. Never invented."""
    results = Path(__file__).resolve().parents[3] / "evals" / "results"
    files = sorted(results.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"available": False}
    import json

    return {"available": True, "file": files[0].name, "report": json.loads(files[0].read_text())}
