from app.agents.models import AdversarialTest
from app.certificate import FixCertificate
from app.pipeline.runner import RepairPipeline
from app.sandbox.local import LocalSandbox
from app.verification.results import CheckOutcome, VerificationVerdict
from tests.conftest import fixture_text
from tests.doubles import (
    AUTH_ADVERSARIAL,
    PAGINATE_ADVERSARIAL,
    ScriptedFixer,
    ScriptedInvestigator,
    ScriptedPlanner,
)

AUTH_ISSUE = "validate_refresh_token accepts access tokens and rejects refresh tokens."


def run(src, fixer, planner, targets, issue=AUTH_ISSUE, max_iterations=3, investigator=None):
    pipeline = RepairPipeline(
        sandbox=LocalSandbox(), fixer=fixer, planner=planner,
        investigator=investigator, max_iterations=max_iterations,
    )  # fmt: skip
    return pipeline.run(source=src, issue=issue, repro_targets=targets, source_label=src.name)


def check(cert: FixCertificate, name: str, iteration: int = -1):
    pool = cert.iterations[iteration].checks if cert.iterations else cert.checks
    return next(c for c in pool if c.name == name)


def test_weak_fix_is_rejected_by_executed_counterexample_then_repaired(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")])
    planner = ScriptedPlanner([AUTH_ADVERSARIAL])
    cert = run(auth_src, fixer, planner, ["test_auth.py"], investigator=ScriptedInvestigator())

    assert len(cert.iterations) == 2
    first = cert.iterations[0]
    # The weak patch passes every *visible* check...
    assert check(cert, "reproduction_green", 0).outcome == CheckOutcome.PASSED
    assert check(cert, "regression", 0).outcome == CheckOutcome.PASSED
    # ...and is rejected only by the executed adversarial test.
    adv = check(cert, "adversarial", 0)
    assert adv.outcome == CheckOutcome.FAILED and adv.tests_executed == 1
    assert any("unknown_token_type" in c for c in first.counterexamples)
    # The counterexample was fed back to the fixer.
    assert fixer.calls[0] is None and "unknown_token_type" in (fixer.calls[1] or "")
    # Second attempt re-ran every mandatory check and passed.
    for name in ("reproduction_green", "regression", "adversarial"):
        assert check(cert, name, 1).outcome == CheckOutcome.PASSED
    assert cert.checks[0].name == "reproduction_red"
    assert cert.checks[0].outcome == CheckOutcome.PASSED
    # Local sandbox is process-level only, so the verdict is capped.
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert any("sandbox isolation" in r for r in cert.verdict_reasons)
    assert cert.final_patch_sha256 == cert.iterations[1].patch_sha256
    assert cert.hash_is_valid()


def test_baseline_would_accept_the_weak_fix_that_fixproof_rejects(auth_src) -> None:
    weak = ScriptedFixer([fixture_text("auth_weak.diff")])
    baseline = run(auth_src, weak, None, ["test_auth.py"], max_iterations=1)
    assert check(baseline, "reproduction_green").outcome == CheckOutcome.PASSED
    assert check(baseline, "regression").outcome == CheckOutcome.PASSED  # baseline accepts
    fixproof = run(
        auth_src, ScriptedFixer([fixture_text("auth_weak.diff")]),
        ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"], max_iterations=1,
    )  # fmt: skip
    assert fixproof.verdict == VerificationVerdict.NOT_VERIFIED
    # Without the adversarial phase there is no positive verdict at all.
    assert baseline.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_repeated_patch_gets_one_warning_then_stops(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_weak.diff")])
    cert = run(
        auth_src, fixer, ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"], max_iterations=5
    )
    notes = [i.note for i in cert.iterations]
    assert len(cert.iterations) == 3  # verified once, warned on first repeat, stopped on second
    assert "repeated" in notes[1] and "stopping" in notes[2]
    assert "IDENTICAL" in (fixer.calls[2] or "")
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_distinct_failing_patches_stop_at_max_iterations(paginate_src) -> None:
    weak = fixture_text("paginate_weak.diff")
    other = weak.replace("page - 1", "page-1")
    cert = run(
        paginate_src, ScriptedFixer([weak, other]), ScriptedPlanner([PAGINATE_ADVERSARIAL]),
        ["test_paginate.py::test_second_page_returns_items_4_to_6"], max_iterations=2,
        issue="paginate returns the wrong slice",
    )  # fmt: skip
    assert len(cert.iterations) == 2  # budget enforced; loop did not run a third attempt
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_paginate_contract_violation_found_then_fixed(paginate_src) -> None:
    cert = run(
        paginate_src,
        ScriptedFixer([fixture_text("paginate_weak.diff"), fixture_text("paginate_correct.diff")]),
        ScriptedPlanner([PAGINATE_ADVERSARIAL]),
        ["test_paginate.py::test_second_page_returns_items_4_to_6"],
        issue="paginate returns the wrong slice",
    )  # fmt: skip
    assert check(cert, "adversarial", 0).outcome == CheckOutcome.FAILED
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert len(cert.iterations) == 2


def test_unreproduced_bug_stops_before_any_model_call(auth_src, tmp_path) -> None:
    import shutil

    fixed = tmp_path / "fixed"
    shutil.copytree(auth_src, fixed)
    (fixed / "auth.py").write_text(
        (fixed / "auth.py").read_text().replace('== "access"', '== "refresh"')
    )
    fixer = ScriptedFixer([fixture_text("auth_correct.diff")])
    cert = run(fixed, fixer, ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"])
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert fixer.calls == [] and cert.iterations == []
    assert cert.checks[0].name == "reproduction_red"


def test_patch_editing_tests_is_rejected(auth_src) -> None:
    cheat = (
        "--- a/test_auth.py\n+++ b/test_auth.py\n@@ -1,9 +1,9 @@\n"
        " from auth import validate_refresh_token\n \n \n"
        " def test_refresh_token_is_accepted() -> None:\n"
        '-    assert validate_refresh_token("refresh:abc123") is True\n'
        "+    assert True\n \n \n"
        " def test_access_token_is_rejected() -> None:\n"
        '     assert validate_refresh_token("access:abc123") is False\n'
    )
    cert = run(auth_src, ScriptedFixer([cheat]), ScriptedPlanner([AUTH_ADVERSARIAL]),
               ["test_auth.py"], max_iterations=1)  # fmt: skip
    scope = check(cert, "patch_applies_in_scope")
    assert scope.outcome == CheckOutcome.FAILED and "protected" in scope.summary
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_unparseable_adversarial_test_is_not_a_pass(auth_src) -> None:
    bad = AdversarialTest(name="broken", rationale="x", code="def test_x(:\n")
    cert = run(auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]),
               ScriptedPlanner([bad]), ["test_auth.py"], max_iterations=1)  # fmt: skip
    adv = check(cert, "adversarial")
    assert adv.outcome == CheckOutcome.ERROR
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_skipped_adversarial_test_is_not_a_pass(auth_src) -> None:
    skipper = AdversarialTest(
        name="skipper", rationale="x",
        spec_quote="Return True only for refresh tokens",
        code="import pytest\n\ndef test_x():\n    pytest.skip('later')\n",
    )  # fmt: skip
    cert = run(auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]),
               ScriptedPlanner([skipper]), ["test_auth.py"], max_iterations=1)  # fmt: skip
    adv = check(cert, "adversarial")
    assert adv.outcome == CheckOutcome.ERROR and adv.tests_executed == 0
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_model_failure_never_yields_positive_verdict(auth_src) -> None:
    class Boom:
        def propose(self, **_):
            raise RuntimeError("endpoint down")

    cert = run(auth_src, Boom(), ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"])
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert any("model call failed" in lim for lim in cert.limitations)


def test_certificate_is_tamper_evident(auth_src) -> None:
    cert = run(auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]),
               ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"])  # fmt: skip
    restored = FixCertificate.model_validate_json(cert.model_dump_json())
    assert restored.hash_is_valid()
    restored.verdict = VerificationVerdict.VERIFIED
    assert not restored.hash_is_valid()


