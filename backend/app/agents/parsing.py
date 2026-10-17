"""Plain-text reply formats for model output that contains code.

Diffs and test modules are fragile inside JSON strings (unescaped quotes/newlines broke a
live Nemotron reply). These formats put code in fenced blocks and parse them deterministically.
"""

import re

from app.agents.models import AdversarialTest, PatchProposal, VerificationPlan

_DIFF_BLOCK = re.compile(r"```(?:diff|patch)?[ \t]*\n(.*?)\n```", re.DOTALL)
_TEST_BLOCK = re.compile(
    r"^###[ \t]*TEST[ \t]+([A-Za-z0-9_\-]+)[^\n]*\n(?:RATIONALE:[ \t]*(.*?)\n)?"
    r"```(?:python)?[ \t]*\n(.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{name}:[ \t]*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_patch_reply(raw: str) -> PatchProposal:
    block = _DIFF_BLOCK.search(raw)
    if not block:
        raise ValueError("no fenced ```diff block found")
    diff = block.group(1)
    if "--- " not in diff or "+++ " not in diff:
        raise ValueError("fenced block is not a unified diff (missing ---/+++ headers)")
    head = raw[: block.start()]
    return PatchProposal(
        summary=_field(head, "SUMMARY") or "model-proposed patch",
        rationale=_field(head, "RATIONALE"),
        diff=diff + "\n",
    )


def parse_verification_reply(raw: str) -> VerificationPlan:
    tests = [
        AdversarialTest(
            name=m.group(1), rationale=(m.group(2) or "").strip(), code=m.group(3) + "\n"
        )
        for m in _TEST_BLOCK.finditer(raw)
    ]
    if not tests:
        raise ValueError("no '### TEST <name>' blocks with fenced python code found")
    invariants = re.findall(r"^INVARIANT:[ \t]*(.+)$", raw, re.MULTILINE)
    risks = re.findall(r"^RISK:[ \t]*(.+)$", raw, re.MULTILINE)
    return VerificationPlan(tests=tests, invariants=invariants, risk_areas=risks)
