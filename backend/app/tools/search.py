from pathlib import Path


def search_text(repo_root: Path, needle: str, max_results: int = 50) -> list[str]:
    """Portable starter search. M1 may replace/augment with ripgrep."""
    matches: list[str] = []
    for file_path in repo_root.rglob("*.py"):
        try:
            for line_number, line in enumerate(
                file_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if needle in line:
                    rel = file_path.relative_to(repo_root)
                    matches.append(f"{rel}:{line_number}:{line.strip()}")
                    if len(matches) >= max_results:
                        return matches
        except (UnicodeDecodeError, OSError):
            continue
    return matches
