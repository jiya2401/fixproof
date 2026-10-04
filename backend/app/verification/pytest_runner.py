from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner


def run_pytest(
    sandbox: SandboxRunner,
    workspace: Path,
    targets: list[str] | None = None,
    timeout_seconds: int = 180,
) -> CommandResult:
    command = ["python", "-m", "pytest", "-q"]
    if targets:
        command.extend(targets)
    return sandbox.run(workspace, command, timeout_seconds=timeout_seconds)
