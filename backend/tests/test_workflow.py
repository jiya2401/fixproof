import pytest

from app.orchestrator.engine import WorkflowEngine, WorkflowError
from app.orchestrator.state import InvestigationStage, InvestigationState


def test_valid_transition() -> None:
    state = InvestigationState(repo_url="https://example.com/repo", issue="A reproducible bug exists")
    engine = WorkflowEngine()
    engine.transition(state, InvestigationStage.REPRODUCING)
    assert state.stage == InvestigationStage.REPRODUCING


def test_invalid_transition() -> None:
    state = InvestigationState(repo_url="https://example.com/repo", issue="A reproducible bug exists")
    engine = WorkflowEngine()
    with pytest.raises(WorkflowError):
        engine.transition(state, InvestigationStage.VERIFYING)
