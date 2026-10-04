from pathlib import Path


class PathOutsideRepository(ValueError):
    pass


def safe_resolve(repo_root: Path, relative_path: str) -> Path:
    root = repo_root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise PathOutsideRepository(relative_path)
    return candidate


def read_text(repo_root: Path, relative_path: str, max_chars: int = 100_000) -> str:
    path = safe_resolve(repo_root, relative_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    return content[:max_chars]
