import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.sandbox.base import CommandResult, SandboxRunner
from app.sandbox.local import LocalSandbox
from app.verification.scan import (
    TargetError,
    _is_project_module,
    _parse_collected_node_ids,
    _reconstruct_junit_node_id,
    _recover_from_junit,
    scan_project,
    validate_repro_targets,
)

try:
    import resource
except ImportError:
    resource = None

skip_if_no_local_sandbox = pytest.mark.skipif(
    resource is None, reason="LocalSandbox requires a Unix-like OS with resource module"
)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class MockSandbox(SandboxRunner):
    IGNORED_DIRS = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
    }

    def __init__(
        self, responses: list[CommandResult] | None = None, auto_collect: bool = True
    ) -> None:
        self.responses = list(responses or [])
        self.auto_collect = auto_collect
        self.commands_run: list[list[str]] = []
        self.timeouts_used: list[int] = []

    def prepare_workspace(self, source: Path) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="fixproof-test-ws-"))
        for item in source.rglob("*"):
            if item.is_file():
                rel = item.relative_to(source)
                if any(p in self.IGNORED_DIRS for p in rel.parts):
                    continue
                dest = tmp / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(item.read_bytes())
        return tmp

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        self.commands_run.append(command)
        self.timeouts_used.append(timeout_seconds)

        if self.auto_collect and "--collect-only" in command:
            target = next((c for c in command if c.endswith(".py") or ".py::" in c), None)
            if target and "::" in target:
                clean_target = target.replace("\\", "/")
                return CommandResult(
                    command=" ".join(command),
                    exit_code=0,
                    stdout=f"collected 1 item\n{clean_target}\n",
                    stderr="",
                    duration_seconds=0.05,
                )

        if self.responses:
            return self.responses.pop(0)

        return CommandResult(
            command=" ".join(command),
            exit_code=0,
            stdout="collected 1 item\ntests/test_a.py::test_ok\n",
            stderr="",
            duration_seconds=0.1,
        )

    def destroy(self, workspace: Path) -> None:
        shutil.rmtree(workspace, ignore_errors=True)

    def describe(self) -> dict[str, Any]:
        return {"kind": "mock", "isolation": "test", "network_blocked": True, "notes": []}


# -----------------------------------------------------------------------------
# Unit Tests for validate_repro_targets()
# -----------------------------------------------------------------------------


def test_validate_repro_targets_valid(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_x(): pass\n"})
    targets = ["tests/test_a.py::test_x"]
    clean = validate_repro_targets(tmp_path, targets)
    assert clean == ["tests/test_a.py::test_x"]


def test_validate_repro_targets_rejects_empty_and_too_many(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match="choose at least one"):
        validate_repro_targets(tmp_path, [])

    too_many = [f"test_{i}.py" for i in range(11)]
    with pytest.raises(TargetError, match="at most 10"):
        validate_repro_targets(tmp_path, too_many)


@pytest.mark.parametrize(
    "bad",
    [
        "../outside.py::test_a",
        "tests/../../outside.py",
        "tests/./test_a.py::test_x",
        "sub/../tests/test_a.py",
    ],
)
def test_validate_repro_targets_rejects_path_traversal(tmp_path: Path, bad: str) -> None:
    write(tmp_path, {"tests/test_a.py": "pass"})
    with pytest.raises(TargetError, match="path traversal"):
        validate_repro_targets(tmp_path, [bad])


@pytest.mark.parametrize(
    "abs_path", ["/etc/passwd", "C:/secret/test.py", "\\\\server\\share\\test.py"]
)
def test_validate_repro_targets_rejects_absolute_paths(tmp_path: Path, abs_path: str) -> None:
    with pytest.raises(TargetError, match="absolute paths are not allowed"):
        validate_repro_targets(tmp_path, [abs_path])


def test_validate_repro_targets_rejects_non_py_extension(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.txt": "hello"})
    with pytest.raises(TargetError, match="must be a Python file"):
        validate_repro_targets(tmp_path, ["tests/test_a.txt::test_foo"])


@pytest.mark.parametrize(
    "malformed", ["tests/test_a.py::", "tests/test_a.py::::test_x", "tests/test_a.py::  "]
)
def test_validate_repro_targets_rejects_malformed_node_ids(tmp_path: Path, malformed: str) -> None:
    write(tmp_path, {"tests/test_a.py": "pass"})
    with pytest.raises(TargetError, match="malformed test node ID"):
        validate_repro_targets(tmp_path, [malformed])


def test_validate_repro_targets_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match="test file not found"):
        validate_repro_targets(tmp_path, ["tests/nonexistent.py::test_x"])


def test_validate_repro_targets_with_sandbox_validation(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_ok(): pass\n"})
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=0,
                stdout="tests/test_a.py::test_ok\n",
                stderr="",
                duration_seconds=0.1,
            )
        ],
        auto_collect=False,
    )
    clean = validate_repro_targets(tmp_path, ["tests/test_a.py::test_ok"], sandbox=sandbox)
    assert clean == ["tests/test_a.py::test_ok"]


