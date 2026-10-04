from app.agents.models import PatchProposal
from app.llm.nebius import NebiusClient


SYSTEM_PROMPT = """You are FixProof's repair agent.
Propose the smallest patch supported by the evidence. Preserve unrelated behavior.
Do not claim the patch is correct; verification happens outside the language model.
"""


class FixAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def propose(self, *, issue: str, evidence: str, relevant_code: str) -> PatchProposal:
        data = self.client.complete_json(
            system=SYSTEM_PROMPT,
            user=(
                f"Issue:\n{issue}\n\nEvidence:\n{evidence}\n\nRelevant code:\n{relevant_code}\n\n"
                "Return keys: summary, rationale, diff. The diff must be a unified diff."
            ),
        )
        return PatchProposal.model_validate(data)
