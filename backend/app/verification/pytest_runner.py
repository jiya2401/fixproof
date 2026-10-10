import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner
from app.verification.results import CheckOutcome, CheckResult, CheckRole

_EXCERPT_CHARS = 4000


def _junit_summary(path: Path) -> dict[str, object]:
    summary: dict[str, object] = {
        "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "failing": [], "erroring": [],
    }  # fmt: skip
    if not path.exists():
        return summary
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return summary
    for case in root.iter("testcase"):
        summary["tests"] = int(summary["tests"]) + 1  # type: ignore[call-overload]
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        if case.find("skipped") is not None:
            summary["skipped"] = int(summary["skipped"]) + 1  # type: ignore[call-overload]
        elif (bad := case.find("failure")) is not None:
            summary["failures"] = int(summary["failures"]) + 1  # type: ignore[call-overload]
            summary["failing"].append(f"{name}: {(bad.get('message') or '')[:300]}")  # type: ignore[attr-defined]
        elif (bad := case.find("error")) is not None:
            summary["errors"] = int(summary["errors"]) + 1  # type: ignore[call-overload]
            summary["erroring"].append(f"{name}: {(bad.get('message') or '')[:300]}")  # type: ignore[attr-defined]
    return summary


def run_pytest(
    sandbox: SandboxRunner,
    workspace: Path,
    targets: list[str] | None = None,
    timeout_seconds: int = 180,
    junit_name: str = ".fixproof_junit.xml",
) -> CommandResult:
    command = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit_name}"]
    if targets:
        command.extend(targets)
    return sandbox.run(workspace, command, timeout_seconds=timeout_seconds)


def run_pytest_check(
    sandbox: SandboxRunner,
    workspace: Path,
    *,
    name: str,
    targets: list[str] | None = None,
    role: CheckRole = CheckRole.CORRECTNESS,
    timeout_seconds: int = 180,
    expect_failure: bool = False,
) -> CheckResult:
    """Run pytest and translate exit code + JUnit XML into an honest CheckResult.

    Distinguishes: tests ran and passed / tests ran and a counterexample failed /
    the run itself broke (collection error, timeout, no tests, crash).
    With expect_failure=True (bug reproduction) a failing test is the *good* outcome.
    """
    junit = f".fixproof_junit_{name}.xml"
    result = run_pytest(sandbox, workspace, targets, timeout_seconds, junit_name=junit)
    stats = _junit_summary(workspace / junit)
    executed = int(stats["tests"]) - int(stats["skipped"]) - int(stats["errors"])  # type: ignore[call-overload]
    failing: list[str] = list(stats["failing"])  # type: ignore[call-overload]
    erroring: list[str] = list(stats["erroring"])  # type: ignore[call-overload]
    combined = (result.stdout + "\n" + result.stderr).strip()
    check = CheckResult(
        name=name, role=role, command=result.command, exit_code=result.exit_code,
        duration_seconds=round(result.duration_seconds, 3), tests_executed=max(executed, 0),
        stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
        output_excerpt=combined[-_EXCERPT_CHARS:],
    )  # fmt: skip

    if result.timed_out:
        check.outcome, check.summary = CheckOutcome.ERROR, "timed out"
    elif result.exit_code == 0:
        if executed < 1:
            check.outcome, check.summary = CheckOutcome.ERROR, "exit 0 but no tests executed"
        elif expect_failure:
            check.outcome = CheckOutcome.FAILED
            check.summary = "bug not reproduced: tests passed before the patch"
        else:
            check.outcome, check.summary = CheckOutcome.PASSED, f"{executed} test(s) passed"
    elif result.exit_code == 1 and failing:
        check.counterexamples = failing
        if expect_failure:
            check.outcome = CheckOutcome.PASSED
            check.summary = f"failure reproduced ({len(failing)} failing test(s))"
        else:
            check.outcome = CheckOutcome.FAILED
            check.summary = f"{len(failing)} failing test(s)"
    else:
        check.outcome = CheckOutcome.ERROR
        detail = erroring[0] if erroring else f"pytest exit code {result.exit_code}"
        check.summary = f"execution problem: {detail}"
        check.counterexamples = []
    if int(stats["skipped"]):  # type: ignore[call-overload]
        check.summary += f" ({stats['skipped']} skipped, not counted)"
    return check
