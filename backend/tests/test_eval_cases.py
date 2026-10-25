"""Validates the benchmark *cases* (not any model): buggy code fails, the reference fix
passes the hidden oracle, and the plausible weak fix passes visible tests yet fails it."""

from app.evaluation import BenchmarkReport, TrialResult, load_cases, oracle_passes, summarize
from app.repair.patching import apply_patch
from app.sandbox.local import LocalSandbox
from app.verification.pytest_runner import run_pytest_check
from app.verification.results import CheckOutcome
from tests.conftest import fixture_text

PAIRS = {
    "auth-refresh-token": ("auth_correct.diff", "auth_weak.diff"),
    "paginate": ("paginate_correct.diff", "paginate_weak.diff"),
    "slugify": ("slugify_correct.diff", "slugify_weak.diff"),
    "dedupe": ("dedupe_correct.diff", "dedupe_weak.diff"),
    "intervals": ("intervals_correct.diff", "intervals_weak.diff"),
    "parse_bool": ("parse_bool_correct.diff", "parse_bool_weak.diff"),
    "truncate": ("truncate_correct.diff", "truncate_weak.diff"),
}


def visible_pass(sandbox, case, diff) -> bool:
    ws = sandbox.prepare_workspace(case.source_path)
    try:
        assert apply_patch(ws, diff)[0]
        return run_pytest_check(sandbox, ws, name="regression").outcome == CheckOutcome.PASSED
    finally:
        sandbox.destroy(ws)


def test_cases_discriminate_correct_from_weak_fixes() -> None:
    sandbox = LocalSandbox()
    cases = {c.name: c for c in load_cases()}
    assert set(cases) == set(PAIRS)
    for name, (good, weak) in PAIRS.items():
        case = cases[name]
        assert not oracle_passes(sandbox, case, None), f"{name}: buggy code must fail oracle"
        assert oracle_passes(sandbox, case, fixture_text(good)), f"{name}: reference fix"
        assert visible_pass(sandbox, case, fixture_text(weak)), f"{name}: weak passes visible"
        assert not oracle_passes(sandbox, case, fixture_text(weak)), f"{name}: weak fails oracle"


def test_summary_math() -> None:
    rows = [
        TrialResult(
            case="c", mode="m", trial=1, accepted=True, oracle_passed=False, false_accept=True
        ),
        TrialResult(case="c", mode="m", trial=2, accepted=True, oracle_passed=True, resolved=True),
        TrialResult(case="c", mode="m", trial=3, accepted=False, oracle_passed=False),
    ]
    s = summarize(BenchmarkReport(trials=rows))["m"]
    assert s["false_acceptance_rate_of_accepted"] == 0.5
    assert s["false_rejection_rate"] == 0.0
    assert abs(s["resolved_rate"] - 1 / 3) < 1e-9


def test_every_case_reproduces_red_on_unpatched_source() -> None:
    sandbox = LocalSandbox()
    for case in load_cases():
        ws = sandbox.prepare_workspace(case.source_path)
        try:
            red = run_pytest_check(
                sandbox,
                ws,
                name="reproduction_red",
                targets=case.repro_targets,
                expect_failure=True,
            )
            assert red.outcome == CheckOutcome.PASSED, f"{case.name}: {red.summary}"
        finally:
            sandbox.destroy(ws)


def test_score_trial_flags_false_acceptance_in_baseline_and_review_modes() -> None:
    from app.agents.models import ReviewResult
    from app.evaluation import score_trial
    from app.pipeline.runner import RepairPipeline
    from tests.doubles import ScriptedFixer
    from tests.test_pipeline import ScriptedReviewer

    sandbox = LocalSandbox()
    case = next(c for c in load_cases() if c.name == "paginate")
    weak = fixture_text("paginate_weak.diff")
    for mode, reviewer in (
        ("baseline", None),
        ("review", ScriptedReviewer([ReviewResult(accept=True)])),
    ):
        pipeline = RepairPipeline(
            sandbox=sandbox,
            fixer=ScriptedFixer([weak]),
            planner=None,
            reviewer=reviewer,
            max_iterations=2,
        )
        result = score_trial(sandbox, case, mode, 1, pipeline)
        assert result.accepted and result.oracle_passed is False and result.false_accept, mode
