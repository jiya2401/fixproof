import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.sandbox.base import CommandResult, SandboxRunner


class UnsafeLocalExecutionDisabled(RuntimeError):
    pass


class LocalSandbox(SandboxRunner):
    """Development-only adapter.

    It is disabled by default because target repository code is untrusted. Production
    milestones should use an isolated container / Nebius sandbox implementation.
    """

    def __init__(self) -> None:
        if not get_settings().allow_unsafe_local_execution:
            raise UnsafeLocalExecutionDisabled(
                "Local target-code execution is disabled. Use an isolated sandbox."
            )

    def prepare_workspace(self, source: Path) -> Path:
        destination = Path(tempfile.mkdtemp(prefix="fixproof-local-")) / "repo"
        shutil.copytree(source, destination)
        return destination

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=" ".join(command),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=time.monotonic() - started,
        )

    def destroy(self, workspace: Path) -> None:
        shutil.rmtree(workspace.parent, ignore_errors=True)
