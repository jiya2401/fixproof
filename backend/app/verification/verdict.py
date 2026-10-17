"""Verdict policy v1.

A positive verdict is derived only from executed checks. Rules, in precedence order:

1. NOT_VERIFIED: a required CORRECTNESS check FAILED (concrete counterexample or failure).
2. INSUFFICIENT_EVIDENCE: a mandatory check is missing, a required check did not produce a
   trustworthy result (ERROR / SKIPPED / NOT_RUN), a PRECONDITION is not PASSED (e.g. the bug
   was never reproduced), or a check "passed" while executing zero tests.
3. VERIFIED_WITH_CONDITIONS: all required checks passed, but isolation is not verified
   container isolation, an optional check did not pass, or limitations were recorded.
4. VERIFIED: none of the above.

VERIFIED never means "proved correct": it means no counterexample was found by the executed
checks. The certificate always lists what was executed.
"""

from pydantic import BaseModel, Field

from app.verification.results import (
    CheckOutcome,
    CheckResult,
    CheckRole,
    VerificationReport,
    VerificationVerdict,
)

POLICY_VERSION = "1.0"

MANDATORY_CHECKS: tuple[str, ...] = (
    "reproduction_red",
    "patch_applies_in_scope",
    "reproduction_green",
    "regression",
    "adversarial",
)
# Checks that must have executed at least one test to count as evidence.
REQUIRES_EXECUTED_TESTS: frozenset[str] = frozenset(
    {"reproduction_red", "reproduction_green", "regression", "adversarial"}
)


class PolicyDecision(BaseModel):
    verdict: VerificationVerdict
    reasons: list[str] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION


def _effective_outcome(check: CheckResult) -> CheckOutcome:
    if (
        check.outcome == CheckOutcome.PASSED
        and check.name in REQUIRES_EXECUTED_TESTS
        and check.tests_executed < 1
    ):
        return CheckOutcome.NOT_RUN
    return check.outcome


def evaluate_policy(report: VerificationReport) -> PolicyDecision:
    by_name: dict[str, CheckResult] = {}
    for check in report.checks:
        by_name[check.name] = check  # later entries for the same name win

    failed: list[str] = []
    insufficient: list[str] = []

    for name in MANDATORY_CHECKS:
        if name not in by_name:
            insufficient.append(f"mandatory check '{name}' is missing")

    for check in report.checks:
        mandatory = check.name in MANDATORY_CHECKS
        if not (check.required or mandatory):
            continue
        outcome = _effective_outcome(check)
        if outcome == CheckOutcome.PASSED:
            continue
        if outcome == CheckOutcome.FAILED and check.role == CheckRole.CORRECTNESS:
            failed.append(f"'{check.name}' failed: {check.summary or 'counterexample found'}")
        else:
            detail = check.summary or outcome.value
            if outcome != check.outcome:
                detail = f"passed but executed {check.tests_executed} tests"
            insufficient.append(f"'{check.name}' is {outcome.value}: {detail}")

    if failed:
        return PolicyDecision(verdict=VerificationVerdict.NOT_VERIFIED, reasons=failed)
    if insufficient:
        return PolicyDecision(
            verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE, reasons=insufficient
        )

    conditions: list[str] = []
    if report.sandbox.isolation != "container" or not report.sandbox.isolation_self_tested:
        conditions.append(
            f"sandbox isolation is '{report.sandbox.isolation}' "
            f"(self-tested={report.sandbox.isolation_self_tested}); "
            "not verified container isolation"
        )
    for check in report.checks:
        if not check.required and check.name not in MANDATORY_CHECKS:
            if _effective_outcome(check) != CheckOutcome.PASSED:
                conditions.append(
                    f"optional check '{check.name}' is {check.outcome.value}: {check.summary}"
                )
    conditions.extend(report.limitations)
    if conditions:
        return PolicyDecision(
            verdict=VerificationVerdict.VERIFIED_WITH_CONDITIONS, reasons=conditions
        )
    return PolicyDecision(
        verdict=VerificationVerdict.VERIFIED,
        reasons=["all mandatory checks executed and no counterexample was found"],
    )


def determine_verdict(report: VerificationReport) -> VerificationVerdict:
    return evaluate_policy(report).verdict
