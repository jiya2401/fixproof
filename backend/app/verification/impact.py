from pathlib import Path

import networkx as nx

from app.codegraph.parser import build_python_code_graph


def impacted_nodes(repo_path: Path, changed_symbol: str, depth: int = 2) -> set[str]:
    graph = build_python_code_graph(repo_path)
    if changed_symbol not in graph:
        return set()

    reversed_graph = graph.reverse(copy=False)
    result = {changed_symbol}
    frontier = {changed_symbol}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            next_frontier.update(nx.descendants_at_distance(reversed_graph, node, 1))
        result.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return result
