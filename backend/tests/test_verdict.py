from app.verification.results import (
    CheckOutcome,
    CheckResult,
    CheckRole,
    SandboxInfo,
    VerificationReport,
    VerificationVerdict,
)
from app.verification.verdict import MANDATORY_CHECKS, determine_verdict, evaluate_policy

CONTAINER = SandboxInfo(kind="docker", isolation="container", isolation_self_tested=True)


def check(name: str, outcome=CheckOutcome.PASSED, tests=1, **kw) -> CheckResult:
    role = CheckRole.PRECONDITION if name == "reproduction_red" else CheckRole.CORRECTNESS
    return CheckResult(name=name, outcome=outcome, tests_executed=tests, role=role, **kw)


def full_report(**overrides) -> VerificationReport:
    checks = [check(name) for name in MANDATORY_CHECKS if name not in overrides]
    checks += [overrides[n] for n in MANDATORY_CHECKS if n in overrides]
    return VerificationReport(checks=checks, sandbox=CONTAINER)


def test_verified_only_when_everything_executed_and_isolated() -> None:
    assert determine_verdict(full_report()) == VerificationVerdict.VERIFIED


def test_single_passing_check_is_not_enough() -> None:
    report = VerificationReport(checks=[check("reproduction_green")], sandbox=CONTAINER)
    assert determine_verdict(report) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_empty_report_is_insufficient() -> None:
    assert determine_verdict(VerificationReport()) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_counterexample_means_not_verified() -> None:
    report = full_report(
        adversarial=check("adversarial", CheckOutcome.FAILED, counterexamples=["x"])
    )
    decision = evaluate_policy(report)
    assert decision.verdict == VerificationVerdict.NOT_VERIFIED
    assert "adversarial" in decision.reasons[0]


def test_failed_regression_means_not_verified() -> None:
    report = full_report(regression=check("regression", CheckOutcome.FAILED))
    assert determine_verdict(report) == VerificationVerdict.NOT_VERIFIED


def test_failure_beats_missing_evidence() -> None:
    report = VerificationReport(
        checks=[check("regression", CheckOutcome.FAILED)], sandbox=CONTAINER
    )
    assert determine_verdict(report) == VerificationVerdict.NOT_VERIFIED


def test_generated_test_that_errors_is_not_a_pass() -> None:
    report = full_report(adversarial=check("adversarial", CheckOutcome.ERROR))
    assert determine_verdict(report) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_skipped_check_is_not_a_pass() -> None:
    report = full_report(adversarial=check("adversarial", CheckOutcome.SKIPPED))
    assert determine_verdict(report) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_pass_with_zero_executed_tests_is_not_evidence() -> None:
    report = full_report(adversarial=check("adversarial", CheckOutcome.PASSED, tests=0))
    assert determine_verdict(report) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_unreproduced_bug_is_insufficient_not_not_verified() -> None:
    red = check("reproduction_red", CheckOutcome.FAILED, summary="bug not reproduced")
    assert determine_verdict(full_report(reproduction_red=red)) == (
        VerificationVerdict.INSUFFICIENT_EVIDENCE
    )


def test_missing_mandatory_check_is_insufficient() -> None:
    report = full_report()
    report.checks = [c for c in report.checks if c.name != "regression"]
    assert determine_verdict(report) == VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_process_sandbox_caps_verdict_at_conditions() -> None:
    report = full_report()
    report.sandbox = SandboxInfo(kind="local-process", isolation="process")
    assert determine_verdict(report) == VerificationVerdict.VERIFIED_WITH_CONDITIONS


def test_untested_container_isolation_caps_verdict() -> None:
    report = full_report()
    report.sandbox = SandboxInfo(kind="docker", isolation="container", isolation_self_tested=False)
    assert determine_verdict(report) == VerificationVerdict.VERIFIED_WITH_CONDITIONS


def test_failed_optional_check_downgrades_to_conditions() -> None:
    report = full_report()
    report.checks.append(
        CheckResult(name="mutation", required=False, outcome=CheckOutcome.FAILED, tests_executed=1)
    )
    decision = evaluate_policy(report)
    assert decision.verdict == VerificationVerdict.VERIFIED_WITH_CONDITIONS
    assert any("mutation" in r for r in decision.reasons)


def test_limitations_downgrade_to_conditions() -> None:
    report = full_report()
    report.limitations = ["flaky reproduction"]
    assert determine_verdict(report) == VerificationVerdict.VERIFIED_WITH_CONDITIONS
