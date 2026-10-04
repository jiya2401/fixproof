from dataclasses import dataclass

from app.sandbox.base import CommandResult


@dataclass(slots=True)
class RedGreenEvidence:
    before: CommandResult
    after: CommandResult

    @property
    def established(self) -> bool:
        return (not self.before.passed) and self.after.passed
