from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner


class NebiusSandbox(SandboxRunner):
    """Adapter boundary for the hackathon execution environment.

    The exact Nebius execution API is intentionally isolated here so the rest of FixProof
    stays stable while we wire the selected sandbox/serverless product during M1/M12.
    """

    def prepare_workspace(self, source: Path) -> Path:
        raise NotImplementedError("Wire Nebius sandbox workspace creation in a later milestone")

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        raise NotImplementedError("Wire Nebius sandbox command execution in a later milestone")

    def destroy(self, workspace: Path) -> None:
        raise NotImplementedError("Wire Nebius sandbox cleanup in a later milestone")