def test_validate_repro_targets_rejects_nonexistent_function_in_valid_file(
    tmp_path: Path,
) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_ok(): pass\n"})
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=5,
                stdout="",
                stderr="ERROR: not found",
                duration_seconds=0.1,
            )
        ],
        auto_collect=False,
    )
    with pytest.raises(TargetError, match="test not found in project"):
        validate_repro_targets(tmp_path, ["tests/test_a.py::test_nonexistent"], sandbox=sandbox)


# -----------------------------------------------------------------------------
# Unit Tests for JUnit and Node ID parsing & recovery
# -----------------------------------------------------------------------------


def test_parse_collected_node_ids() -> None:
    stdout = (
        "rootdir: /tmp\n"
        "collected 3 items\n"
        "<Package tests>\n"
        "tests/test_calc.py::TestCalc::test_add\n"
        "tests/test_calc.py::TestCalc::test_sub\n"
        "tests/test_calc.py::test_top_level\n"
    )
    parsed = _parse_collected_node_ids(stdout)
    assert parsed == {
        "tests/test_calc.py::TestCalc::test_add",
        "tests/test_calc.py::TestCalc::test_sub",
        "tests/test_calc.py::test_top_level",
    }


def test_reconstruct_junit_node_id() -> None:
    source = Path("/tmp")
    # Function in file
    id1 = _reconstruct_junit_node_id("tests/test_calc.py", "tests.test_calc", "test_add", source)
    assert id1 == "tests/test_calc.py::test_add"

    # Class in file
    id2 = _reconstruct_junit_node_id(
        "tests/test_calc.py", "tests.test_calc.TestCalc", "test_add", source
    )
    assert id2 == "tests/test_calc.py::TestCalc::test_add"

    # Nested class in file
    id3 = _reconstruct_junit_node_id(
        "tests/test_calc.py", "tests.test_calc.TestOuter.TestInner", "test_deep", source
    )
    assert id3 == "tests/test_calc.py::TestOuter::TestInner::test_deep"

    # Parameterized test
    id4 = _reconstruct_junit_node_id(
        "tests/test_calc.py", "tests.test_calc.TestCalc", "test_param[1-2]", source
    )
    assert id4 == "tests/test_calc.py::TestCalc::test_param[1-2]"


def test_recover_from_junit_preserves_classes_and_parameters(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_calc.py": "class TestCalc: pass"})
    junit_file = tmp_path / "junit.xml"
    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="pytest" tests="3" failures="3">\n'
        '  <testcase file="tests/test_calc.py" classname="tests.test_calc.TestCalc"'
        ' name="test_add">\n'
        '    <failure message="AssertionError: 1 != 2"/>\n'
        "  </testcase>\n"
        '  <testcase file="tests/test_calc.py" classname="tests.test_calc.TestOuter.TestInner"'
        ' name="test_deep">\n'
        '    <failure message="AssertionError: deep fail"/>\n'
        "  </testcase>\n"
        '  <testcase file="tests/test_calc.py" classname="tests.test_calc.TestCalc"'
        ' name="test_param[1-2]">\n'
        '    <failure message="AssertionError: param fail"/>\n'
        "  </testcase>\n"
        "</testsuite></testsuites>"
    )
    junit_file.write_text(xml_content, encoding="utf-8")

    collected_ids = {
        "tests/test_calc.py::TestCalc::test_add",
        "tests/test_calc.py::TestOuter::TestInner::test_deep",
        "tests/test_calc.py::TestCalc::test_param[1-2]",
    }

    failing, errors = _recover_from_junit(junit_file, tmp_path, collected_node_ids=collected_ids)
    assert len(failing) == 3
    node_ids = [f.node_id for f in failing]
    assert "tests/test_calc.py::TestCalc::test_add" in node_ids
    assert "tests/test_calc.py::TestOuter::TestInner::test_deep" in node_ids
    assert "tests/test_calc.py::TestCalc::test_param[1-2]" in node_ids


