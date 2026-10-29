from app.agents.models import ReviewResult
from app.agents.parsing import parse_review_reply
from app.llm.nebius import NebiusClient

SYSTEM_PROMPT = """You are a strict code reviewer. Decide whether the patch fully resolves the
issue, satisfies the contracts documented in the code, and introduces no regressions. You cannot
run code; judge by reading. Reply in exactly this format:
VERDICT: ACCEPT or VERDICT: REJECT
DEFECT: <one concrete defect, if rejecting> (one line per defect)"""


class SelfReviewAgent:
    """Comparison baseline only: an LLM reviewing an LLM patch, with no execution evidence."""

    def __init__(self, client: NebiusClient | None = None) -> None:
        self.client = client or NebiusClient()

    def review(self, *, issue: str, patch_diff: str, relevant_code: str) -> ReviewResult:
        return self.client.complete_parsed(
            system=SYSTEM_PROMPT,
            user=f"Issue:\n{issue}\n\nPatch:\n{patch_diff}\n\nCode after patch:\n{relevant_code}",
            parser=parse_review_reply,
        )
