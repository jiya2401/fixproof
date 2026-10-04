from app.agents.models import VerificationPlan
from app.llm.nebius import NebiusClient


SYSTEM_PROMPT = """You are FixProof's adversarial verification planner.
Assume the proposed patch may be insufficient. Design the cheapest high-value experiments
most likely to falsify it. You design verification; you do not issue the final verdict.
Do not inherit or repeat the repair agent's confidence.
"""


class VerificationPlannerAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def plan(
        self,
        *,
        issue: str,
        patch_diff: str,
        reproduction_evidence: str,
        impact_context: str,
    ) -> VerificationPlan:
        data = self.client.complete_json(
            system=SYSTEM_PROMPT,
            user=(
                f"Original issue:\n{issue}\n\nCandidate patch:\n{patch_diff}\n\n"
                f"Original reproduction evidence:\n{reproduction_evidence}\n\n"
                f"Impact context:\n{impact_context}\n\n"
                "Return keys: adversarial_scenarios, invariants, regression_targets, "
                "suggested_commands, risk_areas."
            ),
        )
        return VerificationPlan.model_validate(data)
