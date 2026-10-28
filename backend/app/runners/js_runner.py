"""JavaScript / TypeScript runner for FixProof (Vitest).

Command mapping:
    run_tests()    →  npx vitest run --reporter=json
    reproduce_bug()→  npx vitest run --reporter=json [<targets>]
    install_deps() →  npm install --prefer-offline

The raw Vitest JSON output is parsed by ``app.runners.parsers.vitest_parser``.
"""

from __future__ import annotations

from pathlib import Path

from app.runners.detector import Language
from app.runners.parsers.vitest_parser import parse_vitest_json
from app.runners.schema import TestRunResult
from app.sandbox.base import CommandResult, SandboxRunner


class JSRunner:
    """Vitest-based runner for JavaScript / TypeScript projects."""

    language: Language = Language.JS

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        """Return the Vitest command list."""
        cmd = ["npx", "vitest", "run", "--reporter=json"]
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
        """Run the full Vitest suite."""
        result = sandbox.run(workspace, self.build_command(), timeout_seconds=timeout_seconds)
        return self._parse(result)

    def reproduce_bug(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        targets: list[str] | None = None,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run targeted Vitest tests (bug reproduction mode)."""
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
        """Install npm dependencies."""
        return sandbox.run(
            workspace,
            ["npm", "install", "--prefer-offline", "--no-audit", "--no-fund"],
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
        return parse_vitest_json(result.stdout, raw_output=raw)

