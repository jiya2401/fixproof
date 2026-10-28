"""Intake of user projects: zip upload, GitHub URL, or an allow-listed local folder.

Everything here treats the project as hostile data: archives are extracted with path/size/symlink
checks, git is run without hooks/submodules/credentials, local paths must live under an
operator-approved root. Project code itself only ever executes inside the sandbox.
"""

import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import get_settings

IGNORED_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", ".idea", ".vscode",
    ".mypy_cache", ".ruff_cache", ".tox", ".fixproof_projects",
}  # fmt: skip
MAX_FILES = 5000
_GIT_URL = re.compile(
    r"^https://(github\.com|gitlab\.com|bitbucket\.org)/[\w.\-]+/[\w.\-]+?(\.git)?/?$"
)
_GIT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")


class ProjectError(ValueError):
    """User-facing intake problem (bad archive, disallowed path, limits exceeded)."""


class ProjectInfo(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    origin: str  # zip | git | local
    origin_detail: str = ""
    files: int = 0
    bytes: int = 0
    python_files: int = 0
    test_files: int = 0
    # Detected primary language — set by LanguageDetector after upload.
    # Values: "python" | "javascript" | "go"
    language: str = "python"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _max_bytes() -> int:
    return get_settings().max_project_mb * 1024 * 1024


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):  # read-only files on Windows
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onerror=onerror, ignore_errors=False) if path.exists() else None


def _ignored(parts: tuple[str, ...]) -> bool:
    return any(part in IGNORED_DIRS for part in parts)


