import difflib

from app.agents.models import AdversarialTest, VerificationPlan
from app.pipeline.runner import RepairPipeline
from app.sandbox.local import LocalSandbox
from app.verification.contest import find_contests
from app.verification.results import CheckOutcome, VerificationVerdict
from tests.conftest import REPO_ROOT, fixture_text
from tests.doubles import ScriptedFixer

TARGET = ["test_paginate.py::test_second_page_returns_items_4_to_6"]
QUOTE = "Return the items on a 1-indexed ``page``"
ORIGINAL = (REPO_ROOT / "examples" / "paginate-app" / "paginate.py").read_text()
HEAD = (
    "    if page < 1 or per_page < 1:\n"
    "        raise ValueError\n"
    "    start = (page - 1) * per_page\n"
)
CORRECT_BODY = HEAD + "    return list(items[start : start + per_page])\n"
CORRUPTED_BODY = (
    HEAD
    + "    if start + per_page > len(items):\n"
    + "        return []\n"
    + "    return items[start : start + per_page]\n"
)
OLD_BODY = "    start = page * per_page\n    return list(items[start : start + per_page])\n"


def diff_to(body: str, comment: str = "") -> str:
    new = ORIGINAL.replace(OLD_BODY, body + comment)
    return "".join(
        difflib.unified_diff(
            ORIGINAL.splitlines(True),
            new.splitlines(True),
            fromfile="a/paginate.py",
            tofile="b/paginate.py",
        )
    )


def attack(name: str, code: str) -> AdversarialTest:
    return AdversarialTest(name=name, rationale=name, spec_quote=QUOTE, code=code)


# Wrong: page 3 of [1..5] with per_page=2 is [5], not []  (the live mistake)
WRONG = attack(
    "docstring_example",
    "from paginate import paginate\n\ndef test_docstring_example():\n"
    "    assert paginate([1, 2, 3, 4, 5], 3, 2) == []\n",
)
PER_PAGE_LARGER = attack(
    "per_page_larger_than_items",
    "from paginate import paginate\n\ndef test_per_page_larger_than_items():\n"
    "    assert paginate([1, 2, 3], 1, 5) == [1, 2, 3]\n",
)
PARTIAL_LAST = attack(
    "partial_last_page_not_empty",
    "from paginate import paginate\n\ndef test_partial_last_page_not_empty():\n"
    "    assert paginate([1, 2, 3], 2, 2) == [3]\n",
)


class SequencePlanner:
    def __init__(self, rounds: list[list[AdversarialTest]]) -> None:
        self.rounds, self.calls = rounds, 0

    def plan(self, **_kwargs) -> VerificationPlan:
        tests = self.rounds[min(self.calls, len(self.rounds) - 1)]
        self.calls += 1
        return VerificationPlan(tests=tests)


def run(src, diffs, rounds, max_iterations):
    fixer = ScriptedFixer(diffs)
    cert = RepairPipeline(
        sandbox=LocalSandbox(), fixer=fixer, planner=SequencePlanner(rounds),
        max_iterations=max_iterations,
    ).run(source=src, issue="paginate returns the wrong slice", repro_targets=TARGET)  # fmt: skip
    return cert, fixer


def test_find_contests_unit() -> None:
    results = {
        1: {"t": "failed", "s1": "passed", "s2": "passed"},
        2: {"t": "passed", "s1": "failed", "s2": "failed"},
    }
    (contest,) = find_contests(results)
    assert contest.only_second_satisfies == ["t"] and contest.only_first_satisfies == ["s1", "s2"]
    assert contest.keys == {"t", "s1", "s2"}
    # compatible progress is not a contest
    assert (
        find_contests({1: {"a": "failed", "b": "passed"}, 2: {"a": "passed", "b": "passed"}}) == []
    )
    # a test missing from one attempt cannot create a contest
    assert find_contests({1: {"a": "failed"}, 2: {"b": "failed", "a": "passed"}}) == []


