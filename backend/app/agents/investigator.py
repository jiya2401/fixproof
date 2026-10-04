from app.agents.models import InvestigationPlan
from app.llm.nebius import NebiusClient


SYSTEM_PROMPT = """You are FixProof's software failure investigator.
Your job is to form falsifiable root-cause hypotheses, not to jump directly to a patch.
Prefer minimal repository context and concrete reproduction evidence.
Never claim a command ran unless tool evidence says it ran.
"""


class InvestigatorAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def plan(self, *, issue: str, repository_context: str) -> InvestigationPlan:
        data = self.client.complete_json(
            system=SYSTEM_PROMPT,
            user=(
                f"Issue:\n{issue}\n\nRepository context:\n{repository_context}\n\n"
                "Return keys: relevant_files, hypotheses, reproduction_steps."
            ),
        )
        return InvestigationPlan.model_validate(data)
