"""Language-signature detector for FixProof project directories.

Detection strategy (priority order — first match wins):

1. ``go.mod`` present  →  Go   (``go test``)
2. ``package.json`` present  →  JavaScript / TypeScript   (Vitest)
3. Any ``*.py`` file present  →  Python  (pytest)
4. Fallback  →  Python  (safe default)

The detector only reads filenames / directory names — it never opens or parses
file contents — so it is fast enough to run on every project upload.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class Language(StrEnum):
    PYTHON = "python"
    JS = "javascript"
    GO = "go"


# ---------------------------------------------------------------------------
# Signature matchers
# ---------------------------------------------------------------------------

_GO_SIGNATURES: frozenset[str] = frozenset({"go.mod"})
_JS_SIGNATURES: frozenset[str] = frozenset({"package.json"})

# Directories that are never traversed during detection (prevents false positives
# from node_modules/go.mod or vendored test frameworks).
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        "vendor",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)


def _walk_top(root: Path) -> list[Path]:
    """Return all files at depth ≤ 2 (root + one subdirectory level).

    We deliberately limit depth so that a bundled Go module inside a Python
    project's ``vendor/`` tree does not override the outer language.
    """
    results: list[Path] = []
    for entry in root.iterdir():
        if entry.name in _SKIP_DIRS:
            continue
        if entry.is_file():
            results.append(entry)
        elif entry.is_dir():
            try:
                for sub in entry.iterdir():
                    if sub.is_file() and entry.name not in _SKIP_DIRS:
                        results.append(sub)
            except PermissionError:
                pass
    return results


def detect_language(root: Path) -> Language:
    """Detect the primary programming language of the project at *root*.

    Parameters
    ----------
    root:
        Absolute path to the project source directory.

    Returns
    -------
    Language
        ``Language.GO``, ``Language.JS``, or ``Language.PYTHON``.
        Never raises — falls back to ``Language.PYTHON`` on any error.
    """
    if not root.is_dir():
        return Language.PYTHON

    try:
        # Priority 1: Go — check top-level only (go.mod must be at the module root)
        if (root / "go.mod").is_file():
            return Language.GO

        # Priority 2: JS/TS — package.json at root or one level down
        if (root / "package.json").is_file():
            return Language.JS

        # Check one directory deeper for monorepo layouts
        files = _walk_top(root)
        names = {f.name for f in files}

        if "go.mod" in names:
            return Language.GO
        if "package.json" in names:
            return Language.JS

        # Priority 3: Python — any .py file anywhere in the tree
        for path in root.rglob("*.py"):
            if not any(part in _SKIP_DIRS for part in path.parts):
                return Language.PYTHON

        # Priority 4: fallback
        return Language.PYTHON

    except Exception:  # noqa: BLE001 — never crash on detection
        return Language.PYTHON

