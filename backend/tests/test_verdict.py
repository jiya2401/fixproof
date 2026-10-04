from app.orchestrator.state import VerificationVerdict
from app.verification.results import CheckResult, VerificationReport
from app.verification.verdict import determine_verdict


def test_verified_when_all_required_checks_pass() -> None:
    report = VerificationReport(
        checks=[
            CheckResult(name="red-green", passed=True),
            CheckResult(name="regression", passed=True),
        ]
    )
    assert determine_verdict(report) == VerificationVerdict.VERIFIED


def test_not_verified_when_required_check_fails() -> None:
    report = VerificationReport(checks=[CheckResult(name="regression", passed=False)])
    assert determine_verdict(report) == VerificationVerdict.NOT_VERIFIED


def test_conditional_when_limitations_remain() -> None:
    report = VerificationReport(
        checks=[CheckResult(name="red-green", passed=True)],
        limitations=["Mutation testing was not available"],
    )
    assert determine_verdict(report) == VerificationVerdict.VERIFIED_WITH_CONDITIONS
