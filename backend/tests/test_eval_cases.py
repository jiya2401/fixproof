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
