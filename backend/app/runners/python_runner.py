"""Python / pytest language runner for FixProof.

Delegates to the existing ``app.verification.pytest_runner`` module so that
the full JUnit XML parsing and ``CheckResult`` conversion pipeline is reused.
The ``TestRunResult`` returned here is suitable for frontend consumption and
for integration with the unified schema.
"""

from __future__ import annotations

from pathlib import Path

from app.runners.detector import Language
from app.runners.schema import FailureDetail, TestRunResult
from app.sandbox.base import CommandResult, SandboxRunner
from app.verification.pytest_runner import run_pytest


class PythonRunner:
    """pytest-based runner for Python projects."""

    language: Language = Language.PYTHON

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        """Return the pytest command list."""
        cmd = [
            "python", "-m", "pytest", "-q",
            "-p", "no:cacheprovider",
            "-o", "junit_family=xunit1",
            "--junitxml=.fixproof_junit.xml",
        ]
        if targets:
            cmd.extend(targets)
        return cmd

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def run_tests(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run the full pytest suite and return a unified ``TestRunResult``."""
        result = run_pytest(sandbox, workspace, timeout_seconds=timeout_seconds)
        return self._to_test_run_result(result, workspace)

    def reproduce_bug(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        targets: list[str] | None = None,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run targeted pytest tests (bug reproduction mode)."""
        result = run_pytest(sandbox, workspace, targets=targets, timeout_seconds=timeout_seconds)
        return self._to_test_run_result(result, workspace)

    def install_deps(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        timeout_seconds: int = 120,
    ) -> CommandResult:
        """Install dependencies via pip if a requirements.txt exists."""
        req = workspace / "requirements.txt"
        if req.is_file():
            return sandbox.run(
                workspace,
                ["pip", "install", "-r", "requirements.txt", "--quiet"],
                timeout_seconds=timeout_seconds,
            )
        # No requirements file — treat as a no-op success.
        from app.sandbox.base import CommandResult as CR
        return CR(command="(no requirements.txt)", exit_code=0, stdout="", stderr="",
                  duration_seconds=0.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_test_run_result(self, result: CommandResult, workspace: Path) -> TestRunResult:
        """Convert a raw pytest ``CommandResult`` into a ``TestRunResult``.

        Reuses the existing ``_junit_summary`` XML parser from pytest_runner
        to extract per-test details.
        """
        from app.verification.pytest_runner import _junit_summary  # type: ignore[attr-defined]

        if result.timed_out:
            return TestRunResult.timed_out_result(
                raw_output=(result.stdout + "\n" + result.stderr).strip()
            )

        stats = _junit_summary(workspace / ".fixproof_junit.xml")
        total = int(stats["tests"])
        failures_raw: list[str] = list(stats["failing"])  # type: ignore[assignment]
        erroring_raw: list[str] = list(stats["erroring"])  # type: ignore[assignment]
        skipped = int(stats["skipped"])
        failed_count = int(stats["failures"])
        error_count = int(stats["errors"])
        passed_count = total - failed_count - error_count - skipped

        failures: list[FailureDetail] = []
        for entry in failures_raw:
            # entry format: "ClassName::test_name: message text"
            name, _, msg = entry.partition(": ")
            failures.append(FailureDetail(test_name=name.strip(), message=msg.strip()))
        for entry in erroring_raw:
            name, _, msg = entry.partition(": ")
            failures.append(FailureDetail(test_name=name.strip(), message=f"[error] {msg.strip()}"))

        return TestRunResult(
            total_tests=total,
            passed=max(0, passed_count),
            failed=failed_count,
            errors=error_count,
            duration_seconds=round(result.duration_seconds, 3),
            failures=failures,
            raw_output=(result.stdout + "\n" + result.stderr).strip(),
        )

