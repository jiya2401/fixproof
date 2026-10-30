"""Scan a user project for failing tests so the user can pick what to repair, and validate
user-supplied reproduction targets before they are passed to the language runner."""

import logging
import re
import time
from pathlib import Path

from pydantic import BaseModel, Field

from app.sandbox.base import SandboxRunner

logger = logging.getLogger("fixproof.scan")

_RESULT_LINE = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)
_MISSING_MODULE = re.compile(r"No module named '([\w.]+)'")
MAX_TARGETS = 10
_ALLOWED_TEST_SUFFIXES = {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


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
    """Targets are runner node ids relative to the project root.

    For Python: ``tests/test_a.py::test_b``
    For Go:     ``./pkg/...`` or a bare package path
    For JS/TS:  ``src/math.test.ts``

    The only hard constraints are: no shell-injection characters, reasonable
    length, and the file-part must exist inside the project root (when the
    target looks like a file path rather than a Go package pattern).
    """
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
        # Go package patterns (./..., ./pkg/...) are not file paths — skip existence check.
        is_go_pattern = file_part.startswith("./") or file_part == "..."
        if not is_go_pattern:
            path = (root / file_part).resolve()
            if (
                root not in path.parents
                or path.suffix not in _ALLOWED_TEST_SUFFIXES
                or not path.is_file()
            ):
                raise TargetError(f"test file not found in the project: {file_part}")
        clean.append(target.replace("\\", "/"))
    return clean


def _is_project_module(source: Path, name: str) -> bool:
    if any(True for _ in source.rglob(f"{name}.py")):
        return True
    return any(p.is_dir() for p in source.rglob(name))


def scan_project(sandbox: SandboxRunner, source: Path, timeout_seconds: int = 180) -> ScanResult:
    """Scan *source* for failing tests using the language-appropriate runner.

    Detects the project language via :func:`get_language_runner`, runs the
    full test suite, and returns a normalised :class:`ScanResult`.  A fast
    collection-only pre-pass is still performed for Python projects (where
    ``pytest --collect-only`` is cheap); for Go and JavaScript the single
    full run is sufficient.
    """
    from app.runners import get_language_runner  # local import avoids circular dep

    total_start = time.monotonic()
    logger.info("scan_project: starting scan for source=%s (timeout=%ds)", source, timeout_seconds)

    runner = get_language_runner(source)
    runner_name = runner.language.value.capitalize()
    is_python = runner.language.value == "python"
    logger.info("scan_project: detected language=%s", runner.language.value)

    prep_start = time.monotonic()
    workspace = sandbox.prepare_workspace(source)
    prep_duration = time.monotonic() - prep_start
    logger.info("scan_project: workspace prepared at %s (took %.2fs)", workspace, prep_duration)

    try:
        collect_missing: list[str] = []
        _all_collection_failures = False

        if is_python:
            # ── Phase 1: fast collection-only pre-pass (Python only, ≤30 s) ─────────────
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
            _has_collected = bool(re.search(r"\d+ test", collect_result.stdout))
            _all_collection_failures = (
                collect_result.exit_code == 2
                and not _has_collected
                and bool(collect_missing)
                and not collect_result.timed_out
            )

            if _all_collection_failures:
                logger.warning(
                    "scan_project: entire suite failed to collect (%d missing modules). "
                    "Skipping full test run.",
                    len(set(collect_missing)),
                )
                result = collect_result
                stats = {
                    "tests": 0, "failures": 0, "errors": len(set(collect_missing)), "skipped": 0,
                }
            else:
                elapsed_so_far = time.monotonic() - total_start
                remaining_budget = max(10, timeout_seconds - int(elapsed_so_far) - 5)
                junit = ".fixproof_junit_scan.xml"
                result = sandbox.run(
                    workspace,
                    [
                        "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short",
                        "-rfE", "--maxfail=10", "--continue-on-collection-errors",
                        f"--junitxml={junit}",
                    ],
                    timeout_seconds=remaining_budget,
                )
                from app.verification.pytest_runner import _junit_summary
                stats = _junit_summary(workspace / junit)

            combined = result.stdout + "\n" + result.stderr
            failing: list[FailingTest] = []
            collection: list[FailingTest] = []
            seen_failing: set[str] = set()
            seen_collection: set[str] = set()

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

            if not collect_missing:
                collect_missing = _MISSING_MODULE.findall(combined)

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
            effective_skipped = int(stats["skipped"])
            exit_code = result.exit_code
            duration = round(time.monotonic() - total_start, 2)
            raw_output = combined
            is_timed_out = result.timed_out
        else:
            elapsed_so_far = time.monotonic() - total_start
            remaining_budget = max(10, timeout_seconds - int(elapsed_so_far) - 5)
            trr = runner.run_tests(sandbox, workspace, timeout_seconds=remaining_budget)
            raw_output = trr.raw_output
            combined = raw_output
            collect_missing = []
            failing = [
                FailingTest(node_id=f.test_name, message=(f.message or "")[:300])
                for f in trr.failures
                if not f.test_name.startswith("(setup)")
            ]
            collection = [
                FailingTest(node_id=f.test_name, message=(f.message or "")[:300])
                for f in trr.failures
                if f.test_name.startswith("(setup)")
            ]
            if trr.timed_out:
                scan_status = "partial" if failing else "timed_out"
            elif trr.errors > 0 and trr.total_tests == 0:
                scan_status = "error"
            else:
                scan_status = "completed"
            effective_tests = trr.total_tests
            effective_failed = trr.failed
            effective_errors = trr.errors
            effective_skipped = max(0, trr.total_tests - trr.passed - trr.failed - trr.errors)
            exit_code = 0 if trr.ok else (1 if not trr.timed_out else -1)
            duration = round(time.monotonic() - total_start, 2)
            is_timed_out = trr.timed_out
    finally:
        cleanup_start = time.monotonic()
        sandbox.destroy(workspace)
        logger.info("scan_project: workspace destroyed in %.3fs", time.monotonic() - cleanup_start)

    wanted = sorted({m.split(".")[0] for m in collect_missing})
    local = [m for m in wanted if _is_project_module(source, m)]
    missing = [m for m in wanted if m not in local]

    scan = ScanResult(
        exit_code=exit_code,
        timed_out=is_timed_out,
        status=scan_status,
        duration_seconds=duration,
        tests=effective_tests,
        failed=effective_failed,
        errors=effective_errors,
        skipped=max(0, effective_skipped),
        failing_tests=failing,
        collection_errors=collection,
        missing_modules=missing,
        local_modules_unresolved=local,
        output_excerpt=(combined or raw_output).strip()[-3000:],
    )

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
            "Enter a specific test path below to run directly."
        )
    elif scan_status == "error":
        first = next(
            (ln for ln in (combined or raw_output).splitlines() if ln.strip()),
            "no output",
        )
        scan.hint = f"The sandbox could not start or encountered an error: {first[:200]}"
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
    elif (exit_code == 5 if exit_code is not None else False) or effective_tests == 0:
        scan.hint = f"{runner_name} collected no tests. FixProof needs a failing test suite."
    elif (not is_timed_out) and effective_failed == 0 and effective_errors == 0:
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
