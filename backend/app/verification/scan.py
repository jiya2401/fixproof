"""Scan a user project for failing tests so the user can pick what to repair, and validate
user-supplied reproduction targets before they are passed to pytest."""

import logging
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field

from app.sandbox.base import SandboxRunner
from app.verification.pytest_runner import _junit_summary

logger = logging.getLogger("fixproof.scan")

_RESULT_LINE = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)
_MISSING_MODULE = re.compile(r"No module named '([\w.]+)'")
MAX_TARGETS = 10


class FailingTest(BaseModel):
    node_id: str
    message: str = ""


class ScanResult(BaseModel):
    exit_code: int | None = None
    timed_out: bool = False
    status: str = "completed"  # "completed" | "timed_out" | "partial" | "error"
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
    total_start = time.monotonic()
    logger.info("scan_project: starting scan for source=%s (timeout=%ds)", source, timeout_seconds)

    prep_start = time.monotonic()
    workspace = sandbox.prepare_workspace(source)
    prep_duration = time.monotonic() - prep_start
    logger.info("scan_project: workspace prepared at %s (took %.2fs)", workspace, prep_duration)

    junit = ".fixproof_junit_scan.xml"
    try:
        # ── Phase 1: fast collection-only pre-pass (≤30 s) ─────────────────────
        # Detects missing-module / import errors in a few seconds without burning the
        # full timeout budget on a test run that cannot possibly succeed.
        collect_budget = min(30, max(10, timeout_seconds // 4))
        collect_start = time.monotonic()
        collect_result = sandbox.run(
            workspace,
            [
                "python", "-m", "pytest", "--collect-only", "-q",
                "-p", "no:cacheprovider", "--continue-on-collection-errors",
            ],
            timeout_seconds=collect_budget,
        )  # fmt: skip
        collect_duration = time.monotonic() - collect_start
        logger.info(
            "scan_project: collection pre-pass finished in %.2fs (exit_code=%s, timed_out=%s)",
            collect_duration,
            collect_result.exit_code,
            collect_result.timed_out,
        )

        collect_combined = collect_result.stdout + "\n" + collect_result.stderr
        collect_missing = _MISSING_MODULE.findall(collect_combined)
        # Did pytest collect at least one test item?
        _has_collected = bool(re.search(r"\d+ test", collect_result.stdout))
        # Whole-suite collection failure: exit 2, nothing collected, missing
        # modules known, no timeout.
        _all_collection_failures = (
            collect_result.exit_code == 2
            and not _has_collected
            and collect_missing
            and not collect_result.timed_out
        )

        stats: dict
        if _all_collection_failures:
            # Skip the full run — it would hit the same wall after burning 180 s.
            logger.warning(
                "scan_project: entire suite failed to collect (%d missing modules). "
                "Skipping full test run.",
                len(set(collect_missing)),
            )
            result = collect_result
            stats = {"tests": 0, "failures": 0, "errors": len(set(collect_missing)), "skipped": 0}
        else:
            # ── Phase 2: full test run with whatever budget remains ─────────────
            elapsed_so_far = time.monotonic() - total_start
            remaining_budget = max(10, timeout_seconds - int(elapsed_so_far) - 5)

            run_start = time.monotonic()
            # --maxfail=10 stops scanning after finding enough failing tests to repair,
            # avoiding running hundreds of additional passing tests in huge suites.
            result = sandbox.run(
                workspace,
                [
                    "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rfE",
                    "--maxfail=10", "--continue-on-collection-errors", f"--junitxml={junit}",
                ],
                timeout_seconds=remaining_budget,
            )  # fmt: skip
            run_duration = time.monotonic() - run_start
            logger.info(
                "scan_project: pytest execution finished in %.2fs (exit_code=%s, timed_out=%s)",
                run_duration,
                result.exit_code,
                result.timed_out,
            )

            parse_start = time.monotonic()
            stats = _junit_summary(workspace / junit)
            logger.info(
                "scan_project: parsed junit summary (tests=%s, failures=%s, errors=%s) in %.3fs",
                stats.get("tests", 0),
                stats.get("failures", 0),
                stats.get("errors", 0),
                time.monotonic() - parse_start,
            )
    finally:
        cleanup_start = time.monotonic()
        sandbox.destroy(workspace)
        logger.info("scan_project: workspace destroyed in %.3fs", time.monotonic() - cleanup_start)

    combined = result.stdout + "\n" + result.stderr
    failing: list[FailingTest] = []
    collection: list[FailingTest] = []
    seen_failing: set[str] = set()
    seen_collection: set[str] = set()

    # Parse canonical pytest node IDs (file paths) from stdout
    for kind, node, message in _RESULT_LINE.findall(result.stdout):
        clean_node = node.replace("\\", "/")
        item = FailingTest(node_id=clean_node, message=message[:300])
        if kind == "FAILED":
            if clean_node not in seen_failing:
                seen_failing.add(clean_node)
                failing.append(item)
        else:
            if clean_node not in seen_collection:
                seen_collection.add(clean_node)
                collection.append(item)

    wanted = sorted({m.split(".")[0] for m in _MISSING_MODULE.findall(combined)})
    local = [m for m in wanted if _is_project_module(source, m)]
    missing = [m for m in wanted if m not in local]

    # Explicit scan status: PARTIAL, TIMED_OUT, ERROR, or COMPLETED
    if result.timed_out:
        scan_status = "partial" if failing else "timed_out"
    elif result.exit_code in (125, 126, 127):
        scan_status = "error"
    else:
        scan_status = "completed"

    junit_tests = int(stats["tests"])
    effective_tests = junit_tests if junit_tests > 0 else (len(failing) + len(collection))
    effective_failed = int(stats["failures"]) if junit_tests > 0 else len(failing)
    effective_errors = int(stats["errors"]) if junit_tests > 0 else len(collection)

    scan = ScanResult(
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        status=scan_status,
        duration_seconds=round(time.monotonic() - total_start, 2),
        tests=effective_tests,
        failed=effective_failed,
        errors=effective_errors,
        skipped=int(stats["skipped"]),
        failing_tests=failing,
        collection_errors=collection,
        missing_modules=missing,
        local_modules_unresolved=local,
        output_excerpt=combined.strip()[-3000:],
    )  # fmt: skip

    if scan_status == "partial":
        scan.hint = (
            f"The test suite was interrupted after {timeout_seconds}s (PARTIAL SCAN). "
            f"{len(failing)} failing test(s) were recovered before timeout; "
            "select one below to repair."
        )
    elif scan_status == "timed_out":
        scan.hint = (
            f"The test suite did not finish within {timeout_seconds}s (TIMED OUT) and "
            "no failing tests could be determined before termination. "
            "Enter a specific test path below (e.g. tests/test_x.py::test_y) to run directly."
        )
    elif scan_status == "error":
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
    elif result.exit_code == 5 or effective_tests == 0:
        scan.hint = "pytest collected no tests. FixProof needs a pytest test that fails."
    elif result.exit_code == 0:
        scan.hint = "All tests pass, so there is no failing test to reproduce."
    elif not failing and collection:
        scan.hint = "Tests could not be collected (import or syntax errors). See the output below."

    logger.info(
        "scan_project: scan completed status=%s total_duration=%.2fs "
        "(tests=%d, failing=%d, collection=%d)",
        scan.status,
        scan.duration_seconds,
        scan.tests,
        len(scan.failing_tests),
        len(scan.collection_errors),
    )
    return scan
