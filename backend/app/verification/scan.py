"""Scan a user project for failing tests so the user can pick what to repair, and validate
user-supplied reproduction targets before they are passed to pytest.
"""

from __future__ import annotations

import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.sandbox.base import SandboxRunner
from app.verification.pytest_runner import _junit_summary

logger = logging.getLogger("fixproof.scan")

_RESULT_LINE = re.compile(
    r"^(FAILED|ERROR)\s+(?:collecting\s+)?(\S+)(?:\s+-\s+(.*))?$", re.MULTILINE
)
_MISSING_MODULE = re.compile(r"No module named '([\w.]+)'")
_STDLIB_MODULES = getattr(
    sys,
    "stdlib_module_names",
    frozenset(
        {
            "abc",
            "argparse",
            "ast",
            "asyncio",
            "base64",
            "collections",
            "contextlib",
            "copy",
            "csv",
            "datetime",
            "decimal",
            "difflib",
            "email",
            "enum",
            "errno",
            "functools",
            "gc",
            "hashlib",
            "http",
            "importlib",
            "inspect",
            "io",
            "itertools",
            "json",
            "logging",
            "math",
            "multiprocessing",
            "os",
            "pathlib",
            "pickle",
            "platform",
            "random",
            "re",
            "shutil",
            "signal",
            "socket",
            "sqlite3",
            "ssl",
            "stat",
            "string",
            "subprocess",
            "sys",
            "tempfile",
            "threading",
            "time",
            "typing",
            "unittest",
            "urllib",
            "uuid",
            "warnings",
            "weakref",
            "xml",
            "zipfile",
        }
    ),
)
_VENDOR_DIRS = frozenset(
    {"vendor", "third_party", "extern", "site-packages", "docs", "fixtures", "test_fixtures"}
)
MAX_TARGETS = 10

ScanStatus = Literal["completed", "timed_out", "partial", "failed", "inconclusive", "error"]


class FailingTest(BaseModel):
    node_id: str
    message: str = ""


class ScanResult(BaseModel):
    target: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    status: ScanStatus = "completed"
    duration_seconds: float = 0.0
    tests: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failing_tests: list[FailingTest] = Field(default_factory=list)
    collection_errors: list[FailingTest] = Field(default_factory=list)
    missing_modules: list[str] = Field(default_factory=list)
    local_modules_unresolved: list[str] = Field(default_factory=list)
    hint: str = ""
    output_excerpt: str = ""


class TargetError(ValueError):
    pass


