from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner
from app.verification.results import SandboxInfo


class NebiusSandbox(SandboxRunner):
    """NOT IMPLEMENTED. Present only as an adapter boundary; the factory refuses to use it."""

    def prepare_workspace(self, source: Path) -> Path:
        raise NotImplementedError("Nebius sandbox execution is not implemented")

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        raise NotImplementedError("Nebius sandbox execution is not implemented")

    def destroy(self, workspace: Path) -> None:
        raise NotImplementedError("Nebius sandbox execution is not implemented")

    def describe(self) -> SandboxInfo:
        return SandboxInfo(kind="nebius", isolation="none", notes=["not implemented"])
