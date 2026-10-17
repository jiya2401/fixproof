"""Turn model-authored SEARCH/REPLACE edits into a canonical unified diff.

LLMs are unreliable at writing diffs with correct hunk line numbers (a live Nemotron patch
used bare "@@" headers and was rejected by git). Instead the model states exact text to find
and replace; this module verifies each edit strictly and generates the diff itself.

Strictness: the search text must match the file exactly (line endings aside) and exactly once.
Failures return specific, actionable messages that are fed back to the fixer.
"""

import difflib
from pathlib import Path, PurePosixPath

from app.agents.models import FileEdit


def _unsafe(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if not path or path.startswith(("/", "\\")) or ".." in parts or ".git" in parts:
        return f"unsafe or empty path: {path!r}"
    return None


def _hint(text: str, search: str) -> str:
    first = next((ln.strip() for ln in search.splitlines() if ln.strip()), "")
    candidates = [ln.strip() for ln in text.splitlines() if ln.strip()]
    close = difflib.get_close_matches(first, candidates, n=1, cutoff=0.6)
    return f" Closest line in the file: {close[0]!r}." if close else ""


def build_diff_from_edits(root: Path, edits: list[FileEdit]) -> tuple[str, list[str]]:
    """Return (unified_diff, errors). On any error the diff is empty (all-or-nothing)."""
    if not edits:
        return "", ["no edits were provided"]
    errors: list[str] = []
    originals: dict[str, str] = {}
    updated: dict[str, str] = {}
    for edit in edits:
        problem = _unsafe(edit.path)
        if problem:
            errors.append(problem)
            continue
        if edit.path not in updated:
            try:
                raw = (root / edit.path).read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{edit.path}: cannot read file ({type(exc).__name__})")
                continue
            originals[edit.path] = updated[edit.path] = raw.replace("\r\n", "\n")
        search = edit.search.replace("\r\n", "\n")
        if not search.strip():
            errors.append(f"{edit.path}: SEARCH text is empty")
            continue
        count = updated[edit.path].count(search)
        if count == 0:
            errors.append(
                f"{edit.path}: SEARCH text not found; it must match the file exactly, "
                f"including indentation.{_hint(updated[edit.path], search)}"
            )
        elif count > 1:
            errors.append(
                f"{edit.path}: SEARCH text matches {count} places; add surrounding lines "
                "so it matches exactly once"
            )
        else:
            updated[edit.path] = updated[edit.path].replace(
                search, edit.replace.replace("\r\n", "\n"), 1
            )
    if errors:
        return "", errors

    chunks: list[str] = []
    for path, new_text in updated.items():
        old_text = originals[path]
        if new_text == old_text:
            errors.append(f"{path}: edits made no change")
            continue
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        for line in diff:
            chunks.append(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            )
    if errors:
        return "", errors
    return "".join(chunks), []
