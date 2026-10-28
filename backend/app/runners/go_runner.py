"""Go language runner for FixProof (go test).

Command mapping:
    run_tests()    →  go test -json ./...
    reproduce_bug()→  go test -json [<targets> | ./...]
    install_deps() →  go mod download

The raw NDJSON output from ``go test -json`` is parsed by
``app.runners.parsers.gotest_parser``.
"""

from __future__ import annotations

from pathlib import Path

from app.runners.detector import Language
from app.runners.parsers.gotest_parser import parse_gotest_json
from app.runners.schema import TestRunResult
from app.sandbox.base import CommandResult, SandboxRunner


class GoRunner:
    """go-test-based runner for Go projects."""

    language: Language = Language.GO

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        """Return the go test command list."""
        cmd = ["go", "test", "-json"]
        if targets:
            cmd.extend(targets)
        else:
            cmd.append("./...")
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
        """Run the full go test suite."""
        result = sandbox.run(workspace, self.build_command(), timeout_seconds=timeout_seconds)
        return self._parse(result)

    def reproduce_bug(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        targets: list[str] | None = None,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run targeted go tests (bug reproduction mode)."""
        result = sandbox.run(
            workspace, self.build_command(targets), timeout_seconds=timeout_seconds
        )
        return self._parse(result)

    def install_deps(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        timeout_seconds: int = 120,
    ) -> CommandResult:
        """Download Go module dependencies."""
        return sandbox.run(
            workspace,
            ["go", "mod", "download"],
            timeout_seconds=timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, result: CommandResult) -> TestRunResult:
        if result.timed_out:
            return TestRunResult.timed_out_result(
                raw_output=(result.stdout + "\n" + result.stderr).strip()
            )
        raw = (result.stdout + "\n" + result.stderr).strip()
        return parse_gotest_json(result.stdout, raw_output=raw)

