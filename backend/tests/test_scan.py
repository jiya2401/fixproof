from pathlib import Path

from app.sandbox.local import LocalSandbox
from app.verification.scan import scan_project


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def test_scan_lists_failing_tests_with_node_ids(paginate_src) -> None:
    scan = scan_project(LocalSandbox(), paginate_src)
    assert scan.tests == 2 and scan.failed == 1
    assert [t.node_id for t in scan.failing_tests] == [
        "test_paginate.py::test_second_page_returns_items_4_to_6"
    ]
    assert "assert" in scan.failing_tests[0].message.lower()


def test_scan_reports_missing_dependency_with_actionable_hint(tmp_path) -> None:
    write(tmp_path, {"test_a.py": "import not_installed_pkg\n\ndef test_a():\n    pass\n"})
    scan = scan_project(LocalSandbox(), tmp_path)
    assert scan.missing_modules == ["not_installed_pkg"]
    assert "extra-requirements.txt" in scan.hint and scan.failing_tests == []
    assert scan.collection_errors


def test_scan_all_passing_and_no_tests(tmp_path) -> None:
    passing = write(tmp_path / "p", {"test_a.py": "def test_a():\n    assert True\n"})
    assert "All tests pass" in scan_project(LocalSandbox(), passing).hint
    empty = write(tmp_path / "e", {"a.py": "x = 1\n"})
    assert "no tests" in scan_project(LocalSandbox(), empty).hint


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
