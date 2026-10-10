from app.agents.models import InvestigationPlan
from app.llm.nebius import NebiusClient

SYSTEM_PROMPT = """You are FixProof's software failure investigator.
Form several distinct, falsifiable root-cause hypotheses from the evidence, then name the
one best supported by the failing output and code. State your uncertainty.
Never claim a command ran unless the evidence shown says it ran.
Return JSON: {"relevant_files": [str], "hypotheses": [{"title": str, "rationale": str,
"suspect_files": [str]}], "selected_root_cause": str, "confidence_notes": str}"""


class InvestigatorAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def plan(self, *, issue: str, evidence: str, relevant_code: str) -> InvestigationPlan:
        return self.client.complete_model(
            system=SYSTEM_PROMPT,
            user=(
                f"Issue:\n{issue}\n\nFailing reproduction output:\n{evidence}\n\n"
                f"Repository code:\n{relevant_code}"
            ),
            schema=InvestigationPlan,
        )