def test_source_tree_is_not_modified(auth_src) -> None:
    before = (auth_src / "auth.py").read_text()
    run(auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]),
        ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"])  # fmt: skip
    assert (auth_src / "auth.py").read_text() == before


def test_baseline_mode_stops_once_visible_checks_pass(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")])
    cert = run(auth_src, fixer, None, ["test_auth.py"], max_iterations=3)
    assert len(cert.iterations) == 1 and len(fixer.calls) == 1


# --- spec grounding of model-authored tests ---------------------------------------------------

UNGROUNDED_WHITESPACE = AdversarialTest(
    name="space_after_colon",
    rationale="invented whitespace rule",
    spec_quote="values must not start with a space",  # not in the issue or any docstring
    code=(
        "from auth import validate_refresh_token\n\n"
        "def test_space_after_colon():\n"
        "    assert validate_refresh_token('refresh: abc123') is False\n"
    ),
)


def test_ungrounded_failing_test_is_a_condition_not_a_veto_and_not_fed_back(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_correct.diff")])
    planner = ScriptedPlanner([AUTH_ADVERSARIAL, UNGROUNDED_WHITESPACE])
    cert = run(auth_src, fixer, planner, ["test_auth.py"], max_iterations=3)

    grounded = check(cert, "adversarial", 0)
    ungrounded = check(cert, "adversarial_ungrounded", 0)
    assert grounded.outcome == CheckOutcome.PASSED and grounded.tests_executed == 1
    recorded = {t.name: t for t in cert.adversarial_tests}
    assert recorded["unknown_token_type"].grounded and recorded["unknown_token_type"].spec_quote
    assert (
        not recorded["space_after_colon"].grounded
        and "def test_" in recorded["space_after_colon"].code
    )
    assert ungrounded.outcome == CheckOutcome.FAILED and not ungrounded.required
    assert len(cert.iterations) == 1 and fixer.calls == [None]  # nothing fed back
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert any("adversarial_ungrounded" in r for r in cert.verdict_reasons)


def test_grounded_failing_test_still_vetoes_and_shows_its_spec_quote(auth_src) -> None:
    cert = run(
        auth_src,
        ScriptedFixer([fixture_text("auth_weak.diff")]),
        ScriptedPlanner([AUTH_ADVERSARIAL, UNGROUNDED_WHITESPACE]),
        ["test_auth.py"],
        max_iterations=1,
    )
    adv = check(cert, "adversarial", 0)
    assert adv.outcome == CheckOutcome.FAILED
    assert any('[SPEC: "Return True only for refresh tokens"]' in c for c in adv.counterexamples)
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_only_ungrounded_tests_means_insufficient_evidence(auth_src) -> None:
    cert = run(
        auth_src,
        ScriptedFixer([fixture_text("auth_correct.diff")]),
        ScriptedPlanner([UNGROUNDED_WHITESPACE]),
        ["test_auth.py"],
        max_iterations=1,
    )
    adv = check(cert, "adversarial")
    assert adv.outcome == CheckOutcome.ERROR and "no spec-grounded" in adv.summary
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


# --- planner failures and cumulative feedback ------------------------------------------------


class FlakyPlanner:
    """Succeeds on the first call, then fails like a malformed live Nemotron reply."""

    def __init__(self, tests) -> None:
        self.tests, self.calls = tests, 0

    def plan(self, **_kwargs):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("Nemotron reply failed parsing: no TEST blocks")
        return ScriptedPlanner(self.tests).plan()


def test_planner_failure_still_runs_earlier_tests_and_is_a_condition(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")])
    cert = run(auth_src, fixer, FlakyPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"])
    second = check(cert, "adversarial", 1)
    assert second.outcome == CheckOutcome.PASSED and second.tests_executed == 1  # old test ran
    assert "planner failed" in second.summary
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert any("planner failed" in lim for lim in cert.limitations)


def test_planner_failure_with_no_earlier_tests_is_insufficient(auth_src) -> None:
    class AlwaysFails:
        def plan(self, **_):
            raise RuntimeError("boom")

    cert = run(
        auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]), AlwaysFails(),
        ["test_auth.py"], max_iterations=1,
    )  # fmt: skip
    adv = check(cert, "adversarial")
    assert adv.outcome == CheckOutcome.ERROR and "planner failed" in adv.summary
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_feedback_accumulates_counterexamples_across_attempts(auth_src) -> None:
    weak2 = fixture_text("auth_weak.diff").replace(
        '+    return token_type != "access"', '+    return bool(token_type != "access")'
    )
    fixer = ScriptedFixer(
        [fixture_text("auth_weak.diff"), weak2, fixture_text("auth_correct.diff")]
    )
    cert = run(
        auth_src, fixer, FlakyPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"], max_iterations=3
    )
    third = fixer.calls[2] or ""
    assert "All counterexamples found so far" in third and "unknown_token_type" in third
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS


# --- self-review baseline (LLM reviews LLM; nothing executed) ---------------------------------


class ScriptedReviewer:
    def __init__(self, results) -> None:
        self.results, self.calls = results, 0

    def review(self, **_kwargs):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


def run_review(src, fixer, reviewer, targets, max_iterations=3):
    pipeline = RepairPipeline(
        sandbox=LocalSandbox(), fixer=fixer, planner=None, reviewer=reviewer,
        max_iterations=max_iterations,
    )  # fmt: skip
    return pipeline.run(source=src, issue=AUTH_ISSUE, repro_targets=targets)


def test_self_review_can_reject_and_feed_back_defects(auth_src) -> None:
    from app.agents.models import ReviewResult

    fixer = ScriptedFixer([fixture_text("auth_weak.diff"), fixture_text("auth_correct.diff")])
    reviewer = ScriptedReviewer(
        [
            ReviewResult(accept=False, defects=["accepts unknown token types"]),
            ReviewResult(accept=True),
        ]
    )
    cert = run_review(auth_src, fixer, reviewer, ["test_auth.py"])
    assert len(cert.iterations) == 2 and reviewer.calls == 2
    assert "accepts unknown token types" in (fixer.calls[1] or "")
    assert check(cert, "self_review", 0).outcome == CheckOutcome.FAILED
    assert check(cert, "self_review", 1).outcome == CheckOutcome.PASSED


def test_self_review_that_accepts_a_weak_patch_is_not_evidence(auth_src) -> None:
    from app.agents.models import ReviewResult

    cert = run_review(
        auth_src, ScriptedFixer([fixture_text("auth_weak.diff")]),
        ScriptedReviewer([ReviewResult(accept=True)]), ["test_auth.py"],
    )  # fmt: skip
    assert len(cert.iterations) == 1  # the loop stopped: reviewer said fine
    # ...yet the real counterexample exists: the weak patch fails the executed contract test.
    assert (
        cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
    )  # no executed adversarial evidence


def test_review_failure_is_treated_as_no_objection(auth_src) -> None:
    cert = run_review(
        auth_src, ScriptedFixer([fixture_text("auth_correct.diff")]),
        ScriptedReviewer([RuntimeError("unparseable")]), ["test_auth.py"],
    )  # fmt: skip
    review = check(cert, "self_review")
    assert review.outcome == CheckOutcome.ERROR and len(cert.iterations) == 1


# --- code context given to the model ---------------------------------------------------------


def test_collect_code_puts_failing_test_first_and_traceback_files_before_others(tmp_path) -> None:
    from app.pipeline.runner import collect_code

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert f() == 1\n")
    (tmp_path / "a_unrelated.py").write_text("A = 1\n")
    (tmp_path / "z_buggy.py").write_text("def f():\n    return 2\n")
    text = collect_code(
        tmp_path, focus_text="/work/z_buggy.py:2: AssertionError", test_files=["tests/test_x.py"]
    )
    order = [text.index(n) for n in ("tests/test_x.py", "z_buggy.py", "a_unrelated.py")]
    assert order == sorted(order)
    assert "read-only context, do not edit" in text


# --- real projects: pre-existing failures must not be blamed on the patch ---------------------

CALC = (
    "def add(a, b):\n"
    '    """Return the sum of a and b."""\n'
    "    return a - b\n\n\n"
    "def mul(a, b):\n"
    "    return a * b\n"
)
CALC_TESTS = {
    "calc.py": CALC,
    "test_calc.py": (
        "from calc import add, mul\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    ),
    "test_unrelated.py": "def test_unrelated():\n    assert False\n",  # fails before and after
    "test_broken_import.py": "import zzz_missing_pkg_for_test\n\ndef test_z():\n    pass\n",
}
CALC_SPEC_TEST = AdversarialTest(
    name="add_sums",
    rationale="documented contract",
    spec_quote="Return the sum of a and b",
    code=(
        "from calc import add\n\n"
        "def test_add_sums():\n    assert add(-1, 1) == 0\n    assert add(2, 3) == 5\n"
    ),
)


def calc_project(tmp_path):
    for name, content in CALC_TESTS.items():
        (tmp_path / name).write_text(content)
    return tmp_path


def calc_diff(new_calc: str) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            CALC.splitlines(True),
            new_calc.splitlines(True),
            fromfile="a/calc.py",
            tofile="b/calc.py",
        )
    )


def run_calc(src, diff, planner=None):
    pipeline = RepairPipeline(
        sandbox=LocalSandbox(), fixer=ScriptedFixer([diff]),
        planner=planner or ScriptedPlanner([CALC_SPEC_TEST]), max_iterations=1,
    )  # fmt: skip
    return pipeline.run(
        source=src,
        issue="add() subtracts instead of adding",
        repro_targets=["test_calc.py::test_add"],
    )


def test_preexisting_failures_are_excluded_but_disclosed(tmp_path) -> None:
    cert = run_calc(calc_project(tmp_path), calc_diff(CALC.replace("a - b", "a + b")))
    regression = check(cert, "regression")
    assert regression.outcome == CheckOutcome.PASSED
    assert "pre-existing failure(s) unchanged" in regression.summary
    assert any("already failing before the patch" in lim for lim in cert.limitations)
    assert cert.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS


def test_a_patch_that_breaks_another_passing_test_is_a_regression(tmp_path) -> None:
    broken = CALC.replace("a - b", "a + b").replace("return a * b", "return a + b")
    cert = run_calc(calc_project(tmp_path), calc_diff(broken))
    regression = check(cert, "regression")
    assert regression.outcome == CheckOutcome.FAILED
    assert any("test_calc.py::test_mul" in c for c in regression.counterexamples)
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_a_patch_that_makes_tests_vanish_is_a_regression(tmp_path) -> None:
    vanishing = "import zzz_missing_pkg_for_test\n" + CALC.replace("a - b", "a + b")
    cert = run_calc(calc_project(tmp_path), calc_diff(vanishing))
    assert check(cert, "regression").outcome == CheckOutcome.FAILED
    assert cert.verdict == VerificationVerdict.NOT_VERIFIED


def test_no_usable_baseline_means_insufficient_evidence(tmp_path, monkeypatch) -> None:
    from app.verification.suite import SuiteRun

    monkeypatch.setattr("app.pipeline.runner.run_suite", lambda *a, **k: SuiteRun(timed_out=True))
    cert = run_calc(calc_project(tmp_path), calc_diff(CALC.replace("a - b", "a + b")))
    reg = check(cert, "regression")
    assert reg.outcome == CheckOutcome.ERROR and "baseline" in reg.summary
    assert cert.verdict == VerificationVerdict.INSUFFICIENT_EVIDENCE