def test_recover_from_junit_rejects_unverified_reconstructed_ids(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_calc.py": "pass"})
    junit_file = tmp_path / "junit.xml"
    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites><testsuite name="pytest" tests="1" failures="1">\n'
        '  <testcase file="tests/test_calc.py" classname="tests.test_calc.BogusClass"'
        ' name="test_phantom">\n'
        '    <failure message="AssertionError"/>\n'
        "  </testcase>\n"
        "</testsuite></testsuites>"
    )
    junit_file.write_text(xml_content, encoding="utf-8")

    collected_ids = {"tests/test_calc.py::RealClass::test_real"}
    failing, errors = _recover_from_junit(junit_file, tmp_path, collected_node_ids=collected_ids)
    assert len(failing) == 0


def test_is_project_module_accurate_classification(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "my_module.py": "x = 1",
            "vendor/vendored_mod.py": "v = 1",
            "third_party/lib.py": "l = 1",
            "docs/conf.py": "c = 1",
        },
    )
    assert _is_project_module(tmp_path, "my_module") is True
    assert _is_project_module(tmp_path, "vendored_mod") is False
    assert _is_project_module(tmp_path, "lib") is False
    assert _is_project_module(tmp_path, "conf") is False
    assert _is_project_module(tmp_path, "sys") is False
    assert _is_project_module(tmp_path, "os") is False
    assert _is_project_module(tmp_path, "json") is False


# -----------------------------------------------------------------------------
# Targeted Scan Workflow Tests (Workflow A)
# -----------------------------------------------------------------------------


def test_targeted_scan_executes_exact_test(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "tests/test_orders.py": "def test_discount(): assert False\n",
            "tests/test_other.py": "def test_other(): pass\n",
        },
    )
    target = "tests/test_orders.py::test_discount"
    sandbox = MockSandbox(
        [
            # Execution response
            CommandResult(
                command="pytest",
                exit_code=1,
                stdout=f"FAILED {target} - AssertionError: assert False\n",
                stderr="",
                duration_seconds=0.2,
            )
        ]
    )

    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.target == target
    assert res.status == "completed"
    assert res.failed == 1
    assert res.failing_tests[0].node_id == target
    # Ensure command executed contained target directly
    exec_cmd = sandbox.commands_run[-1]
    assert target in exec_cmd


