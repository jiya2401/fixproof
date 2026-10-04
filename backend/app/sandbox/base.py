from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


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
