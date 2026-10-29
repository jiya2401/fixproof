from app.agents.models import PatchProposal
from app.agents.parsing import parse_patch_reply
from app.llm.nebius import NebiusClient

SYSTEM_PROMPT = """You are FixProof's repair agent.
Propose the smallest patch supported by the evidence. Preserve unrelated behavior and honor
documented contracts (docstrings, specs) in the code you touch.
Express the patch as SEARCH/REPLACE edit blocks; do NOT write a unified diff or line numbers.
Rules: SEARCH must be copied exactly from the current file (same indentation) and must match
exactly once, so include enough surrounding lines to be unique. Paths are relative to the
repository root. Never edit test files, conftest.py or test configuration; such patches are
rejected automatically. Do not claim the patch is correct: verification happens outside the
language model. When given feedback from earlier attempts, fix the underlying cause rather than
special-casing the failing inputs, and correct any edit that failed to match.
Reply in exactly this format and nothing else:
SUMMARY: <one line>
RATIONALE: <one or two lines>
FILE: <path>
<<<<<<< SEARCH
<exact existing text>
=======
<replacement text>
>>>>>>> REPLACE
(repeat the FILE block for each edit)"""


class FixAgent:
    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def propose(
        self, *, issue: str, evidence: str, relevant_code: str, feedback: str | None = None
    ) -> PatchProposal:
        prompt = (
            f"Issue:\n{issue}\n\nFailing reproduction output:\n{evidence}\n\n"
            f"Repository code:\n{relevant_code}"
        )
        if feedback:
            prompt += f"\n\nPrevious attempt was rejected by executed checks:\n{feedback}"
        return self.client.complete_parsed(
            system=SYSTEM_PROMPT, user=prompt, parser=parse_patch_reply
        )