def test_live_scenario_wrong_test_corrupted_patch_contradiction_is_detected(paginate_src) -> None:
    cert, fixer = run(
        paginate_src,
        [diff_to(CORRECT_BODY), diff_to(CORRUPTED_BODY), diff_to(CORRECT_BODY, "    # v3\n")],
        [[WRONG], [PER_PAGE_LARGER, PARTIAL_LAST]],
        max_iterations=3,
    )
    first, second = cert.iterations[0], cert.iterations[1]
    # attempt 1 (correct patch) is rejected only by the wrong test...
    assert first.counterexamples and "docstring_example" in first.counterexamples[0]
    # ...attempt 2 (corrupted patch) satisfies it but breaks the later tests
    assert not any("docstring_example" in c for c in second.counterexamples)
    # cross-running shows the contradiction: attempt 1 passes the later tests, fails the wrong one
    assert first.test_results["docstring_example"] == "failed"
    assert first.test_results["per_page_larger_than_items"] == "passed"
    assert second.test_results["docstring_example"] == "passed"
    assert second.test_results["per_page_larger_than_items"] == "failed"
    assert {"docstring_example", "per_page_larger_than_items"} <= set(cert.contested)
    # the fixer is warned instead of being steered by a possibly wrong test
    assert "WARNING - contradictory attack tests" in (fixer.calls[2] or "")
    # the certificate reports the least-bad attempt, not the corrupted last one
    assert cert.selected_attempt in (1, 3)
    assert "if start + per_page > len(items)" not in (cert.final_patch or "")
    assert any("Contradictory attack tests" in lim for lim in cert.limitations)
    assert (
        cert.verdict == VerificationVerdict.NOT_VERIFIED
    )  # still a grounded failure: needs a human


def test_compatible_progress_reports_the_last_attempt_without_a_contest(auth_src) -> None:
    from tests.doubles import AUTH_ADVERSARIAL

    weak, good = fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")
    cert = RepairPipeline(
        sandbox=LocalSandbox(),
        fixer=ScriptedFixer([weak, good]),
        planner=SequencePlanner([[AUTH_ADVERSARIAL]]),
        max_iterations=3,
    ).run(
        source=auth_src,
        issue="refresh tokens are rejected",
        repro_targets=["test_auth.py"],
    )
    assert cert.contested == [] and cert.selected_attempt == 2
    assert cert.iterations[0].test_results["unknown_token_type"] == "failed"
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert next(c for c in cert.checks if c.name == "adversarial").outcome == CheckOutcome.PASSED


# --- human dispute / re-verification ---------------------------------------------------------


def contested_run(paginate_src):
    return run(
        paginate_src,
        [diff_to(CORRECT_BODY), diff_to(CORRUPTED_BODY)],
        [[WRONG], [PER_PAGE_LARGER, PARTIAL_LAST]],
        max_iterations=2,
    )[0]


def reverify(
    src, base, attempt, disputed, reason="page 3 of [1..5] with per_page=2 is [5], not []"
):
    return RepairPipeline.for_reverification(LocalSandbox()).reverify(
        source=src, issue="paginate returns the wrong slice", repro_targets=TARGET,
        base=base, attempt=attempt, disputed=disputed, reason=reason,
    )  # fmt: skip


def test_disputing_the_wrong_test_re_verifies_the_correct_patch_with_a_recorded_condition(
    paginate_src,
) -> None:
    base = contested_run(paginate_src)
    assert base.verdict == VerificationVerdict.NOT_VERIFIED and base.selected_attempt == 1

    cert = reverify(paginate_src, base, 1, ["docstring_example"])  # no model: _NoModel would raise

    adversarial = next(c for c in cert.checks if c.name == "adversarial")
    assert adversarial.outcome == CheckOutcome.PASSED and adversarial.tests_executed == 2
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert cert.derived_from == base.certificate_sha256 and cert.reverified_attempt == 1
    assert len(cert.iterations) == len(base.iterations) + 1  # history is preserved, not rewritten
    assert cert.final_patch == base.iterations[0].diff
    disputed = {t.key: t for t in cert.adversarial_tests}["docstring_example"]
    assert disputed.disputed and "[5]" in disputed.dispute_reason
    assert any(
        lim.startswith("Human review:") and "docstring_example" in lim for lim in cert.limitations
    )
    assert cert.hash_is_valid()


def test_a_dispute_cannot_launder_a_genuinely_bad_patch(paginate_src) -> None:
    base = contested_run(paginate_src)
    # re-verify the corrupted attempt 2, disputing the only test it fails that ISN'T spec-valid...
    # it still fails the two correct tests, so the verdict must stay negative.
    cert = reverify(paginate_src, base, 2, ["per_page_larger_than_items"])
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED
    assert any("partial_last_page_not_empty" in c for c in cert.iterations[-1].counterexamples)


def test_disputing_every_grounded_test_leaves_no_evidence(paginate_src) -> None:
    base = contested_run(paginate_src)
    cert = reverify(
        paginate_src, base, 1,
        ["docstring_example", "per_page_larger_than_items", "partial_last_page_not_empty"],
    )  # fmt: skip
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
