"""Boundary Protection Map for FixProof.

Partitions every file in a project into two disjoint buckets:

``editable_paths``
    Application source files that the patch-generation LLM is allowed to
    view and modify.  These are relative POSIX paths (e.g. ``src/utils.py``).

``locked_paths``
    Test infrastructure, configuration, and build-system files that must
    **never** be given to the LLM as editable context.  The LLM may still
    *read* failing test files (as read-only context), but it cannot receive
    them as patchable paths.

The split is based entirely on file names and path patterns — content is
never read here.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Lock patterns — files matching ANY of these are always locked
# ---------------------------------------------------------------------------

# Directory prefixes: a file is locked if any of its path components matches.
_LOCKED_DIRS: frozenset[str] = frozenset(
    {
        "tests",
        "test",
        "__tests__",
        "spec",
        "specs",
        "e2e",
        "fixtures",
        "testdata",       # Go convention
        "fixproof_adv",   # FixProof adversarial test dir
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".github",
        "coverage",
        ".nyc_output",
    }
)

# Glob patterns matched against the **basename** of a file.
_LOCKED_BASENAMES: tuple[str, ...] = (
    # Python test files
    "test_*.py",
    "*_test.py",
    "conftest.py",
    # Go test files
    "*_test.go",
    # TypeScript / JavaScript test files
    "*.test.ts",
    "*.test.tsx",
    "*.test.js",
    "*.test.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.js",
    "*.spec.jsx",
    # Configuration / build / lock files
    "go.mod",
    "go.sum",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "Makefile",
    "Dockerfile*",
    "docker-compose*.yml",
    "*.toml",
    "*.cfg",
    "*.ini",
    "*.yaml",
    "*.yml",
    "tsconfig*.json",
    "vite.config.*",
    "vitest.config.*",
    "jest.config.*",
    ".eslintrc*",
    ".prettierrc*",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    "*.md",
    "*.rst",
    "LICENSE*",
    "CHANGELOG*",
    "CONTRIBUTING*",
)

# Source-file extensions that are candidates for ``editable_paths``.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class BoundaryMap:
    """The partitioned view of a project's files.

    All paths are **relative POSIX strings** (forward slashes, no leading
    slash) relative to the project source root.

    Attributes
    ----------
    editable_paths:
        Files the patch-gen LLM may view and propose edits for.
    locked_paths:
        Files the LLM must never receive as patchable context.
    root:
        The absolute source root used to build this map.
    """

    editable_paths: list[str] = field(default_factory=list)
    locked_paths: list[str] = field(default_factory=list)
    root: Path = field(default_factory=Path)

    def is_editable(self, rel_path: str) -> bool:
        """Return True iff *rel_path* (POSIX) is editable."""
        return rel_path in set(self.editable_paths)

    def is_locked(self, rel_path: str) -> bool:
        """Return True iff *rel_path* (POSIX) is locked."""
        return rel_path in set(self.locked_paths)


def _is_locked(rel: Path) -> bool:
    """Return True when *rel* (relative Path) matches any lock rule."""
    # Check every directory component
    for part in rel.parts[:-1]:  # parent dirs only (not the filename itself)
        if part in _LOCKED_DIRS:
            return True

    # Check the filename itself against the dir set too (e.g. a file literally
    # named "test" at the root, which is unusual but possible in Go).
    name = rel.name
    if name in _LOCKED_DIRS:
        return True

    # Glob patterns on basename
    for pattern in _LOCKED_BASENAMES:
        if fnmatch.fnmatch(name, pattern):
            return True

    return False


def build_boundary_map(root: Path) -> BoundaryMap:
    """Partition all files under *root* into editable and locked buckets.

    Parameters
    ----------
    root:
        Absolute path to the project source directory.

    Returns
    -------
    BoundaryMap
        A ``BoundaryMap`` where every file under *root* appears in exactly
        one of ``editable_paths`` or ``locked_paths``.
    """
    editable: list[str] = []
    locked: list[str] = []

    if not root.is_dir():
        return BoundaryMap(root=root)

    for abs_path in sorted(root.rglob("*")):
        if not abs_path.is_file():
            continue
        rel = abs_path.relative_to(root)
        rel_posix = rel.as_posix()

        if _is_locked(rel):
            locked.append(rel_posix)
        elif rel.suffix in _SOURCE_EXTENSIONS:
            # Only source-code files are exposed as editable;
            # binary assets and unknown formats go to locked.
            editable.append(rel_posix)
        else:
            locked.append(rel_posix)

    return BoundaryMap(editable_paths=editable, locked_paths=locked, root=root)

