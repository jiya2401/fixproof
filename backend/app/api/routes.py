from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, HttpUrl

from app.certificate import FixCertificate, TimelineEvent
from app.config import get_settings
from app.evaluation import load_cases
from app.llm.nebius import NebiusConfigurationError
from app.orchestrator.state import InvestigationStage, InvestigationState
from app.pipeline import factory
from app.projects import ProjectError, ProjectInfo, ProjectStore
from app.sandbox.factory import SandboxUnavailable, get_sandbox
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
    "verifying": InvestigationStage.VERIFYING,
    "repairing": InvestigationStage.REPAIRING,
}


class CreateInvestigationRequest(BaseModel):
    repo_url: HttpUrl | None = None
    issue: str
    example_case: str | None = None
    project_id: str | None = None
    repro_targets: list[str] = []


class GitProjectRequest(BaseModel):
    url: str
    ref: str | None = None


class LocalProjectRequest(BaseModel):
    path: str


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


def _execute(state: InvestigationState, pipeline: Any, source: Path, label: str) -> None:
    try:
        cert = pipeline.run(
            source=source,
            issue=state.issue,
            repro_targets=state.repro_targets,
            investigation_id=state.id,
            source_label=label,
        )
        state.certificate = cert
        state.verdict = cert.verdict
        state.patch = cert.final_patch
        state.root_cause = cert.selected_root_cause or None
        state.repair_iteration = len(cert.iterations)
        state.limitations = cert.limitations
        state.stage = InvestigationStage.COMPLETED
    except Exception as exc:  # noqa: BLE001 - surfaced to the client, never a fake verdict
        state.error = f"{type(exc).__name__}: {exc}"
        state.stage = InvestigationStage.FAILED


@router.post("/investigations/{investigation_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_investigation(investigation_id: str, background: BackgroundTasks) -> dict[str, str]:
    state = _get(investigation_id)
    if state.project_id:
        info, source = _project(state.project_id)
        label = f"project/{info.name}"
    elif state.example_case:
        source, label = EXAMPLES_ROOT / state.example_case, f"examples/{state.example_case}"
    else:
        raise HTTPException(
            status_code=422, detail="Choose a project or a bundled example before running."
        )
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


@router.get("/investigations/{investigation_id}/certificate", response_model=FixCertificate)
def get_certificate(investigation_id: str) -> FixCertificate:
    state = _get(investigation_id)
    if state.certificate is None:
        raise HTTPException(status_code=404, detail="No certificate yet")
    return state.certificate


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
