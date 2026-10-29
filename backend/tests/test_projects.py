import io
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.config import get_settings
from app.projects import ProjectError, ProjectStore, safe_extract_zip
from app.verification.scan import TargetError, validate_repro_targets


def make_zip(files: dict[str, str | bytes], symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch) -> ProjectStore:
    monkeypatch.setattr(get_settings(), "projects_dir", str(tmp_path / "projects"))
    return ProjectStore()


def test_zip_with_github_style_top_folder_is_flattened(store) -> None:
    data = make_zip(
        {"repo-main/app.py": "x = 1\n", "repo-main/tests/test_app.py": "def test_a(): pass\n"}
    )
    info = store.create_from_zip(data, "repo-main.zip")
    _, src = store.get(info.id)
    assert (src / "app.py").exists() and (src / "tests" / "test_app.py").exists()
    assert info.python_files == 2 and info.test_files == 1 and info.origin == "zip"


@pytest.mark.parametrize("bad", ["../evil.py", "/abs/evil.py", "C:/evil.py", "a/../../evil.py"])
def test_zip_slip_and_absolute_paths_are_rejected(store, bad) -> None:
    with pytest.raises(ProjectError, match="unsafe path"):
        store.create_from_zip(make_zip({"ok.py": "x=1", bad: "boom"}))
    assert list(store.root.iterdir()) == []  # nothing left behind


def test_symlinks_in_archives_are_dropped_not_followed(store) -> None:
    info = store.create_from_zip(make_zip({"a.py": "x = 1\n"}, symlinks={"link.py": "/etc/passwd"}))
    _, src = store.get(info.id)
    assert (src / "a.py").exists() and not (src / "link.py").exists()


def test_ignored_dirs_are_not_extracted(store) -> None:
    info = store.create_from_zip(
        make_zip({"a.py": "x=1", ".git/config": "secret", "__pycache__/a.pyc": "x"})
    )
    _, src = store.get(info.id)
    assert not (src / ".git").exists() and not (src / "__pycache__").exists()


def test_size_limit_blocks_zip_bombs_by_uncompressed_size(store, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_project_mb", 1)
    bomb = make_zip({"a.py": "x=1", "big.bin": b"\0" * (3 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024  # compresses far below the limit
    with pytest.raises(ProjectError, match="limit"):
        store.create_from_zip(bomb)


def test_not_a_zip_and_no_python_are_clear_errors(store) -> None:
    with pytest.raises(ProjectError, match="valid zip"):
        store.create_from_zip(b"not a zip")
    with pytest.raises(ProjectError, match="no Python files"):
        store.create_from_zip(make_zip({"README.md": "hi"}))
    assert list(store.root.iterdir()) == []


def test_project_ids_cannot_traverse(store) -> None:
    for bad in ["../x", "..", "a" * 12 + "/../..", "", "ZZZZZZZZZZZZ"]:
        with pytest.raises(KeyError):
            store.get(bad)


def test_local_folders_disabled_by_default_and_confined_to_roots(
    store, tmp_path, monkeypatch
) -> None:
    project = tmp_path / "mine"
    project.mkdir()
    (project / "m.py").write_text("x = 1\n")
    with pytest.raises(ProjectError, match="disabled"):
        store.create_from_local(str(project))
    monkeypatch.setattr(get_settings(), "local_path_roots", str(tmp_path / "allowed"))
    with pytest.raises(ProjectError, match="outside the allowed roots"):
        store.create_from_local(str(project))
    monkeypatch.setattr(get_settings(), "local_path_roots", str(tmp_path))
    info = store.create_from_local(str(project))
    assert info.origin == "local" and info.python_files == 1


def test_local_copy_skips_symlinks(store, tmp_path, monkeypatch) -> None:
    project = tmp_path / "mine"
    project.mkdir()
    (project / "m.py").write_text("x = 1\n")
    (project / "link.py").symlink_to("/etc/passwd")
    monkeypatch.setattr(get_settings(), "local_path_roots", str(tmp_path))
    _, src = store.get(store.create_from_local(str(project)).id)
    assert not (src / "link.py").exists()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc",
        "http://github.com/a/b",
        "https://evil.example/a/b",
        "https://github.com/a/b; rm -rf /",
        "ext::sh -c id",
        "--upload-pack=x",
    ],
)
def test_git_urls_are_allow_listed(store, url) -> None:
    with pytest.raises(ProjectError, match="only https"):
        store.create_from_git(url)


def test_git_ref_cannot_inject_options(store) -> None:
    with pytest.raises(ProjectError, match="invalid branch"):
        store.create_from_git("https://github.com/a/b", ref="--upload-pack=touch /tmp/x")


def test_git_clone_drops_dot_git_and_history(store, tmp_path) -> None:
    repo = tmp_path / "origin"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    info = store.create_from_git(str(repo), _protocol="file")  # file protocol only for this test
    _, src = store.get(info.id)
    assert (src / "m.py").exists() and not (src / ".git").exists() and info.origin == "git"


def test_repro_targets_are_validated(tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): assert False\n")
    (tmp_path / "notes.txt").write_text("x")
    assert validate_repro_targets(tmp_path, ["tests/test_a.py::test_x"]) == [
        "tests/test_a.py::test_x"
    ]
    for bad in [
        [],
        ["--rootdir=/"],
        ["-p", "x"],
        ["../x.py"],
        ["tests/missing.py"],
        ["notes.txt"],
        [" "],
        ["a\nb.py"],
    ]:
        with pytest.raises(TargetError):
            validate_repro_targets(tmp_path, bad)
    with pytest.raises(TargetError):
        validate_repro_targets(tmp_path, ["tests/test_a.py"] * 11)


def test_safe_extract_rejects_zip_with_only_ignored_content(tmp_path) -> None:
    with pytest.raises(ProjectError, match="no files"):
        safe_extract_zip(make_zip({".git/config": "x"}), tmp_path / "out")
    assert isinstance(tmp_path, Path)
