import fnmatch
import hashlib
import subprocess
from pathlib import Path, PurePosixPath

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

_TEST_GLOBS = ("test_*.py", "*_test.py", "conftest.py", "pytest.ini", "tox.ini", "setup.cfg")
_TEST_DIRS = {"tests", "test", "fixproof_adv"}


def is_protected_path(path: str) -> bool:
    """Files a patch must not touch: tests and test configuration."""
    p = PurePosixPath(path)
    if any(part in _TEST_DIRS for part in p.parts[:-1]):
        return True
    return any(fnmatch.fnmatch(p.name, pattern) for pattern in _TEST_GLOBS)


def _strip_prefix(path: str) -> str:
    return path[2:] if path[:2] in ("a/", "b/") else path


def touched_paths(diff: str) -> list[str]:
    patch = PatchSet(diff)
    paths: list[str] = []
    for patched in patch:
        for raw in (patched.source_file, patched.target_file):
            if raw and raw != "/dev/null":
                path = _strip_prefix(raw)
                if path not in paths:
                    paths.append(path)
    return paths


def patch_violations(diff: str) -> list[str]:
    """Return reasons the diff is unacceptable (empty list = acceptable)."""
    if not diff.strip():
        return ["patch is empty"]
    try:
        paths = touched_paths(diff)
    except (UnidiffParseError, ValueError) as exc:
        return [f"patch is not a parseable unified diff: {exc}"]
    if not paths:
        return ["patch touches no files"]
    problems: list[str] = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if path.startswith("/") or ".." in parts or ".git" in parts:
            problems.append(f"unsafe path in patch: {path}")
        elif is_protected_path(path):
            problems.append(f"patch modifies protected test/config file: {path}")
    return problems


def apply_patch(workspace: Path, diff: str) -> tuple[bool, str]:
    """Apply a unified diff in `workspace` using git apply (check first, then apply)."""
    body = diff if diff.endswith("\n") else diff + "\n"
    for args in (["--check"], []):
        done = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", *args, "-"],
            cwd=workspace, input=body, capture_output=True, text=True, check=False,
        )  # fmt: skip
        if done.returncode != 0:
            return False, (done.stderr or done.stdout).strip()[:2000]
    return True, "applied"


def normalized_patch_hash(diff: str) -> str:
    lines = [line.rstrip() for line in diff.strip().splitlines()]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def snapshot_hash(root: Path) -> str:
    """Content hash of a source tree (ignores VCS/cache dirs): the repository 'revision'."""
    digest = hashlib.sha256()
    skip = {".git", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not any(part in skip for part in rel.parts):
            digest.update(str(rel).encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
