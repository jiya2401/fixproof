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


def test_iteration_budget_is_bounded_and_ends_not_verified(auth_src) -> None:
    fixer = ScriptedFixer([fixture_text("auth_weak.diff")])
    cert = run(
        auth_src, fixer, ScriptedPlanner([AUTH_ADVERSARIAL]), ["test_auth.py"], max_iterations=3
    )
    # Same patch twice => repeat detected on iteration 2, loop stops early.
    assert len(cert.iterations) == 2 and "repeated" in cert.iterations[1].note
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
