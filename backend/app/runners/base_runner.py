"""Abstract LanguageRunner protocol for FixProof.

Every concrete runner (Python, JS/TS, Go) implements this protocol so the
pipeline can call ``run_tests()`` and ``reproduce_bug()`` without knowing
which toolchain is involved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.runners.detector import Language
from app.runners.schema import TestRunResult
from app.sandbox.base import CommandResult, SandboxRunner


@runtime_checkable
class LanguageRunner(Protocol):
    """Protocol satisfied by all concrete language runners.

    Attributes
    ----------
    language:
        The language this runner handles.  Set as a class attribute.
    """

    language: Language

    # ------------------------------------------------------------------
    # Core operations (must be implemented)
    # ------------------------------------------------------------------

    def run_tests(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run the full test suite and return a normalised result.

        Parameters
        ----------
        sandbox:
            The low-level process/container runner.
        workspace:
            Absolute path to the working copy of the project.
        timeout_seconds:
            Maximum wall-clock seconds before the run is killed.
        """
        ...

    def reproduce_bug(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        targets: list[str] | None = None,
        timeout_seconds: int = 180,
    ) -> TestRunResult:
        """Run targeted tests to confirm the bug is present (pre-patch).

        Semantics: a **failing** test suite is the *expected* outcome here.
        The result's ``ok`` attribute will be ``False`` when the bug is
        successfully reproduced.

        Parameters
        ----------
        sandbox:
            The low-level process/container runner.
        workspace:
            Absolute path to the working copy of the project.
        targets:
            Optional list of test identifiers / file paths to focus on.
        timeout_seconds:
            Maximum wall-clock seconds before the run is killed.
        """
        ...

    def install_deps(
        self,
        sandbox: SandboxRunner,
        workspace: Path,
        timeout_seconds: int = 120,
    ) -> CommandResult:
        """Install / download project dependencies inside the workspace.

        This is a best-effort operation — callers should tolerate failure
        gracefully (the sandbox image may already have dependencies cached).

        Parameters
        ----------
        sandbox:
            The low-level process/container runner.
        workspace:
            Absolute path to the working copy of the project.
        timeout_seconds:
            Maximum wall-clock seconds for the install step.
        """
        ...

    def build_command(self, targets: list[str] | None = None) -> list[str]:
        """Return the shell command list for running tests.

        Used by the pipeline to log / audit the exact command invoked.
        """
        ...

