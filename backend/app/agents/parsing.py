"""Plain-text reply formats for model output that contains code.

Diffs and test modules are fragile inside JSON strings (unescaped quotes/newlines broke a
live Nemotron reply). These formats put code in fenced blocks and parse them deterministically.
"""

import re

from app.agents.models import (
    AdversarialTest,
    FileEdit,
    PatchProposal,
    ReviewResult,
    VerificationPlan,
)

_DIFF_BLOCK = re.compile(r"```(?:diff|patch)?[ \t]*\n(.*?)\n```", re.DOTALL)
_EDIT_BLOCK = re.compile(
    r"^FILE:[ \t]*(\S+)[ \t]*\n<<<<<<< SEARCH[ \t]*\n(.*?)\n?=======[ \t]*\n"
    r"(.*?)\n?>>>>>>> REPLACE",
    re.MULTILINE | re.DOTALL,
)
_TEST_BLOCK = re.compile(
    r"^#{2,4}[ \t]*TEST[ \t]*[:#\-]?[ \t]*([A-Za-z0-9_\-]+)[^\n]*\n(?:RATIONALE:[ \t]*([^\n]*)\n)?"
    r"(?:SPEC:[ \t]*([^\n]*)\n)?"
    r"```(?:python)?[ \t]*\n(.*?)\n```",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{name}:[ \t]*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_patch_reply(raw: str) -> PatchProposal:
    """Parse SEARCH/REPLACE edit blocks (preferred) or, as a fallback, one fenced unified diff."""
    edits = [
        FileEdit(path=m.group(1), search=m.group(2), replace=m.group(3))
        for m in _EDIT_BLOCK.finditer(raw)
    ]
    first = _EDIT_BLOCK.search(raw)
    if edits and first:
        head = raw[: first.start()]
        return PatchProposal(
            summary=_field(head, "SUMMARY") or "model-proposed patch",
            rationale=_field(head, "RATIONALE"),
            edits=edits,
        )
    block = _DIFF_BLOCK.search(raw)
    if not block:
        raise ValueError("no FILE/SEARCH/REPLACE edit blocks and no fenced ```diff block found")
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
            name=m.group(1),
            rationale=(m.group(2) or "").strip(),
            spec_quote=(m.group(3) or "").strip(),
            code=m.group(4) + "\n",
        )
        for m in _TEST_BLOCK.finditer(raw)
    ]
    if not tests:
        raise ValueError("no '### TEST <name>' blocks with fenced python code found")
    invariants = re.findall(r"^INVARIANT:[ \t]*(.+)$", raw, re.MULTILINE)
    risks = re.findall(r"^RISK:[ \t]*(.+)$", raw, re.MULTILINE)
    return VerificationPlan(tests=tests, invariants=invariants, risk_areas=risks)


def parse_review_reply(raw: str) -> ReviewResult:
    match = re.search(r"^VERDICT:[ \t]*(ACCEPT|REJECT)", raw, re.MULTILINE | re.IGNORECASE)
    if not match:
        raise ValueError("no 'VERDICT: ACCEPT|REJECT' line found")
    accept = match.group(1).upper() == "ACCEPT"
    defects = re.findall(r"^DEFECT:[ \t]*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
    if not accept and not defects:
        defects = ["reviewer rejected the patch without naming a defect"]
    return ReviewResult(accept=accept, defects=defects)