def test_targeted_scan_exit_code_0_passing(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_ok.py": "def test_ok(): pass\n"})
    target = "tests/test_ok.py::test_ok"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=0,
                stdout="PASSED tests/test_ok.py::test_ok\n",
                stderr="",
                duration_seconds=0.1,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "completed"
    assert res.failed == 0
    assert "passed (exit 0)" in res.hint


def test_targeted_scan_timeout_accounting(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_slow.py": "def test_slow(): pass\n"})
    target = "tests/test_slow.py::test_slow"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=10.0,
                timed_out=True,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, timeout_seconds=10, test_id=target)
    assert res.status == "timed_out"
    assert res.timed_out is True
    assert "TIMED OUT" in res.hint


def test_targeted_scan_exit_code_2_collection_error(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_syntax.py": "def test_syntax(): syntax error\n"})
    target = "tests/test_syntax.py::test_syntax"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=2,
                stdout="ERROR collecting tests/test_syntax.py\n",
                stderr="SyntaxError",
                duration_seconds=0.1,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "failed"
    assert "syntax or collection errors" in res.hint


def test_targeted_scan_exit_code_3_internal_error(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    target = "tests/test_a.py::test_a"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=3,
                stdout="",
                stderr="pytest internal error",
                duration_seconds=0.1,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "error"
    assert "internal error" in res.hint


def test_targeted_scan_exit_code_4_usage_error(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    target = "tests/test_a.py::test_a"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=4,
                stdout="",
                stderr="usage error",
                duration_seconds=0.1,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "error"
    assert "usage error" in res.hint


def test_targeted_scan_exit_code_5_no_tests(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    target = "tests/test_a.py::test_a"
    sandbox = MockSandbox(
        [
            # pre-validation succeeds
            CommandResult(
                command="pytest",
                exit_code=0,
                stdout=f"collected 1 item\n{target}\n",
                stderr="",
                duration_seconds=0.05,
            ),
            # execution exits 5
            CommandResult(
                command="pytest",
                exit_code=5,
                stdout="",
                stderr="no tests ran",
                duration_seconds=0.1,
            ),
        ],
        auto_collect=False,
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "inconclusive"
    assert "collected no tests" in res.hint


def test_targeted_scan_sandbox_failure_exit_codes(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    target = "tests/test_a.py::test_a"
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=127,
                stdout="",
                stderr="bwrap: command not found",
                duration_seconds=0.05,
            )
        ]
    )
    res = scan_project(sandbox, tmp_path, test_id=target)
    assert res.status == "error"
    assert "sandbox could not start" in res.hint


# -----------------------------------------------------------------------------
# Global Discovery Workflow Tests (Workflow B)
# -----------------------------------------------------------------------------


def test_discovery_scan_collection_timeout(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest --collect-only",
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=10.0,
                timed_out=True,
            )
        ],
        auto_collect=False,
    )
    res = scan_project(sandbox, tmp_path, timeout_seconds=10)
    assert res.status == "timed_out"
    assert res.timed_out is True
    assert "collection timed out" in res.hint
    # Verify Phase 2 execution was NOT launched
    assert len(sandbox.commands_run) == 1


def test_discovery_scan_fatal_collection_halts_phase_2(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_bad.py": "syntax error here\n"})
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest --collect-only",
                exit_code=2,
                stdout="ERROR collecting tests/test_bad.py - SyntaxError\n",
                stderr="",
                duration_seconds=0.2,
            )
        ],
        auto_collect=False,
    )
    res = scan_project(sandbox, tmp_path)
    assert res.status == "failed"
    assert len(res.collection_errors) == 1
    # Phase 2 pytest was NEVER launched
    assert len(sandbox.commands_run) == 1


def test_discovery_scan_empty_test_suite_inconclusive(tmp_path: Path) -> None:
    write(tmp_path, {"app.py": "x = 1\n"})
    sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest --collect-only",
                exit_code=5,
                stdout="collected 0 items\n",
                stderr="",
                duration_seconds=0.1,
            )
        ],
        auto_collect=False,
    )
    res = scan_project(sandbox, tmp_path)
    assert res.status == "inconclusive"
    assert "collected no tests" in res.hint
    assert len(sandbox.commands_run) == 1


def test_discovery_scan_timeout_preserves_partial_results(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): assert False\n"})
    sandbox = MockSandbox(
        [
            # Phase 1: collection succeeds
            CommandResult(
                command="pytest --collect-only",
                exit_code=0,
                stdout="collected 1 item\ntests/test_a.py::test_a\n",
                stderr="",
                duration_seconds=0.1,
            ),
            # Phase 2: times out but captured 1 failure before termination
            CommandResult(
                command="pytest",
                exit_code=-1,
                stdout="FAILED tests/test_a.py::test_a - AssertionError: fail\n",
                stderr="",
                duration_seconds=120.0,
                timed_out=True,
            ),
        ],
        auto_collect=False,
    )
    res = scan_project(sandbox, tmp_path)
    assert res.status == "partial"
    assert res.timed_out is True
    assert len(res.failing_tests) == 1
    assert res.failing_tests[0].node_id == "tests/test_a.py::test_a"
    assert "PARTIAL SCAN" in res.hint


