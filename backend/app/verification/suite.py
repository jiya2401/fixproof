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


def run_suite(sandbox: SandboxRunner, workspace: Path, timeout_seconds: int = 180, runner=None) -> SuiteRun:
    """Run the full test suite and return a :class:`SuiteRun` for regression comparison.

    When *runner* is ``None`` the language is detected from *workspace* automatically
    via :func:`~app.runners.get_language_runner`.  Pass the runner explicitly from
    :class:`~app.pipeline.runner.RepairPipeline` to avoid a second filesystem scan.
    """
    if runner is None:
        from app.runners import get_language_runner
        runner = get_language_runner(workspace)

    # Use the runner's run_tests() to get a normalised TestRunResult, then
    # translate it into the SuiteRun schema the pipeline's regression check expects.
    trr = runner.run_tests(sandbox, workspace, timeout_seconds=timeout_seconds)

    # Build an outcomes dict: test_name -> "passed" | "failed" | "error"
    outcomes: dict[str, str] = {}
    for f in trr.failures:
        name = f.test_name
        outcomes[name] = "error" if name.startswith("(setup)") else "failed"

    # For Python we additionally parse JUnit XML so that passing test names are recorded
    # (TestRunResult only carries failing details, not the full per-test list).
    if runner.language.value == "python":
        for junit_candidate in (workspace / JUNIT, workspace / ".fixproof_junit.xml"):
            if junit_candidate.exists():
                for node, outcome in parse_outcomes(junit_candidate).items():
                    outcomes.setdefault(node, outcome)
                break
    else:
        # For Go / JS, record anonymous passed slots so the baseline-vs-post diff
        # notices when the passed-count drops (even without per-test names).
        for i in range(max(0, trr.passed)):
            outcomes.setdefault(f"__passed_{i}", "passed")

    inferred_exit = 0 if trr.ok else (1 if not trr.timed_out else -1)
    return SuiteRun(
        exit_code=inferred_exit,
        timed_out=trr.timed_out,
        duration_seconds=round(trr.duration_seconds, 3),
        outcomes=outcomes,
        command="",
        stdout_sha256=hashlib.sha256(trr.raw_output.encode()).hexdigest(),
        excerpt=trr.raw_output[-4000:],
    )


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
