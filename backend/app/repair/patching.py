import fnmatch
import hashlib
import re
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


_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _file_eol(path: Path) -> str | None:
    """Return the file's uniform line ending ("\n" or "\r\n"), or None if mixed/unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return "\n"  # new file: nothing to match against
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        return None
    return "\r\n" if crlf else "\n"


def adapt_diff_to_file_endings(workspace: Path, diff: str) -> tuple[str | None, str]:
    """Re-encode each file's hunk lines in that file's own line-ending style.

    Models and tools see source through universal-newline reads (always LF), but the file on
    disk may be CRLF (Windows checkouts). Context must still match byte-for-byte; only the EOL
    representation of the diff is adapted, in memory. Mixed-ending files are refused rather
    than guessed. Returns (adapted_diff, "") or (None, reason).
    """
    lines = diff.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out: list[str] = []
    eol = "\n"
    old_left = new_left = 0
    for index, line in enumerate(lines):
        if old_left == 0 and new_left == 0:  # outside a hunk body: headers stay LF
            if line.startswith("--- "):
                target = _strip_prefix(line[4:].split("\t")[0].strip())
                found = _file_eol(workspace / target) if target != "/dev/null" else "\n"
                if found is None:
                    return None, f"{target} has mixed line endings; refusing to guess"
                eol = found
            match = _HUNK_HEADER.match(line)
            if match:
                old_left = int(match.group(1) if match.group(1) is not None else 1)
                new_left = int(match.group(2) if match.group(2) is not None else 1)
            out.append(line + "\n")
            continue
        if line.startswith("\\"):  # "\ No newline at end of file"
            out.append(line + "\n")
            continue
        marker = line[:1]
        old_left -= marker in (" ", "-", "")
        new_left -= marker in (" ", "+", "")
        # The final line of a file with no trailing newline carries no CR either.
        no_eol_follows = index + 1 < len(lines) and lines[index + 1].startswith("\\")
        out.append(line + ("\n" if no_eol_follows else eol))
    return "".join(out), ""


def apply_patch(workspace: Path, diff: str) -> tuple[bool, str]:
    """Apply a unified diff with `git apply` (all-or-nothing): check first, then apply.

    Strict: no whitespace-insensitive matching. The workspace is never modified unless the
    adapted diff passes `--check`, so a failed patch leaves it untouched.
    """
    adapted, reason = adapt_diff_to_file_endings(workspace, diff)
    if adapted is None:
        return False, reason
    body = adapted.encode("utf-8")  # bytes: no platform newline translation
    for args in (["--check"], []):
        done = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", *args, "-"],
            cwd=workspace, input=body, capture_output=True, check=False,
        )  # fmt: skip
        if done.returncode != 0:
            message = (done.stderr or done.stdout).decode("utf-8", "replace").strip()
            return False, message[:2000]
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
