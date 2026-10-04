from pathlib import Path

from app.codegraph.parser import build_python_code_graph


def test_codegraph_finds_function_and_call(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
        encoding="utf-8",
    )
    graph = build_python_code_graph(tmp_path)
    assert "service:main" in graph
    assert graph.has_edge("service:main", "helper")
