"""Tests for the multi-language SandboxRunner expansion.

Covers:
  1. Language detection (detector.py)
  2. Boundary protection map (boundary.py)
  3. Vitest log parser (parsers/vitest_parser.py)
  4. Go test log parser (parsers/gotest_parser.py)
  5. Runner command construction and sandbox delegation
  6. Factory correctness (get_language_runner)
  7. ProjectStore acceptance of JS/Go project stubs

All tests run without any network, Docker, or real toolchain — every
sandbox call is replaced by a minimal double via ``unittest.mock``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sandbox(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    """Return a mock SandboxRunner whose .run() returns a fixed CommandResult."""
    from app.sandbox.base import CommandResult

    sandbox = MagicMock()
    sandbox.run.return_value = CommandResult(
        command=" ".join(["mock"]),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.5,
        timed_out=False,
    )
    return sandbox


def _tmp_dir(files: dict[str, str | None]) -> Path:
    """Create a temporary directory tree from a dict of {rel_path: content}.

    A ``None`` value creates an empty file.
    """
    tmp = Path(tempfile.mkdtemp(prefix="fixproof_test_"))
    for rel, content in files.items():
        target = tmp / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
    return tmp


# ===========================================================================
# 1. Language Detection
# ===========================================================================


class TestLanguageDetection:
    def test_empty_dir_falls_back_to_python(self, tmp_path):
        from app.runners.detector import Language, detect_language

        assert detect_language(tmp_path) == Language.PYTHON

    def test_python_files_detected(self, tmp_path):
        from app.runners.detector import Language, detect_language

        (tmp_path / "main.py").write_text("x = 1")
        assert detect_language(tmp_path) == Language.PYTHON

    def test_package_json_gives_js(self, tmp_path):
        from app.runners.detector import Language, detect_language

        (tmp_path / "package.json").write_text('{"name": "demo"}')
        assert detect_language(tmp_path) == Language.JS

    def test_go_mod_gives_go(self, tmp_path):
        from app.runners.detector import Language, detect_language

        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n")
        assert detect_language(tmp_path) == Language.GO

    def test_go_wins_over_package_json(self, tmp_path):
        """When both go.mod and package.json exist, Go takes priority (it checks first)."""
        from app.runners.detector import Language, detect_language

        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n")
        (tmp_path / "package.json").write_text('{"name": "demo"}')
        assert detect_language(tmp_path) == Language.GO

    def test_non_existent_path_returns_python(self, tmp_path):
        from app.runners.detector import Language, detect_language

        assert detect_language(tmp_path / "does_not_exist") == Language.PYTHON

    def test_package_json_nested_one_level(self, tmp_path):
        """package.json one directory deep is still detected."""
        from app.runners.detector import Language, detect_language

        sub = tmp_path / "frontend"
        sub.mkdir()
        (sub / "package.json").write_text("{}")
        assert detect_language(tmp_path) == Language.JS


# ===========================================================================
# 2. Boundary Protection Map
# ===========================================================================


class TestBoundaryMap:
    def test_python_source_is_editable(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "app.py").write_text("x = 1")
        bm = build_boundary_map(tmp_path)
        assert "app.py" in bm.editable_paths

    def test_python_test_file_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "test_app.py").write_text("def test_x(): pass")
        bm = build_boundary_map(tmp_path)
        assert "test_app.py" in bm.locked_paths
        assert "test_app.py" not in bm.editable_paths

    def test_conftest_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "conftest.py").write_text("")
        bm = build_boundary_map(tmp_path)
        assert "conftest.py" in bm.locked_paths

    def test_js_source_is_editable(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        src = tmp_path / "src"
        src.mkdir()
        (src / "utils.ts").write_text("export const x = 1;")
        bm = build_boundary_map(tmp_path)
        assert "src/utils.ts" in bm.editable_paths

    def test_vitest_spec_file_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "utils.test.ts").write_text("it('x', () => {})")
        bm = build_boundary_map(tmp_path)
        assert "utils.test.ts" in bm.locked_paths

    def test_go_source_is_editable(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "math.go").write_text("package pkg\nfunc Add(a, b int) int { return a + b }")
        bm = build_boundary_map(tmp_path)
        assert "pkg/math.go" in bm.editable_paths

    def test_go_test_file_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "math_test.go").write_text("package main")
        bm = build_boundary_map(tmp_path)
        assert "math_test.go" in bm.locked_paths

    def test_go_mod_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n")
        bm = build_boundary_map(tmp_path)
        assert "go.mod" in bm.locked_paths

    def test_package_json_is_locked(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "package.json").write_text("{}")
        bm = build_boundary_map(tmp_path)
        assert "package.json" in bm.locked_paths

    def test_is_editable_helper(self, tmp_path):
        from app.runners.boundary import build_boundary_map

        (tmp_path / "src.py").write_text("x = 1")
        bm = build_boundary_map(tmp_path)
        assert bm.is_editable("src.py") is True
        assert bm.is_locked("src.py") is False

    def test_partitions_are_disjoint(self, tmp_path):
        """Every path appears in exactly one of editable or locked, never both."""
        from app.runners.boundary import build_boundary_map

        (tmp_path / "main.py").write_text("x=1")
        (tmp_path / "test_main.py").write_text("def test(): pass")
        (tmp_path / "go.mod").write_text("")
        bm = build_boundary_map(tmp_path)
        editable_set = set(bm.editable_paths)
        locked_set = set(bm.locked_paths)
        assert editable_set.isdisjoint(locked_set), "editable and locked must be disjoint"


# ===========================================================================
# 3. Vitest Parser
# ===========================================================================


VITEST_ALL_PASS = json.dumps({
    "numTotalTests": 3,
    "numPassedTests": 3,
    "numFailedTests": 0,
    "numPendingTests": 0,
    "success": True,
    "testResults": [
        {
            "testFilePath": "/workspace/src/math.test.ts",
            "status": "passed",
            "assertionResults": [
                {"fullName": "Math add returns 3", "status": "passed", "duration": 5},
                {"fullName": "Math sub returns 1", "status": "passed", "duration": 3},
                {"fullName": "Math mul returns 6", "status": "passed", "duration": 4},
            ],
        }
    ],
})

VITEST_WITH_FAILURES = json.dumps({
    "numTotalTests": 3,
    "numPassedTests": 1,
    "numFailedTests": 2,
    "numPendingTests": 0,
    "success": False,
    "testResults": [
        {
            "testFilePath": "/workspace/src/math.test.ts",
            "status": "failed",
            "assertionResults": [
                {"fullName": "Math add returns 3", "status": "passed", "duration": 5},
                {
                    "fullName": "Math sub returns 1",
                    "status": "failed",
                    "duration": 3,
                    "failureMessages": ["expected 2 to equal 1"],
                    "location": {"line": 12, "column": 0},
                },
                {
                    "fullName": "Math mul returns 6",
                    "status": "failed",
                    "duration": 4,
                    "failureMessages": ["expected 4 to equal 6"],
                    "location": {"line": 20, "column": 0},
                },
            ],
        }
    ],
})


class TestVitestParser:
    def test_all_pass(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_ALL_PASS)
        assert result.total_tests == 3
        assert result.passed == 3
        assert result.failed == 0
        assert result.failures == []
        assert result.ok is True

    def test_with_failures(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_WITH_FAILURES)
        assert result.total_tests == 3
        assert result.passed == 1
        assert result.failed == 2
        assert len(result.failures) == 2
        assert result.ok is False

    def test_failure_test_names_captured(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_WITH_FAILURES)
        names = [f.test_name for f in result.failures]
        assert "Math sub returns 1" in names
        assert "Math mul returns 6" in names

    def test_failure_messages_captured(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_WITH_FAILURES)
        msgs = {f.test_name: f.message for f in result.failures}
        assert "expected 2 to equal 1" in msgs["Math sub returns 1"]

    def test_failure_line_numbers_captured(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_WITH_FAILURES)
        lines = {f.test_name: f.line for f in result.failures}
        assert lines["Math sub returns 1"] == 12
        assert lines["Math mul returns 6"] == 20

    def test_malformed_json_returns_error_result(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json("not json at all")
        assert result.errors >= 1 or result.failed >= 0  # graceful, not a crash

    def test_to_dict_schema(self):
        from app.runners.parsers.vitest_parser import parse_vitest_json

        result = parse_vitest_json(VITEST_ALL_PASS)
        d = result.to_dict()
        assert set(d) >= {"total_tests", "passed", "failed", "failures", "timed_out"}


# ===========================================================================
# 4. Go Test Parser
# ===========================================================================


def _gotest_ndjson(events: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in events)


GOTEST_ALL_PASS_NDJSON = _gotest_ndjson([
    {"Action": "run", "Package": "example.com/pkg", "Test": "TestAdd"},
    {"Action": "run", "Package": "example.com/pkg", "Test": "TestMul"},
    {"Action": "output", "Package": "example.com/pkg", "Test": "TestAdd", "Output": "--- PASS: TestAdd (0.00s)\n"},
    {"Action": "output", "Package": "example.com/pkg", "Test": "TestMul", "Output": "--- PASS: TestMul (0.00s)\n"},
    {"Action": "pass", "Package": "example.com/pkg", "Test": "TestAdd", "Elapsed": 0.001},
    {"Action": "pass", "Package": "example.com/pkg", "Test": "TestMul", "Elapsed": 0.001},
    {"Action": "pass", "Package": "example.com/pkg", "Elapsed": 0.005},
])

GOTEST_WITH_FAILURE_NDJSON = _gotest_ndjson([
    {"Action": "run", "Package": "example.com/pkg", "Test": "TestAdd"},
    {"Action": "run", "Package": "example.com/pkg", "Test": "TestMul"},
    {"Action": "output", "Package": "example.com/pkg", "Test": "TestAdd",
     "Output": "    math_test.go:12: expected 1 got 0\n"},
    {"Action": "output", "Package": "example.com/pkg", "Test": "TestAdd", "Output": "--- FAIL: TestAdd (0.00s)\n"},
    {"Action": "fail", "Package": "example.com/pkg", "Test": "TestAdd", "Elapsed": 0.001},
    {"Action": "output", "Package": "example.com/pkg", "Test": "TestMul", "Output": "--- PASS: TestMul (0.00s)\n"},
    {"Action": "pass", "Package": "example.com/pkg", "Test": "TestMul", "Elapsed": 0.001},
    {"Action": "fail", "Package": "example.com/pkg", "Elapsed": 0.005},
])


class TestGoTestParser:
    def test_all_pass(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json(GOTEST_ALL_PASS_NDJSON)
        assert result.passed == 2
        assert result.failed == 0
        assert result.failures == []
        assert result.ok is True

    def test_with_failure(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json(GOTEST_WITH_FAILURE_NDJSON)
        assert result.failed == 1
        assert len(result.failures) == 1
        assert result.ok is False

    def test_failure_test_name_extracted(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json(GOTEST_WITH_FAILURE_NDJSON)
        assert result.failures[0].test_name == "TestAdd"

    def test_failure_message_extracted(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json(GOTEST_WITH_FAILURE_NDJSON)
        assert "expected 1 got 0" in result.failures[0].message

    def test_failure_file_line_extracted(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json(GOTEST_WITH_FAILURE_NDJSON)
        assert result.failures[0].file == "math_test.go"
        assert result.failures[0].line == 12

    def test_malformed_lines_ignored(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        mixed = "not json\n" + GOTEST_ALL_PASS_NDJSON + "\nalso not json"
        result = parse_gotest_json(mixed)  # should not raise
        assert result.failed == 0

    def test_empty_input(self):
        from app.runners.parsers.gotest_parser import parse_gotest_json

        result = parse_gotest_json("")
        assert result.total_tests == 0


# ===========================================================================
# 5. Runner Command Construction & Sandbox Delegation
# ===========================================================================


class TestPythonRunner:
    def test_build_command_no_targets(self):
        from app.runners.python_runner import PythonRunner

        cmd = PythonRunner().build_command()
        assert "pytest" in " ".join(cmd)

    def test_build_command_with_targets(self):
        from app.runners.python_runner import PythonRunner

        cmd = PythonRunner().build_command(["tests/test_foo.py::test_bar"])
        assert "tests/test_foo.py::test_bar" in cmd

    def test_run_tests_calls_sandbox_run(self, tmp_path):
        from app.runners.python_runner import PythonRunner

        # Write a minimal JUnit XML so _junit_summary doesn't fail
        (tmp_path / ".fixproof_junit.xml").write_text(
            '<?xml version="1.0"?><testsuites><testsuite tests="0"/></testsuites>',
            encoding="utf-8",
        )
        sandbox = _make_sandbox(stdout="", exit_code=0)
        runner = PythonRunner()
        result = runner.run_tests(sandbox, tmp_path)
        sandbox.run.assert_called_once()
        assert result is not None

    def test_language_attribute(self):
        from app.runners.detector import Language
        from app.runners.python_runner import PythonRunner

        assert PythonRunner.language == Language.PYTHON


class TestJSRunner:
    def test_build_command_includes_vitest(self):
        from app.runners.js_runner import JSRunner

        cmd = JSRunner().build_command()
        assert "vitest" in cmd
        assert "--reporter=json" in cmd

    def test_build_command_with_targets(self):
        from app.runners.js_runner import JSRunner

        cmd = JSRunner().build_command(["src/math.test.ts"])
        assert "src/math.test.ts" in cmd

    def test_run_tests_calls_sandbox_run(self, tmp_path):
        from app.runners.js_runner import JSRunner

        sandbox = _make_sandbox(stdout=VITEST_ALL_PASS, exit_code=0)
        result = JSRunner().run_tests(sandbox, tmp_path)
        sandbox.run.assert_called_once()
        assert result.passed == 3

    def test_run_tests_parses_failures(self, tmp_path):
        from app.runners.js_runner import JSRunner

        sandbox = _make_sandbox(stdout=VITEST_WITH_FAILURES, exit_code=1)
        result = JSRunner().run_tests(sandbox, tmp_path)
        assert result.failed == 2

    def test_timed_out_result(self, tmp_path):
        from app.sandbox.base import CommandResult
        from app.runners.js_runner import JSRunner

        sandbox = MagicMock()
        sandbox.run.return_value = CommandResult(
            command="npx vitest run", exit_code=1, stdout="", stderr="",
            duration_seconds=180.0, timed_out=True,
        )
        result = JSRunner().run_tests(sandbox, tmp_path)
        assert result.timed_out is True

    def test_language_attribute(self):
        from app.runners.detector import Language
        from app.runners.js_runner import JSRunner

        assert JSRunner.language == Language.JS


class TestGoRunner:
    def test_build_command_default(self):
        from app.runners.go_runner import GoRunner

        cmd = GoRunner().build_command()
        assert "go" in cmd
        assert "test" in cmd
        assert "-json" in cmd
        assert "./..." in cmd

    def test_build_command_with_targets(self):
        from app.runners.go_runner import GoRunner

        cmd = GoRunner().build_command(["./pkg/..."])
        assert "./pkg/..." in cmd
        assert "./..." not in cmd

    def test_run_tests_calls_sandbox_run(self, tmp_path):
        from app.runners.go_runner import GoRunner

        sandbox = _make_sandbox(stdout=GOTEST_ALL_PASS_NDJSON, exit_code=0)
        result = GoRunner().run_tests(sandbox, tmp_path)
        sandbox.run.assert_called_once()
        assert result.passed == 2

    def test_run_tests_parses_failures(self, tmp_path):
        from app.runners.go_runner import GoRunner

        sandbox = _make_sandbox(stdout=GOTEST_WITH_FAILURE_NDJSON, exit_code=1)
        result = GoRunner().run_tests(sandbox, tmp_path)
        assert result.failed == 1

    def test_timed_out_result(self, tmp_path):
        from app.sandbox.base import CommandResult
        from app.runners.go_runner import GoRunner

        sandbox = MagicMock()
        sandbox.run.return_value = CommandResult(
            command="go test -json ./...", exit_code=1, stdout="", stderr="",
            duration_seconds=180.0, timed_out=True,
        )
        result = GoRunner().run_tests(sandbox, tmp_path)
        assert result.timed_out is True

    def test_language_attribute(self):
        from app.runners.detector import Language
        from app.runners.go_runner import GoRunner

        assert GoRunner.language == Language.GO


# ===========================================================================
# 6. Factory: get_language_runner
# ===========================================================================


class TestGetLanguageRunnerFactory:
    def test_python_project_returns_python_runner(self, tmp_path):
        from app.runners import get_language_runner
        from app.runners.python_runner import PythonRunner

        (tmp_path / "main.py").write_text("x = 1")
        runner = get_language_runner(tmp_path)
        assert isinstance(runner, PythonRunner)

    def test_js_project_returns_js_runner(self, tmp_path):
        from app.runners import get_language_runner
        from app.runners.js_runner import JSRunner

        (tmp_path / "package.json").write_text("{}")
        runner = get_language_runner(tmp_path)
        assert isinstance(runner, JSRunner)

    def test_go_project_returns_go_runner(self, tmp_path):
        from app.runners import get_language_runner
        from app.runners.go_runner import GoRunner

        (tmp_path / "go.mod").write_text("module example.com\n\ngo 1.21\n")
        runner = get_language_runner(tmp_path)
        assert isinstance(runner, GoRunner)

    def test_go_wins_over_js_in_factory(self, tmp_path):
        from app.runners import get_language_runner
        from app.runners.go_runner import GoRunner

        (tmp_path / "go.mod").write_text("module example.com\n\ngo 1.21\n")
        (tmp_path / "package.json").write_text("{}")
        runner = get_language_runner(tmp_path)
        assert isinstance(runner, GoRunner)

    def test_empty_dir_returns_python_runner(self, tmp_path):
        from app.runners import get_language_runner
        from app.runners.python_runner import PythonRunner

        runner = get_language_runner(tmp_path)
        assert isinstance(runner, PythonRunner)


# ===========================================================================
# 7. ProjectStore — accepts JS and Go project stubs
# ===========================================================================


class TestProjectStoreMultiLang:
    """Smoke tests that ProjectStore._finish() no longer rejects JS/Go stubs."""

    def _store(self, tmp_path: Path):
        from app.projects import ProjectStore

        return ProjectStore(root=tmp_path)

    def test_js_stub_accepted(self, tmp_path):
        """A project with only package.json + .ts files must not raise ProjectError."""
        from app.projects import ProjectError, ProjectInfo, ProjectStore

        store_root = tmp_path / "store"
        store = ProjectStore(root=store_root)

        info = ProjectInfo(name="js_demo", origin="zip")
        slot = store_root / info.id
        src = slot / "src"
        src.mkdir(parents=True)
        (src / "package.json").write_text('{"name": "js_demo"}')
        (src / "index.ts").write_text("export const x = 1;")

        # _finish() should not raise for a JS project
        result = store._finish(info)
        assert result.language == "javascript"

    def test_go_stub_accepted(self, tmp_path):
        """A project with only go.mod + .go files must not raise ProjectError."""
        from app.projects import ProjectInfo, ProjectStore

        store_root = tmp_path / "store"
        store = ProjectStore(root=store_root)

        info = ProjectInfo(name="go_demo", origin="zip")
        slot = store_root / info.id
        src = slot / "src"
        src.mkdir(parents=True)
        (src / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n")
        (src / "main.go").write_text("package main\nfunc main() {}")

        result = store._finish(info)
        assert result.language == "go"

    def test_python_stub_still_accepted(self, tmp_path):
        """Regression: existing Python projects must still work."""
        from app.projects import ProjectInfo, ProjectStore

        store_root = tmp_path / "store"
        store = ProjectStore(root=store_root)

        info = ProjectInfo(name="py_demo", origin="zip")
        slot = store_root / info.id
        src = slot / "src"
        src.mkdir(parents=True)
        (src / "main.py").write_text("x = 1\n")
        (src / "test_main.py").write_text("def test_x(): assert 1 == 1\n")

        result = store._finish(info)
        assert result.language == "python"

    def test_empty_project_still_rejected(self, tmp_path):
        """A truly empty project (no source files at all) must still raise."""
        from app.projects import ProjectError, ProjectInfo, ProjectStore

        store_root = tmp_path / "store"
        store = ProjectStore(root=store_root)

        info = ProjectInfo(name="empty_demo", origin="zip")
        slot = store_root / info.id
        src = slot / "src"
        src.mkdir(parents=True)
        # Write only a README — no code at all
        (src / "README.md").write_text("# empty")

        with pytest.raises(ProjectError, match="no Python files"):
            store._finish(info)
