from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, HttpUrl

from app.certificate import FixCertificate
from app.config import get_settings
from app.llm.nebius import NebiusConfigurationError
from app.orchestrator.state import InvestigationStage, InvestigationState
from app.pipeline import factory
from app.sandbox.factory import SandboxUnavailable

router = APIRouter(prefix="/api/v1")

_INVESTIGATIONS: dict[str, InvestigationState] = {}

EXAMPLES_ROOT = Path(__file__).resolve().parents[3] / "examples"
# Allowlist: this release repairs only bundled example repositories. Arbitrary repository
# URLs are recorded but not cloned or executed (untrusted-code policy).
EXAMPLE_CASES: dict[str, list[str]] = {
    "buggy-python-app": ["test_auth.py"],
    "paginate-app": ["test_paginate.py::test_second_page_returns_items_4_to_6"],
}
_STAGE_MAP = {
    "reproducing": InvestigationStage.REPRODUCING,
    "investigating": InvestigationStage.INVESTIGATING,
    "fixing": InvestigationStage.FIXING,
    "planning_verification": InvestigationStage.PLANNING_VERIFICATION,
    "verifying": InvestigationStage.VERIFYING,
    "repairing": InvestigationStage.REPAIRING,
}


class CreateInvestigationRequest(BaseModel):
    repo_url: HttpUrl
    issue: str
    example_case: str | None = None


@router.get("/about")
def about() -> dict[str, Any]:
    settings = get_settings()
    return {
        "name": "FixProof",
        "tagline": "AI proposes the fix. Evidence earns the merge.",
        "status": "vertical_slice",
        "target_scope": "Python + pytest repositories (bundled example cases only)",
        "nebius_model": settings.nebius_model,
        "nebius_configured": bool(settings.nebius_api_key),
        "sandbox_mode": settings.sandbox_mode,
        "example_cases": sorted(EXAMPLE_CASES),
        "implemented_now": [
            "red/green reproduction",
            "patch scope validation + apply",
            "regression run",
            "model-authored adversarial tests executed in sandbox",
            "bounded repair loop with counterexample feedback",
            "verdict policy v1 + sealed Fix Certificate",
        ],
        "not_implemented": [
            "hypothesis experiments",
            "Hypothesis property tests",
            "mutation testing",
            "arbitrary repository cloning",
            "Nebius-hosted execution",
        ],
    }


@router.post(
    "/investigations", response_model=InvestigationState, status_code=status.HTTP_201_CREATED
)
def create_investigation(payload: CreateInvestigationRequest) -> InvestigationState:
    issue = payload.issue.strip()
    if len(issue) < 10:
        raise HTTPException(
            status_code=422, detail="Issue description must be at least 10 characters"
        )
    if payload.example_case is not None and payload.example_case not in EXAMPLE_CASES:
        raise HTTPException(status_code=422, detail="Unknown example_case")
    state = InvestigationState(
        repo_url=str(payload.repo_url),
        issue=issue,
        example_case=payload.example_case,
        repro_targets=EXAMPLE_CASES.get(payload.example_case or "", []),
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


def _execute(state: InvestigationState, pipeline: Any) -> None:
    try:
        cert = pipeline.run(
            source=EXAMPLES_ROOT / str(state.example_case),
            issue=state.issue,
            repro_targets=state.repro_targets,
            investigation_id=state.id,
            source_label=f"examples/{state.example_case}",
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
    if state.example_case is None:
        raise HTTPException(
            status_code=422,
            detail="This release repairs bundled example cases only; set example_case.",
        )
    if state.stage not in (InvestigationStage.CREATED, InvestigationStage.FAILED):
        raise HTTPException(status_code=409, detail=f"Investigation is {state.stage}")

    def on_event(stage: str, _message: str) -> None:
        if stage in _STAGE_MAP:
            state.stage = _STAGE_MAP[stage]

    try:
        pipeline = factory.build_pipeline(on_event)
    except (NebiusConfigurationError, SandboxUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    state.error = None
    state.stage = InvestigationStage.REPRODUCING
    background.add_task(_execute, state, pipeline)
    return {"status": "accepted", "investigation_id": state.id}


@router.get("/investigations/{investigation_id}/certificate", response_model=FixCertificate)
def get_certificate(investigation_id: str) -> FixCertificate:
    state = _get(investigation_id)
    if state.certificate is None:
        raise HTTPException(status_code=404, detail="No certificate yet")
    return state.certificate