def validate_repro_targets(
    source: Path,
    targets: list[str],
    sandbox: SandboxRunner | None = None,
    timeout_seconds: int = 30,
) -> list[str]:
    """Validate pytest node IDs relative to project root.

    Rejects path traversal, absolute paths, malformed targets, and unsupported files.
    Optionally pre-validates complete node IDs against pytest collection if a sandbox
    is provided.
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

        # Reject path traversal components in the raw target
        parts = target.replace("\\", "/").split("/")
        if any(p in ("..", ".") for p in parts):
            raise TargetError(f"path traversal or relative components not allowed: {raw!r}")

        file_part = target.split("::", 1)[0].replace("\\", "/")
        if file_part.startswith("/") or re.match(r"^[A-Za-z]:", file_part):
            raise TargetError(f"absolute paths are not allowed: {raw!r}")
        if not file_part.endswith(".py"):
            raise TargetError(f"test target must be a Python file (.py): {raw!r}")

        # Check for malformed node IDs (empty segment after ::)
        if "::" in target:
            segments = target.split("::")[1:]
            if any(not seg.strip() for seg in segments):
                raise TargetError(f"malformed test node ID: {raw!r}")

        path = (root / file_part).resolve()
        if root not in path.parents or not path.is_file():
            raise TargetError(f"test file not found in the project: {file_part}")

        clean.append(target.replace("\\", "/"))

    if sandbox is not None:
        workspace = sandbox.prepare_workspace(source)
        try:
            for target_id in clean:
                res = sandbox.run(
                    workspace,
                    [
                        "python",
                        "-m",
                        "pytest",
                        target_id,
                        "--collect-only",
                        "-q",
                        "-p",
                        "no:cacheprovider",
                    ],
                    timeout_seconds=min(timeout_seconds, 15),
                )
                if res.exit_code == 5:
                    raise TargetError(f"test not found in project: {target_id}")
                collected = _parse_collected_node_ids(res.stdout)
                if target_id not in collected and not any(
                    c.startswith(f"{target_id}::") for c in collected
                ):
                    raise TargetError(f"test not found in project: {target_id}")
        finally:
            sandbox.destroy(workspace)

    return clean


def _parse_collected_node_ids(stdout: str) -> set[str]:
    """Extract node IDs from pytest --collect-only -q output."""
    node_ids: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("<") or line.endswith(">"):
            continue
        if "::" in line and (line.endswith(".py") or ".py::" in line):
            node_ids.add(line.replace("\\", "/"))
        elif line.endswith(".py") and not line.startswith("rootdir:"):
            node_ids.add(line.replace("\\", "/"))
    return node_ids


def _reconstruct_junit_node_id(file_attr: str, classname: str, name: str, source: Path) -> str:
    """Reconstruct exact pytest node ID from JUnit XML attributes."""
    file_norm = file_attr.replace("\\", "/")
    if file_norm.startswith("./"):
        file_norm = file_norm[2:]

    module_dot = file_norm.removesuffix(".py").replace("/", ".")
    class_part = ""
    if classname:
        if classname.startswith(module_dot + "."):
            class_part = classname[len(module_dot) + 1 :]
        elif classname == module_dot:
            class_part = ""
        else:
            class_part = classname

    if class_part:
        class_hierarchy = class_part.replace(".", "::")
        return f"{file_norm}::{class_hierarchy}::{name}"
    return f"{file_norm}::{name}"


def _recover_from_junit(
    junit_path: Path,
    source: Path,
    collected_node_ids: set[str] | None = None,
) -> tuple[list[FailingTest], list[FailingTest]]:
    """Parse JUnit XML and recover failing and errored tests.

    If collected_node_ids is provided, reconstructed IDs are validated against
    actual collected IDs. Unverified IDs are dropped so they are never presented
    as exact reproducible targets.
    """
    if not junit_path.exists():
        return [], []

    failing: list[FailingTest] = []
    errors: list[FailingTest] = []

    try:
        tree = ET.parse(junit_path)
        root = tree.getroot()
    except Exception as exc:
        logger.warning("_recover_from_junit: failed to parse %s: %s", junit_path, exc)
        return [], []

    for tc in root.iter("testcase"):
        file_attr = tc.get("file") or ""
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""

        if not file_attr:
            module_parts = classname.split(".")
            candidate_file = "/".join(module_parts) + ".py"
            if (source / candidate_file).is_file():
                file_attr = candidate_file
            elif len(module_parts) > 1:
                candidate_file2 = "/".join(module_parts[:-1]) + ".py"
                if (source / candidate_file2).is_file():
                    file_attr = candidate_file2

        reconstructed_id = _reconstruct_junit_node_id(file_attr, classname, name, source)
        if collected_node_ids is not None and reconstructed_id not in collected_node_ids:
            # Drop unverified reconstructed candidate ID
            continue

        fail_elem = tc.find("failure")
        err_elem = tc.find("error")

        if fail_elem is not None:
            msg = fail_elem.get("message") or fail_elem.text or ""
            failing.append(FailingTest(node_id=reconstructed_id, message=msg[:300]))
        elif err_elem is not None:
            msg = err_elem.get("message") or err_elem.text or ""
            errors.append(FailingTest(node_id=reconstructed_id, message=msg[:300]))

    return failing, errors


def _is_project_module(source: Path, name: str) -> bool:
    """Check if a module name is a local project module (not stdlib or vendored)."""
    if name in _STDLIB_MODULES:
        return False

    for match in source.rglob(f"{name}.py"):
        rel_parts = match.relative_to(source).parts
        if not any(v in rel_parts for v in _VENDOR_DIRS):
            return True

    for match in source.rglob(name):
        if match.is_dir() and (match / "__init__.py").exists():
            rel_parts = match.relative_to(source).parts
            if not any(v in rel_parts for v in _VENDOR_DIRS):
                return True

    return False


def scan_project(
    sandbox: SandboxRunner,
    source: Path,
    timeout_seconds: int = 180,
    test_id: str | None = None,
) -> ScanResult:
    """Scan a project for failing tests.

    Workflow A (Fast Path): If test_id is supplied, validates and executes that
    specific test directly.
    Workflow B (Default Path): If test_id is None, discovers tests across the
    repository using collection pre-pass and full execution.
    """
    clean_target: str | None = None
    if test_id and test_id.strip():
        validated = validate_repro_targets(source, [test_id.strip()])
        clean_target = validated[0]
        return _run_targeted_scan(sandbox, source, clean_target, timeout_seconds)

    return _run_discovery_scan(sandbox, source, timeout_seconds)


def _run_targeted_scan(
    sandbox: SandboxRunner,
    source: Path,
    clean_target: str,
    timeout_seconds: int,
) -> ScanResult:
    """Execute targeted test fast path."""
    total_start = time.monotonic()
    logger.info(
        "scan_project: targeted scan for target=%s (timeout=%ds)", clean_target, timeout_seconds
    )

    prep_start = time.monotonic()
    workspace = sandbox.prepare_workspace(source)
    prep_duration = time.monotonic() - prep_start
    logger.info("scan_project: workspace prepared at %s (took %.2fs)", workspace, prep_duration)

    elapsed_so_far = time.monotonic() - total_start
    remaining_budget = timeout_seconds - elapsed_so_far
    if remaining_budget < 1.0:
        sandbox.destroy(workspace)
        return ScanResult(
            target=clean_target,
            timed_out=True,
            status="timed_out",
            duration_seconds=round(time.monotonic() - total_start, 2),
            hint=f"Workspace preparation consumed the {timeout_seconds}s timeout budget.",
        )

    junit = ".fixproof_junit_scan.xml"
    junit_path = workspace / junit

    try:
        # Pre-validate that the complete node ID exists
        collect_res = sandbox.run(
            workspace,
            [
                "python",
                "-m",
                "pytest",
                clean_target,
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            timeout_seconds=min(int(remaining_budget), 15),
        )
        if collect_res.exit_code == 5:
            raise TargetError(f"test not found in project: {clean_target}")

        collected_node_ids = _parse_collected_node_ids(collect_res.stdout)
        if collected_node_ids and clean_target not in collected_node_ids:
            if not any(c.startswith(f"{clean_target}::") for c in collected_node_ids):
                raise TargetError(f"test not found in project: {clean_target}")

        elapsed_so_far = time.monotonic() - total_start
        remaining_budget = timeout_seconds - elapsed_so_far
        if remaining_budget < 1.0:
            return ScanResult(
                target=clean_target,
                timed_out=True,
                status="timed_out",
                duration_seconds=round(time.monotonic() - total_start, 2),
                hint=f"Target validation consumed the {timeout_seconds}s timeout budget.",
            )

        exec_timeout = int(remaining_budget)
        result = sandbox.run(
            workspace,
            [
                "python",
                "-m",
                "pytest",
                clean_target,
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "-rfE",
                "-o",
                "junit_family=xunit1",
                f"--junitxml={junit}",
            ],
            timeout_seconds=exec_timeout,
        )

        has_junit = junit_path.exists()
        stats = (
            _junit_summary(junit_path)
            if has_junit
            else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        )
        junit_failing, junit_errors = _recover_from_junit(
            junit_path, source, collected_node_ids=collected_node_ids or None
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

    for jf in junit_failing:
        if jf.node_id not in seen_failing:
            seen_failing.add(jf.node_id)
            failing.append(jf)

    for je in junit_errors:
        if je.node_id not in seen_collection and je.node_id not in seen_failing:
            seen_collection.add(je.node_id)
            collection.append(je)

    wanted = sorted({m.split(".")[0] for m in _MISSING_MODULE.findall(combined)})
    local = [m for m in wanted if _is_project_module(source, m)]
    missing = [m for m in wanted if m not in local]

    effective_tests = int(stats["tests"]) if has_junit else 0
    junit_skipped = int(stats["skipped"]) if has_junit else 0

    scan_status: ScanStatus = "completed"
    hint = ""

    if result.timed_out:
        scan_status = "timed_out"
        hint = (
            f"The targeted test {clean_target} did not finish within {timeout_seconds}s "
            "(TIMED OUT)."
        )
    elif result.exit_code in (125, 126, 127):
        scan_status = "error"
        effective_tests = 0
        first = next((ln for ln in result.stderr.splitlines() if ln.strip()), "no stderr")
        hint = f"The sandbox could not start (exit {result.exit_code}): {first[:200]}"
    elif result.exit_code == 0:
        scan_status = "completed"
        failing = []
        hint = (
            f"Targeted test {clean_target} passed (exit 0). "
            "FixProof needs a failing test to reproduce the bug."
        )
    elif result.exit_code == 1:
        if failing:
            scan_status = "completed"
        elif collection:
            scan_status = "failed"
            hint = (
                f"Targeted test {clean_target} encountered setup/fixture errors (exit 1). "
                "See output below."
            )
        else:
            scan_status = "failed"
            hint = (
                f"pytest exited with code 1 for {clean_target}, "
                "but no failing tests were identified."
            )
    elif result.exit_code == 2:
        scan_status = "failed"
        hint = (
            f"Targeted test {clean_target} could not be executed due to syntax or "
            "collection errors (exit 2)."
        )
    elif result.exit_code == 3:
        scan_status = "error"
        effective_tests = 0
        hint = f"pytest encountered an internal error while executing {clean_target} (exit 3)."
    elif result.exit_code == 4:
        scan_status = "error"
        effective_tests = 0
        hint = (
            f"pytest command-line usage error for {clean_target} (exit 4). "
            "Check test target and arguments."
        )
    elif result.exit_code == 5:
        scan_status = "inconclusive"
        effective_tests = 0
        hint = f"pytest collected no tests matching {clean_target} (exit 5)."
    else:
        scan_status = "failed"
        hint = f"pytest exited unexpectedly with code {result.exit_code} for {clean_target}."

    effective_failed = len(failing)
    effective_errors = int(stats["errors"]) if has_junit else len(collection)

    if scan_status not in ("timed_out", "error") and (missing or local):
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
        hint = " ".join(parts)

    return ScanResult(
        target=clean_target,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        status=scan_status,
        duration_seconds=round(time.monotonic() - total_start, 2),
        tests=effective_tests,
        failed=effective_failed,
        errors=effective_errors,
        skipped=junit_skipped,
        failing_tests=failing,
        collection_errors=collection,
        missing_modules=missing,
        local_modules_unresolved=local,
        hint=hint,
        output_excerpt=combined.strip()[-3000:],
    )


def _run_discovery_scan(
    sandbox: SandboxRunner,
    source: Path,
    timeout_seconds: int,
) -> ScanResult:
    """Execute automatic global discovery workflow."""
    total_start = time.monotonic()
    logger.info(
        "scan_project: starting discovery scan for source=%s (timeout=%ds)", source, timeout_seconds
    )

    prep_start = time.monotonic()
    workspace = sandbox.prepare_workspace(source)
    prep_duration = time.monotonic() - prep_start
    logger.info("scan_project: workspace prepared at %s (took %.2fs)", workspace, prep_duration)

    elapsed_so_far = time.monotonic() - total_start
    remaining_total = timeout_seconds - elapsed_so_far
    if remaining_total < 1.0:
        sandbox.destroy(workspace)
        return ScanResult(
            target=None,
            timed_out=True,
            status="timed_out",
            duration_seconds=round(time.monotonic() - total_start, 2),
            hint=f"Workspace preparation consumed the entire {timeout_seconds}s timeout budget.",
        )

    junit = ".fixproof_junit_scan.xml"
    junit_path = workspace / junit

    try:
        # Phase 1: fast collection pre-pass
        max_collect = min(timeout_seconds, min(30, max(1, timeout_seconds // 4)))
        collect_budget = min(int(remaining_total), max_collect)
        collect_start = time.monotonic()
        collect_result = sandbox.run(
            workspace,
            [
                "python",
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "--continue-on-collection-errors",
            ],
            timeout_seconds=collect_budget,
        )
        collect_duration = time.monotonic() - collect_start
        logger.info(
            "scan_project: collection pre-pass finished in %.2fs (exit_code=%s, timed_out=%s)",
            collect_duration,
            collect_result.exit_code,
            collect_result.timed_out,
        )

        collect_combined = collect_result.stdout + "\n" + collect_result.stderr
        wanted_collect = sorted(
            {m.split(".")[0] for m in _MISSING_MODULE.findall(collect_combined)}
        )
        missing_collect = [m for m in wanted_collect if not _is_project_module(source, m)]
        local_collect = [m for m in wanted_collect if _is_project_module(source, m)]
        collected_node_ids = _parse_collected_node_ids(collect_result.stdout)
        num_collected = len(collected_node_ids)

        if collect_result.timed_out:
            logger.warning("scan_project: collection timed out after %ds", collect_budget)
            return ScanResult(
                target=None,
                exit_code=collect_result.exit_code,
                timed_out=True,
                status="timed_out",
                duration_seconds=round(time.monotonic() - total_start, 2),
                missing_modules=missing_collect,
                local_modules_unresolved=local_collect,
                hint=(
                    f"Test collection timed out after {collect_budget}s. "
                    "Enter a specific test path to run directly."
                ),
                output_excerpt=collect_combined.strip()[-3000:],
            )

        if collect_result.exit_code == 3:
            return ScanResult(
                target=None,
                exit_code=3,
                timed_out=False,
                status="error",
                duration_seconds=round(time.monotonic() - total_start, 2),
                hint="pytest encountered an internal error during test collection (exit 3).",
                output_excerpt=collect_combined.strip()[-3000:],
            )

        if collect_result.exit_code == 4:
            return ScanResult(
                target=None,
                exit_code=4,
                timed_out=False,
                status="error",
                duration_seconds=round(time.monotonic() - total_start, 2),
                hint="pytest command-line usage error during test collection (exit 4).",
                output_excerpt=collect_combined.strip()[-3000:],
            )

        if collect_result.exit_code == 5 or (collect_result.exit_code == 0 and num_collected == 0):
            return ScanResult(
                target=None,
                exit_code=5,
                timed_out=False,
                status="inconclusive",
                duration_seconds=round(time.monotonic() - total_start, 2),
                hint=(
                    "pytest collected no tests in the project (exit 5). "
                    "FixProof needs a test suite to scan."
                ),
                output_excerpt=collect_combined.strip()[-3000:],
            )

        if collect_result.exit_code == 2 and num_collected == 0:
            logger.warning("scan_project: collection conclusively failed with 0 items collected")
            collection_errors: list[FailingTest] = []
            for kind, node, message in _RESULT_LINE.findall(collect_result.stdout):
                if kind != "FAILED":
                    collection_errors.append(
                        FailingTest(node_id=node.replace("\\", "/"), message=message[:300])
                    )
            hint_msg = (
                "Test collection failed due to syntax, import, or configuration errors. "
                "See output below."
            )
            if missing_collect:
                hint_msg = (
                    f"Tests import {', '.join(missing_collect)}, which is not installed in the "
                    "offline sandbox image. Add it to backend/sandbox-image/extra-requirements.txt "
                    "and rebuild the image."
                )
            elif local_collect:
                hint_msg = (
                    f"Some tests import project modules ({', '.join(local_collect)}) "
                    "that are not importable from the project root. "
                    "They likely belong to a sub-project with its own root; "
                    "pick a test that runs on its own, or use that sub-folder as the project."
                )
            return ScanResult(
                target=None,
                exit_code=2,
                timed_out=False,
                status="failed",
                duration_seconds=round(time.monotonic() - total_start, 2),
                errors=len(collection_errors) or 1,
                collection_errors=collection_errors,
                missing_modules=missing_collect,
                local_modules_unresolved=local_collect,
                hint=hint_msg,
                output_excerpt=collect_combined.strip()[-3000:],
            )

        elapsed_so_far = time.monotonic() - total_start
        remaining_budget = timeout_seconds - elapsed_so_far
        if remaining_budget < 1.0:
            logger.warning(
                "scan_project: collection consumed timeout budget (%.2fs remaining)",
                remaining_budget,
            )
            return ScanResult(
                target=None,
                exit_code=collect_result.exit_code,
                timed_out=True,
                status="timed_out",
                duration_seconds=round(time.monotonic() - total_start, 2),
                missing_modules=missing_collect,
                local_modules_unresolved=local_collect,
                hint=f"Test collection consumed the entire {timeout_seconds}s timeout budget.",
                output_excerpt=collect_combined.strip()[-3000:],
            )

        # Phase 2: full test execution
        run_start = time.monotonic()
        exec_timeout = int(remaining_budget)
        result = sandbox.run(
            workspace,
            [
                "python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "-rfE",
                "--maxfail=10",
                "--continue-on-collection-errors",
                "-o",
                "junit_family=xunit1",
                f"--junitxml={junit}",
            ],
            timeout_seconds=exec_timeout,
        )
        run_duration = time.monotonic() - run_start
        logger.info(
            "scan_project: pytest execution finished in %.2fs (exit_code=%s, timed_out=%s)",
            run_duration,
            result.exit_code,
            result.timed_out,
        )

        has_junit = junit_path.exists()
        stats = (
            _junit_summary(junit_path)
            if has_junit
            else {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        )
        junit_failing, junit_errors = _recover_from_junit(
            junit_path, source, collected_node_ids=collected_node_ids
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

    for jf in junit_failing:
        if jf.node_id not in seen_failing:
            seen_failing.add(jf.node_id)
            failing.append(jf)

    for je in junit_errors:
        if je.node_id not in seen_collection and je.node_id not in seen_failing:
            seen_collection.add(je.node_id)
            collection.append(je)

    wanted = sorted({m.split(".")[0] for m in _MISSING_MODULE.findall(combined)})
    local = [m for m in wanted if _is_project_module(source, m)]
    missing = [m for m in wanted if m not in local]

    effective_tests = int(stats["tests"]) if has_junit else 0
    junit_skipped = int(stats["skipped"]) if has_junit else 0

    scan_status: ScanStatus = "completed"
    hint = ""

    if result.timed_out:
        scan_status = "partial" if failing else "timed_out"
        if scan_status == "partial":
            hint = (
                f"The test suite was interrupted after {timeout_seconds}s (PARTIAL SCAN). "
                f"{len(failing)} failing test(s) were recovered before timeout; "
                "select one below to repair."
            )
        else:
            hint = (
                f"The test suite did not finish within {timeout_seconds}s (TIMED OUT) and "
                "no failing tests could be determined before termination. "
                "Enter a specific test path below (e.g. tests/test_x.py::test_y) to run directly."
            )
    elif result.exit_code in (125, 126, 127):
        scan_status = "error"
        effective_tests = 0
        first = next((ln for ln in result.stderr.splitlines() if ln.strip()), "no stderr")
        hint = f"The sandbox could not start (exit {result.exit_code}): {first[:200]}"
    elif result.exit_code == 0:
        scan_status = "completed"
        failing = []
        hint = "All tests pass, so there is no failing test to reproduce."
    elif result.exit_code == 1:
        if failing:
            scan_status = "completed"
        elif collection:
            scan_status = "failed"
            hint = (
                "Tests could not be executed due to collection or setup errors. See output below."
            )
        else:
            scan_status = "failed"
            hint = (
                "pytest exited with code 1, but no failing tests were identified. See output below."
            )
    elif result.exit_code == 2:
        scan_status = "failed"
        hint = "Tests could not be collected (import or syntax errors). See output below."
    elif result.exit_code == 3:
        scan_status = "error"
        effective_tests = 0
        hint = "pytest encountered an internal error during test execution (exit 3)."
    elif result.exit_code == 4:
        scan_status = "error"
        effective_tests = 0
        hint = "pytest command-line usage error (exit 4). Check pytest configuration and arguments."
    elif result.exit_code == 5:
        scan_status = "inconclusive"
        effective_tests = 0
        hint = "pytest collected no tests matching selection (exit 5)."
    else:
        scan_status = "failed"
        hint = f"pytest exited unexpectedly with code {result.exit_code}."

    effective_failed = len(failing)
    effective_errors = int(stats["errors"]) if has_junit else len(collection)

    if scan_status not in ("timed_out", "partial", "error") and (missing or local):
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
        hint = " ".join(parts)

    return ScanResult(
        target=None,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        status=scan_status,
        duration_seconds=round(time.monotonic() - total_start, 2),
        tests=effective_tests,
        failed=effective_failed,
        errors=effective_errors,
        skipped=junit_skipped,
        failing_tests=failing,
        collection_errors=collection,
        missing_modules=missing,
        local_modules_unresolved=local,
        hint=hint,
        output_excerpt=combined.strip()[-3000:],
    )
