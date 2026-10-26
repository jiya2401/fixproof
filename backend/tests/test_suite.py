from pathlib import Path

from app.sandbox.local import LocalSandbox
from app.verification.suite import SuiteRun, compare, matches_target, parse_outcomes, run_suite


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


MONO = {
    "examples/my-app/test_a.py": (
        "import pytest\n"
        "def test_ok(): assert True\n"
        "def test_bad(): assert 1 == 2\n"
        "@pytest.mark.parametrize('x', [1, 'a b'])\n"
        "def test_param(x): assert x\n"
        "class TestK:\n    def test_m(self): assert True\n"
    ),
    "evals/oracle/test_o.py": "import zzz_missing_pkg\n\ndef test_x(): pass\n",
}


def test_outcomes_have_stable_ids_in_a_messy_project(tmp_path) -> None:
    run = run_suite(LocalSandbox(), write(tmp_path, MONO))
    assert run.usable
    assert run.outcomes == {
        "examples/my-app/test_a.py::test_ok": "passed",
        "examples/my-app/test_a.py::test_bad": "failed",
        "examples/my-app/test_a.py::test_param[1]": "passed",
        "examples/my-app/test_a.py::test_param[a b]": "passed",
        "examples/my-app/test_a.py::TestK::test_m": "passed",
        "evals/oracle/test_o.py": "error",  # collection error is keyed by its file
    }
    assert run.executed == 5


def test_empty_or_missing_junit_is_not_usable(tmp_path) -> None:
    assert parse_outcomes(tmp_path / "nope.xml") == {}
    assert not SuiteRun(exit_code=0).usable
    assert not SuiteRun(exit_code=2, outcomes={"a": "passed"}).usable
    assert not SuiteRun(exit_code=1, timed_out=True, outcomes={"a": "passed"}).usable


def test_compare_flags_broken_and_vanished_tests_but_not_preexisting_failures() -> None:
    before = SuiteRun(
        exit_code=1,
        outcomes={
            "a": "passed",
            "b": "passed",
            "c": "passed",
            "d": "failed",
            "e": "error",
            "f": "failed",
        },
    )
    after = SuiteRun(
        exit_code=1,
        outcomes={
            "a": "passed",
            "b": "failed",
            "d": "failed",
            "e": "passed",
            "f": "failed",
            "n": "failed",
        },
    )
    diff = compare(before, after)
    assert diff.regressions == ["b", "c"]  # b now fails, c vanished (e.g. import error)
    assert diff.still_failing == ["d", "f"] and diff.fixed == [
        "e"
    ]  # new failure "n" is not a regression


def test_target_matching() -> None:
    assert matches_target("t/test_a.py::test_x", ["t/test_a.py::test_x"])
    assert matches_target("t/test_a.py::TestK::test_m", ["t/test_a.py"])  # file-level target
    assert not matches_target("t/test_a.py::test_x[1]", ["t/test_a.py::test_x"])  # exact ids only
