from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner


class DockerSandbox(SandboxRunner):
    """Production-oriented adapter placeholder for M1.

    The interface is committed now so the agent layer never depends on host subprocesses.
    M1 will implement resource-limited Docker execution and later allow a Nebius-backed
    implementation behind the same contract.
    """

    def prepare_workspace(self, source: Path) -> Path:
        raise NotImplementedError("M1: implement isolated Docker workspace preparation")

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        raise NotImplementedError("M1: implement resource-limited Docker execution")

    def destroy(self, workspace: Path) -> None:
        raise NotImplementedError("M1: implement Docker sandbox cleanup")
