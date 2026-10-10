from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.verification.results import SandboxInfo


@dataclass(slots=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxRunner(ABC):
    @abstractmethod
    def prepare_workspace(self, source: Path) -> Path:
        raise NotImplementedError

    @abstractmethod
    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        raise NotImplementedError

    @abstractmethod
    def destroy(self, workspace: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def describe(self) -> SandboxInfo:
        """Honest description of the isolation actually provided."""
        raise NotImplementedError