def safe_extract_zip(data: bytes, dest: Path) -> None:
    if len(data) > _max_bytes():
        raise ProjectError(f"archive larger than {get_settings().max_project_mb} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProjectError("file is not a valid zip archive") from exc
    entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in path.parts:
            raise ProjectError(f"unsafe path in archive: {info.filename!r}")
        if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            continue  # symlinks are dropped, never followed
        if _ignored(path.parts[:-1]):
            continue
        total += info.file_size
        if total > _max_bytes() or len(entries) >= MAX_FILES:
            raise ProjectError("archive exceeds the size or file-count limit")
        entries.append((info, path))
    if not entries:
        raise ProjectError("archive contains no files")
    tops = {p.parts[0] for _, p in entries if len(p.parts) > 1}
    flatten = len(tops) == 1 and all(len(p.parts) > 1 for _, p in entries)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    for info, path in entries:
        rel = PurePosixPath(*path.parts[1:]) if flatten else path
        target = (root / rel).resolve()
        if root not in target.parents:
            raise ProjectError(f"unsafe path in archive: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _git_env(home: Path, protocol: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""), "HOME": str(home), "USERPROFILE": str(home),
        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": protocol,
        "SystemRoot": os.environ.get("SystemRoot", ""),
    }  # fmt: skip


def git_clone(url: str, dest: Path, ref: str | None = None, protocol: str = "https") -> None:
    """Shallow clone with no hooks, submodules, credentials or prompts. Caller validates `url`."""
    command = [
        "git", "-c", "protocol.allow=never", "-c", f"protocol.{protocol}.allow=always",
        "-c", "core.symlinks=false", "-c", "core.hooksPath=" + os.devnull,
        "clone", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules",
    ]  # fmt: skip
    if ref:
        command += ["--branch", ref]
    command += ["--", url, str(dest)]
    home = Path(tempfile.mkdtemp(prefix="fixproof-githome-"))
    try:
        done = subprocess.run(
            command, env=_git_env(home, protocol), capture_output=True, text=True,
            timeout=120, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise ProjectError("git clone timed out after 120s") from exc
    finally:
        shutil.rmtree(home, ignore_errors=True)
    if done.returncode != 0:
        raise ProjectError("git clone failed: " + (done.stderr.strip().splitlines() or ["?"])[-1])
    _rmtree(dest / ".git")


def _sanitize_tree(root: Path) -> tuple[int, int]:
    """Drop symlinks/ignored dirs and enforce limits. Returns (files, bytes)."""
    files = total = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        for d in list(dirs):
            full = Path(current) / d
            if d in IGNORED_DIRS or full.is_symlink():
                (full.unlink() if full.is_symlink() else _rmtree(full))
                dirs.remove(d)
        for n in names:
            full = Path(current) / n
            if full.is_symlink():
                full.unlink()
                continue
            files += 1
            total += full.stat().st_size
            if files > MAX_FILES or total > _max_bytes():
                raise ProjectError("project exceeds the size or file-count limit")
    return files, total


def _copy_limited(src: Path, dest: Path) -> None:
    def ignore(directory: str, names: list[str]) -> set[str]:
        return {n for n in names if n in IGNORED_DIRS or (Path(directory) / n).is_symlink()}

    shutil.copytree(src, dest, ignore=ignore, symlinks=False)


def _describe(root: Path, info: ProjectInfo) -> ProjectInfo:
    info.files, info.bytes = _sanitize_tree(root)
    py = [p for p in root.rglob("*.py")]
    info.python_files = len(py)
    info.test_files = sum(
        1 for p in py if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    return info


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(get_settings().projects_dir)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _slot(self, info: ProjectInfo) -> Path:
        return self.root / info.id

    def _finish(self, info: ProjectInfo) -> ProjectInfo:
        src = self._slot(info) / "src"
        try:
            _describe(src, info)
            # Detect language and relax the Python-only guard for JS/Go projects.
            from app.runners.detector import detect_language  # local import avoids circular dep
            info.language = str(detect_language(src))
            is_python = info.language == "python"
            has_go_mod = (src / "go.mod").exists()
            has_pkg_json = (src / "package.json").exists()
            if info.python_files == 0 and not has_go_mod and not has_pkg_json:
                raise ProjectError(
                    "no Python files found; for JavaScript/TypeScript include package.json,"
                    " or for Go include go.mod"
                )
        except ProjectError:
            _rmtree(self._slot(info))
            raise
        (self._slot(info) / "info.json").write_text(info.model_dump_json())
        return info

    def create_from_zip(self, data: bytes, filename: str = "project.zip") -> ProjectInfo:
        info = ProjectInfo(
            name=Path(filename).stem[:60] or "project", origin="zip", origin_detail=filename
        )
        try:
            safe_extract_zip(data, self._slot(info) / "src")
        except ProjectError:
            _rmtree(self._slot(info))
            raise
        return self._finish(info)

    def create_from_git(
        self, url: str, ref: str | None = None, _protocol: str = "https"
    ) -> ProjectInfo:
        if _protocol == "https" and not _GIT_URL.match(url.strip()):
            raise ProjectError(
                "only https://github.com, gitlab.com or bitbucket.org repository URLs are allowed"
            )
        if ref and not _GIT_REF.match(ref):
            raise ProjectError("invalid branch/tag name")
        info = ProjectInfo(
            name=url.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1][:60] or "repo",
            origin="git", origin_detail=url + (f"@{ref}" if ref else ""),
        )  # fmt: skip
        self._slot(info).mkdir(parents=True)
        try:
            git_clone(url.strip(), self._slot(info) / "src", ref, protocol=_protocol)
        except ProjectError:
            _rmtree(self._slot(info))
            raise
        return self._finish(info)

    def create_from_local(self, path: str) -> ProjectInfo:
        roots = get_settings().local_path_root_list
        if not roots:
            raise ProjectError(
                "local folders are disabled; set FIXPROOF_LOCAL_PATH_ROOTS to an allowed folder"
            )
        target = Path(path).expanduser().resolve()
        if not any(
            target == Path(r).resolve() or Path(r).resolve() in target.parents for r in roots
        ):
            raise ProjectError("that folder is outside the allowed roots")
        if not target.is_dir():
            raise ProjectError("folder does not exist")
        info = ProjectInfo(
            name=target.name[:60] or "project", origin="local", origin_detail=str(target)
        )
        self._slot(info).mkdir(parents=True)
        try:
            _copy_limited(target, self._slot(info) / "src")
        except (OSError, shutil.Error) as exc:
            _rmtree(self._slot(info))
            raise ProjectError(f"could not copy folder: {exc}") from exc
        return self._finish(info)

    def get(self, project_id: str) -> tuple[ProjectInfo, Path]:
        if not re.fullmatch(r"[0-9a-f]{12}", project_id):
            raise KeyError(project_id)
        slot = self.root / project_id
        meta = slot / "info.json"
        if not meta.exists():
            raise KeyError(project_id)
        return ProjectInfo.model_validate(json.loads(meta.read_text())), slot / "src"

    def delete(self, project_id: str) -> None:
        self.get(project_id)
        _rmtree(self.root / project_id)
