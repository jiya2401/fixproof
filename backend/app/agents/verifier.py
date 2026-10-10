from app.agents.models import VerificationPlan
from app.llm.nebius import NebiusClient

SYSTEM_PROMPT = """You are FixProof's adversarial test designer.
Assume the candidate patch is insufficient. Write executable pytest tests that would expose
the most likely remaining defects: boundary values, malformed input, inputs the patch's
condition mishandles, and violations of the documented contract (read the docstrings).
Tests must be deterministic, import the code under test directly, avoid network/filesystem
side effects, and must not use pytest.skip or xfail. You do not decide whether the patch is
correct; the tests will be run by deterministic tooling and the results decide.
Return JSON: {"tests": [{"name": str, "rationale": str, "code": str}],
"invariants": [str], "risk_areas": [str]} where code is a complete pytest module."""


class VerificationPlannerAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def plan(
        self,
        *,
        issue: str,
        patch_diff: str,
        reproduction_evidence: str,
        relevant_code: str,
        prior_counterexamples: list[str] | None = None,
    ) -> VerificationPlan:
        prompt = (
            f"Original issue:\n{issue}\n\nCandidate patch:\n{patch_diff}\n\n"
            f"Original failing reproduction:\n{reproduction_evidence}\n\n"
            f"Code after patch:\n{relevant_code}"
        )
        if prior_counterexamples:
            prompt += "\n\nCounterexamples already found:\n" + "\n".join(prior_counterexamples)
        return self.client.complete_model(
            system=SYSTEM_PROMPT, user=prompt, schema=VerificationPlan
        )
