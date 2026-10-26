"""Whole-suite runs with per-test outcomes, and baseline-aware regression comparison.

Real projects already have failing tests. A patch must not be blamed for those, but it must not
break anything that used to pass. So the full suite is run once before the patch (baseline) and
once after; regression means: a test that passed before no longer passes (including tests that
vanished, e.g. through a new import error).
"""

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from pydantic import BaseModel, Field

from app.sandbox.base import SandboxRunner

JUNIT = ".fixproof_junit_suite.xml"


class SuiteRun(BaseModel):
    exit_code: int | None = None
    timed_out: bool = False
    duration_seconds: float = 0.0
    outcomes: dict[str, str] = Field(default_factory=dict)  # node id -> passed|failed|error|skipped
    command: str = ""
    stdout_sha256: str = ""
    excerpt: str = ""

    @property
    def usable(self) -> bool:
        """pytest ran to completion: all passed (0) or some failed/errored (1), and we saw tests."""
        return not self.timed_out and self.exit_code in (0, 1) and bool(self.outcomes)

    def count(self, outcome: str) -> int:
        return sum(1 for o in self.outcomes.values() if o == outcome)

    @property
    def executed(self) -> int:
        return self.count("passed") + self.count("failed")


class SuiteDiff(BaseModel):
    regressions: list[str] = Field(default_factory=list)
    still_failing: list[str] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)


def _node_id(case: ET.Element) -> str:
    file = (case.get("file") or "").replace("\\", "/")
    classname, name = case.get("classname") or "", case.get("name") or ""
    if not file:  # xunit1 should always give `file`; fall back to the dotted names
        return f"{classname}::{name}" if classname else name
    if not classname:  # collection error: the "test" is the module itself
        return file
    module = file.removesuffix(".py").replace("/", ".")
    klass = classname.removeprefix(module).lstrip(".")
    return "::".join(part for part in (file, klass.replace(".", "::"), name) if part)


def parse_outcomes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return {}
    outcomes: dict[str, str] = {}
    for case in root.iter("testcase"):
        if case.find("skipped") is not None:
            outcome = "skipped"
        elif case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        else:
            outcome = "passed"
        outcomes[_node_id(case)] = outcome
    return outcomes


def run_suite(sandbox: SandboxRunner, workspace: Path, timeout_seconds: int = 180) -> SuiteRun:
    result = sandbox.run(
        workspace,
        [
            "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--continue-on-collection-errors", "-o", "junit_family=xunit1", f"--junitxml={JUNIT}",
        ],
        timeout_seconds=timeout_seconds,
    )  # fmt: skip
    return SuiteRun(
        exit_code=result.exit_code, timed_out=result.timed_out,
        duration_seconds=round(result.duration_seconds, 3),
        outcomes=parse_outcomes(workspace / JUNIT), command=result.command,
        stdout_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),
        excerpt=(result.stdout + "\n" + result.stderr).strip()[-4000:],
    )  # fmt: skip


def compare(before: SuiteRun, after: SuiteRun) -> SuiteDiff:
    diff = SuiteDiff()
    for node, was in before.outcomes.items():
        now = after.outcomes.get(node)  # None = no longer collected
        if was == "passed" and now != "passed":
            diff.regressions.append(node)
        elif was in ("failed", "error"):
            (diff.fixed if now == "passed" else diff.still_failing).append(node)
    return diff


def matches_target(node_id: str, targets: list[str]) -> bool:
    return any(node_id == t or node_id.startswith(t + "::") for t in targets)