def test_subsecond_remaining_budget_returns_timed_out(tmp_path: Path) -> None:
    write(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    sandbox = MockSandbox()

    # Generator to advance monotonic time past timeout
    def time_advancer():
        val = 100.0
        while True:
            yield val
            val += 20.0

    with patch("time.monotonic", side_effect=time_advancer()):
        res = scan_project(sandbox, tmp_path, timeout_seconds=10)
        assert res.status == "timed_out"
        assert res.timed_out is True


def test_scan_route_supports_targeted_scan_and_validation(tmp_path: Path, monkeypatch) -> None:
    from fastapi import HTTPException

    from app.api import routes
    from app.api.routes import ScanRequest
    from app.config import get_settings
    from app.projects import ProjectStore

    project_dir = tmp_path / "project"
    store_dir = tmp_path / "store"

    write(
        project_dir,
        {
            "tests/test_a.py": "def test_failing(): assert False\n",
            "tests/test_b.py": "def test_passing(): pass\n",
        },
    )
    monkeypatch.setattr(get_settings(), "local_path_roots", str(project_dir))
    store = ProjectStore(store_dir)
    info = store.create_from_local(str(project_dir))
    monkeypatch.setattr(routes, "_store", lambda: store)

    target = "tests/test_a.py::test_failing"
    mock_sandbox = MockSandbox(
        [
            CommandResult(
                command="pytest",
                exit_code=1,
                stdout=f"FAILED {target} - AssertionError\n",
                stderr="",
                duration_seconds=0.1,
            )
        ]
    )
    monkeypatch.setattr(routes, "get_sandbox", lambda: mock_sandbox)

    # 1. Successful targeted scan via route function
    result = routes.scan(info.id, ScanRequest(test_id=target))
    assert result.target == target
    assert result.status == "completed"
    assert len(result.failing_tests) == 1
    assert result.failing_tests[0].node_id == target

    # 2. Path traversal rejected with 422
    with pytest.raises(HTTPException) as exc_info:
        routes.scan(info.id, ScanRequest(test_id="../evil.py::test_x"))
    assert exc_info.value.status_code == 422

    # 3. Missing file rejected with 422
    with pytest.raises(HTTPException) as exc_info:
        routes.scan(info.id, ScanRequest(test_id="tests/nonexistent.py::test_x"))
    assert exc_info.value.status_code == 422


# -----------------------------------------------------------------------------
# Existing LocalSandbox tests (kept intact)
# -----------------------------------------------------------------------------


@skip_if_no_local_sandbox
def test_scan_lists_failing_tests_with_node_ids(paginate_src) -> None:
    scan = scan_project(LocalSandbox(), paginate_src)
    assert scan.tests == 2 and scan.failed == 1
    assert [t.node_id for t in scan.failing_tests] == [
        "test_paginate.py::test_second_page_returns_items_4_to_6"
    ]
    assert "assert" in scan.failing_tests[0].message.lower()


@skip_if_no_local_sandbox
def test_scan_reports_missing_dependency_with_actionable_hint(tmp_path) -> None:
    write(tmp_path, {"test_a.py": "import not_installed_pkg\n\ndef test_a():\n    pass\n"})
    scan = scan_project(LocalSandbox(), tmp_path)
    assert scan.missing_modules == ["not_installed_pkg"]
    assert "extra-requirements.txt" in scan.hint and scan.failing_tests == []
    assert scan.collection_errors


@skip_if_no_local_sandbox
def test_scan_all_passing_and_no_tests(tmp_path) -> None:
    passing = write(tmp_path / "p", {"test_a.py": "def test_a():\n    assert True\n"})
    assert "All tests pass" in scan_project(LocalSandbox(), passing).hint
    empty = write(tmp_path / "e", {"a.py": "x = 1\n"})
    assert "no tests" in scan_project(LocalSandbox(), empty).hint


@skip_if_no_local_sandbox
def test_scan_supports_src_layout(tmp_path) -> None:
    write(
        tmp_path,
        {
            "src/pkg/__init__.py": "",
            "src/pkg/mod.py": "def double(x):\n    return x + x + 1\n",
            "tests/test_mod.py": (
                "from pkg.mod import double\n\ndef test_double():\n    assert double(2) == 4\n"
            ),
        },
    )
    scan = scan_project(LocalSandbox(), tmp_path)
    assert scan.missing_modules == [] and scan.collection_errors == []
    assert [t.node_id for t in scan.failing_tests] == ["tests/test_mod.py::test_double"]


@skip_if_no_local_sandbox
def test_scan_separates_project_modules_from_missing_packages(tmp_path) -> None:
    write(
        tmp_path,
        {
            "sub/helpers.py": "def f():\n    return 1\n",
            "tests/test_x.py": "from helpers import f\n\ndef test_x():\n    assert f() == 1\n",
        },
    )
    scan = scan_project(LocalSandbox(), tmp_path)
    assert scan.missing_modules == []
    assert scan.local_modules_unresolved == ["helpers"]
    assert "sub-project" in scan.hint
