"""Scan a user project for failing tests so the user can pick what to repair, and validate
user-supplied reproduction targets before they are passed to pytest."""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.sandbox.base import SandboxRunner
from app.verification.pytest_runner import _junit_summary

_RESULT_LINE = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)
_MISSING_MODULE = re.compile(r"No module named '([\w.]+)'")
MAX_TARGETS = 10


class FailingTest(BaseModel):
    node_id: str
    message: str = ""


class ScanResult(BaseModel):
    exit_code: int | None = None
    timed_out: bool = False
    duration_seconds: float = 0.0
    tests: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failing_tests: list[FailingTest] = Field(default_factory=list)
    collection_errors: list[FailingTest] = Field(default_factory=list)
    missing_modules: list[str] = Field(default_factory=list)  # third-party, not in the image
    local_modules_unresolved: list[str] = Field(default_factory=list)  # project's own modules
    hint: str = ""
    output_excerpt: str = ""


class TargetError(ValueError):
    pass


def validate_repro_targets(source: Path, targets: list[str]) -> list[str]:
    """Targets are pytest node ids relative to the project root, e.g. tests/test_a.py::test_b."""
    if not targets:
        raise TargetError("choose at least one failing test to reproduce the bug")
    if len(targets) > MAX_TARGETS:
        raise TargetError(f"at most {MAX_TARGETS} reproduction targets are allowed")
    root = source.resolve()
    clean: list[str] = []
    for raw in targets:
        target = raw.strip()
        if not target or target.startswith("-") or "\x00" in target or "\n" in target:
            raise TargetError(f"invalid reproduction target: {raw!r}")
        if len(target) > 300:
            raise TargetError("reproduction target is too long")
        file_part = target.split("::", 1)[0].replace("\\", "/")
        path = (root / file_part).resolve()
        if root not in path.parents or path.suffix != ".py" or not path.is_file():
            raise TargetError(f"test file not found in the project: {file_part}")
        clean.append(target.replace("\\", "/"))
    return clean


def _is_project_module(source: Path, name: str) -> bool:
    if any(True for _ in source.rglob(f"{name}.py")):
        return True
    return any(p.is_dir() for p in source.rglob(name))


def scan_project(sandbox: SandboxRunner, source: Path, timeout_seconds: int = 180) -> ScanResult:
    workspace = sandbox.prepare_workspace(source)
    try:
        junit = ".fixproof_junit_scan.xml"
        result = sandbox.run(
            workspace,
            [
                "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rfE",
                "--continue-on-collection-errors", f"--junitxml={junit}",
            ],
            timeout_seconds=timeout_seconds,
        )  # fmt: skip
        stats = _junit_summary(workspace / junit)
    finally:
        sandbox.destroy(workspace)

    combined = result.stdout + "\n" + result.stderr
    failing, collection = [], []
    for kind, node, message in _RESULT_LINE.findall(result.stdout):
        item = FailingTest(node_id=node.replace("\\", "/"), message=message[:300])
        # FAILED = a test ran and failed; ERROR = collection/import/fixture problem
        (failing if kind == "FAILED" else collection).append(item)
    wanted = sorted({m.split(".")[0] for m in _MISSING_MODULE.findall(combined)})
    local = [m for m in wanted if _is_project_module(source, m)]
    missing = [m for m in wanted if m not in local]
    scan = ScanResult(
        exit_code=result.exit_code, timed_out=result.timed_out,
        duration_seconds=round(result.duration_seconds, 2), tests=int(stats["tests"]),
        failed=int(stats["failures"]), errors=int(stats["errors"]), skipped=int(stats["skipped"]),
        failing_tests=failing, collection_errors=collection, missing_modules=missing,
        local_modules_unresolved=local,
        output_excerpt=combined.strip()[-3000:],
    )  # fmt: skip

    if result.timed_out:
        scan.hint = f"The test suite did not finish within {timeout_seconds}s inside the sandbox."
    elif result.exit_code in (125, 126, 127) and not scan.tests:
        first = next((ln for ln in result.stderr.splitlines() if ln.strip()), "no stderr")
        scan.hint = f"The sandbox could not start (exit {result.exit_code}): {first[:200]}"
    elif missing or local:
        parts = []
        if missing:
            parts.append(
                f"Tests import {', '.join(missing)}, which is not installed in the offline "
                "sandbox image. Add it to backend/sandbox-image/extra-requirements.txt and "
                "rebuild the image."
            )
        if local:
            parts.append(
                f"Some tests import project modules ({', '.join(local)}) that are not importable "
                "from the project root. They likely belong to a sub-project with its own root; "
                "pick a test that runs on its own, or use that sub-folder as the project."
            )
        scan.hint = " ".join(parts)
    elif result.exit_code == 5:
        scan.hint = "pytest collected no tests. FixProof needs a pytest test that fails."
    elif result.exit_code == 0:
        scan.hint = "All tests pass, so there is no failing test to reproduce."
    elif not failing and collection:
        scan.hint = "Tests could not be collected (import or syntax errors). See the output below."
    return scan
