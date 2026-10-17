import shutil

from app.agents.models import FileEdit, PatchProposal
from app.agents.parsing import parse_patch_reply
from app.pipeline.runner import RepairPipeline
from app.repair.edits import build_diff_from_edits
from app.repair.patching import apply_patch
from app.sandbox.local import LocalSandbox
from app.verification.results import CheckOutcome, VerificationVerdict
from tests.conftest import fixture_text
from tests.doubles import PAGINATE_ADVERSARIAL, ScriptedPlanner

SEARCH = "    start = page * per_page\n"
GOOD = FileEdit(
    path="paginate.py",
    search=SEARCH,
    replace=(
        "    if page < 1 or per_page < 1:\n"
        '        raise ValueError("page and per_page must be >= 1")\n'
        "    start = (page - 1) * per_page\n"
    ),
)


def test_live_bare_hunk_diff_is_rejected_with_actionable_hint(paginate_src, tmp_path) -> None:
    """Regression for a real Nemotron reply: '@@' without line numbers."""
    ws = tmp_path / "ws"
    shutil.copytree(paginate_src, ws)
    ok, message = apply_patch(ws, fixture_text("live_bare_hunk.diff"))
    assert not ok and "line numbers" in message


def test_edit_becomes_a_valid_applying_diff(paginate_src, tmp_path) -> None:
    diff, errors = build_diff_from_edits(paginate_src, [GOOD])
    assert errors == [] and diff.startswith("--- a/paginate.py\n+++ b/paginate.py\n@@ -")
    ws = tmp_path / "ws"
    shutil.copytree(paginate_src, ws)
    ok, message = apply_patch(ws, diff)
    assert ok, message
    assert "(page - 1) * per_page" in (ws / "paginate.py").read_text()


def test_search_not_found_gives_hint_and_no_diff(paginate_src) -> None:
    bad = FileEdit(path="paginate.py", search="    start = page*per_page\n", replace="x\n")
    diff, errors = build_diff_from_edits(paginate_src, [bad])
    assert diff == "" and "not found" in errors[0] and "start = page * per_page" in errors[0]


def test_ambiguous_search_is_rejected(tmp_path) -> None:
    (tmp_path / "m.py").write_text("x = 1\nx = 1\n")
    diff, errors = build_diff_from_edits(
        tmp_path, [FileEdit(path="m.py", search="x = 1", replace="x = 2")]
    )
    assert diff == "" and "matches 2 places" in errors[0]


def test_unsafe_path_and_noop_edit_rejected(paginate_src) -> None:
    assert build_diff_from_edits(paginate_src, [FileEdit(path="../x.py", search="a", replace="b")])[
        1
    ]
    same = FileEdit(path="paginate.py", search=SEARCH, replace=SEARCH)
    assert "no change" in build_diff_from_edits(paginate_src, [same])[1][0]


def test_edit_on_crlf_file_applies_and_keeps_crlf(paginate_src, tmp_path) -> None:
    ws = tmp_path / "ws"
    shutil.copytree(paginate_src, ws)
    path = ws / "paginate.py"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    diff, errors = build_diff_from_edits(ws, [GOOD])
    assert errors == []
    ok, message = apply_patch(ws, diff)
    assert ok, message
    result = path.read_bytes()
    assert b"(page - 1)" in result and result.count(b"\n") == result.count(b"\r\n")


def test_parse_edit_blocks_including_empty_replacement() -> None:
    raw = (
        "SUMMARY: fix\nRATIONALE: why\n"
        "FILE: a.py\n<<<<<<< SEARCH\nold = 1\n=======\nnew = 1\n>>>>>>> REPLACE\n"
        "FILE: b.py\n<<<<<<< SEARCH\nremove me\n=======\n>>>>>>> REPLACE\n"
    )
    patch = parse_patch_reply(raw)
    assert [(e.path, e.search, e.replace) for e in patch.edits] == [
        ("a.py", "old = 1", "new = 1"),
        ("b.py", "remove me", ""),
    ]
    assert patch.summary == "fix"


class EditFixer:
    def __init__(self, attempts: list[list[FileEdit]]) -> None:
        self.attempts, self.feedback = attempts, []

    def propose(self, *, feedback=None, **_) -> PatchProposal:
        self.feedback.append(feedback)
        edits = self.attempts[min(len(self.feedback) - 1, len(self.attempts) - 1)]
        return PatchProposal(summary="edit", rationale="r", edits=edits)


def test_failed_edit_feedback_is_actionable_and_second_attempt_is_verified(paginate_src) -> None:
    wrong = FileEdit(path="paginate.py", search="    start = page*per_page\n", replace="y\n")
    fixer = EditFixer([[wrong], [GOOD]])
    cert = RepairPipeline(
        sandbox=LocalSandbox(), fixer=fixer, planner=ScriptedPlanner([PAGINATE_ADVERSARIAL])
    ).run(
        source=paginate_src,
        issue="paginate returns the wrong slice",
        repro_targets=["test_paginate.py::test_second_page_returns_items_4_to_6"],
    )
    first = next(c for c in cert.iterations[0].checks if c.name == "patch_applies_in_scope")
    assert first.outcome == CheckOutcome.FAILED and "not found" in first.summary
    assert "not found" in (fixer.feedback[1] or "") and "Closest line" in (fixer.feedback[1] or "")
    assert len(cert.iterations) == 2
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert cert.final_patch and cert.final_patch.startswith("--- a/paginate.py")
