from datetime import UTC, datetime

from app.orchestrator.state import InvestigationStage, InvestigationState

_ALLOWED_TRANSITIONS: dict[InvestigationStage, set[InvestigationStage]] = {
    InvestigationStage.CREATED: {InvestigationStage.REPRODUCING, InvestigationStage.FAILED},
    InvestigationStage.REPRODUCING: {
        InvestigationStage.INVESTIGATING,
        InvestigationStage.FAILED,
    },
    InvestigationStage.INVESTIGATING: {InvestigationStage.FIXING, InvestigationStage.FAILED},
    InvestigationStage.FIXING: {
        InvestigationStage.PLANNING_VERIFICATION,
        InvestigationStage.FAILED,
    },
    InvestigationStage.PLANNING_VERIFICATION: {
        InvestigationStage.VERIFYING,
        InvestigationStage.FAILED,
    },
    InvestigationStage.VERIFYING: {
        InvestigationStage.REPAIRING,
        InvestigationStage.COMPLETED,
        InvestigationStage.FAILED,
    },
    InvestigationStage.REPAIRING: {InvestigationStage.FIXING, InvestigationStage.FAILED},
    InvestigationStage.COMPLETED: set(),
    InvestigationStage.FAILED: set(),
}


class WorkflowError(ValueError):
    pass


class WorkflowEngine:
    """State transition guard for the repair pipeline.

    This starter deliberately does not fake autonomous repair. Upcoming milestones will
    attach concrete handlers to these stages.
    """

    def transition(
        self, state: InvestigationState, next_stage: InvestigationStage
    ) -> InvestigationState:
        if next_stage not in _ALLOWED_TRANSITIONS[state.stage]:
            raise WorkflowError(f"Invalid transition: {state.stage} -> {next_stage}")
        state.stage = next_stage
        state.updated_at = datetime.now(UTC)
        return state
