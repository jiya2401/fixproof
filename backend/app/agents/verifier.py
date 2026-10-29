from app.agents.models import VerificationPlan
from app.agents.parsing import parse_verification_reply
from app.llm.nebius import NebiusClient

SYSTEM_PROMPT = """You are FixProof's adversarial test designer.
Assume the candidate patch is insufficient. Write executable pytest tests that would expose
the most likely remaining defects: boundary values, malformed input, inputs the patch's
condition mishandles, and violations of the documented contract (read the docstrings).
Tests must be deterministic, import the code under test directly, avoid network/filesystem
side effects, and must not use pytest.skip or xfail. You do not decide whether the patch is
correct; the tests will be run by deterministic tooling and the results decide.
Every test MUST enforce a requirement that is actually stated: quote, verbatim, the sentence
from the issue or from a docstring that the test enforces. Do not invent requirements (for
example whitespace, case or unicode behavior) that the issue and docstrings do not state;
if no stated rule covers an edge case, do not write a blocking test for it. Tests whose quote
is not found verbatim are only recorded as unvalidated notes and cannot reject a patch.
Reply in exactly this format (repeat the TEST block for each test; 3-6 tests):
### TEST <short_snake_case_name>
RATIONALE: <what this attacks>
SPEC: <verbatim sentence from the issue or a docstring>
```python
<complete pytest module>
```
Optionally add lines "INVARIANT: ..." and "RISK: ..." at the end."""


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
        return self.client.complete_parsed(
            system=SYSTEM_PROMPT, user=prompt, parser=parse_verification_reply
        )
