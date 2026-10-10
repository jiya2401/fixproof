import ast
from pathlib import Path

import networkx as nx


def _module_name(repo_path: Path, file_path: Path) -> str:
    relative = file_path.relative_to(repo_path).with_suffix("")
    return ".".join(relative.parts)


def build_python_code_graph(repo_path: Path) -> nx.DiGraph:
    """Build a lightweight module/function/call graph for Python repositories.

    This is intentionally conservative. M7 will add symbol resolution and test mapping.
    """
    graph = nx.DiGraph()

    for file_path in repo_path.rglob("*.py"):
        if any(part.startswith(".") for part in file_path.relative_to(repo_path).parts):
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (UnicodeDecodeError, SyntaxError):
            continue

        module = _module_name(repo_path, file_path)
        graph.add_node(module, kind="module", path=str(file_path.relative_to(repo_path)))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = f"{module}:{node.name}"
                graph.add_node(
                    function, kind="function", path=str(file_path.relative_to(repo_path))
                )
                graph.add_edge(module, function, relation="defines")

                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            called = child.func.id
                        elif isinstance(child.func, ast.Attribute):
                            called = child.func.attr
                        else:
                            continue
                        graph.add_node(called, kind="unresolved_symbol")
                        graph.add_edge(function, called, relation="calls")

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    graph.add_node(alias.name, kind="import")
                    graph.add_edge(module, alias.name, relation="imports")
            elif isinstance(node, ast.ImportFrom) and node.module:
                graph.add_node(node.module, kind="import")
                graph.add_edge(module, node.module, relation="imports")

    return graph
