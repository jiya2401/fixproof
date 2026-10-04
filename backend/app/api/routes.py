from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, HttpUrl

from app.config import get_settings
from app.orchestrator.state import InvestigationState

router = APIRouter(prefix="/api/v1")

_INVESTIGATIONS: dict[str, InvestigationState] = {}


class CreateInvestigationRequest(BaseModel):
    repo_url: HttpUrl
    issue: str


@router.get("/about")
def about() -> dict[str, Any]:
    settings = get_settings()
    return {
        "name": "FixProof",
        "tagline": "AI proposes the fix. Evidence earns the merge.",
        "status": "core_scaffold",
        "target_scope": "Python + pytest repositories",
        "nebius_model": settings.nebius_model,
        "nebius_configured": bool(settings.nebius_api_key),
        "implemented_now": [
            "typed workflow state",
            "Nebius/Nemotron client wrapper",
            "agent contracts",
            "verification verdict policy",
            "Python AST code graph",
            "sandbox interfaces",
        ],
        "next_milestone": "M1 red/green repair loop",
    }


@router.post("/investigations", response_model=InvestigationState, status_code=status.HTTP_201_CREATED)
def create_investigation(payload: CreateInvestigationRequest) -> InvestigationState:
    issue = payload.issue.strip()
    if len(issue) < 10:
        raise HTTPException(status_code=422, detail="Issue description must be at least 10 characters")
    state = InvestigationState(repo_url=str(payload.repo_url), issue=issue)
    _INVESTIGATIONS[state.id] = state
    return state


@router.get("/investigations/{investigation_id}", response_model=InvestigationState)
def get_investigation(investigation_id: str) -> InvestigationState:
    try:
        return _INVESTIGATIONS[investigation_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Investigation not found") from exc
