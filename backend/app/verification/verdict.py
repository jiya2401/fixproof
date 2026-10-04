from app.orchestrator.state import VerificationVerdict
from app.verification.results import VerificationReport


def determine_verdict(report: VerificationReport) -> VerificationVerdict:
    required = [check for check in report.checks if check.required]

    if not required or any(not check.executed for check in required):
        return VerificationVerdict.INSUFFICIENT_EVIDENCE

    if any(not check.passed for check in required):
        return VerificationVerdict.NOT_VERIFIED

    if report.limitations:
        return VerificationVerdict.VERIFIED_WITH_CONDITIONS

    return VerificationVerdict.VERIFIED
