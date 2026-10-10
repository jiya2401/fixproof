import pytest

from app.repair.patching import (
    apply_patch,
    is_protected_path,
    normalized_patch_hash,
    patch_violations,
    snapshot_hash,
)
from tests.conftest import fixture_text


def test_good_patch_has_no_violations() -> None:
    assert patch_violations(fixture_text("auth_correct.diff")) == []


@pytest.mark.parametrize(
    "path", ["test_auth.py", "pkg/tests/x.py", "conftest.py", "pytest.ini", "a/b_test.py"]
)
def test_protected_paths(path: str) -> None:
    assert is_protected_path(path)


def test_patch_touching_tests_is_rejected() -> None:
    diff = (
        "--- a/test_auth.py\n+++ b/test_auth.py\n@@ -1,1 +1,1 @@\n-from auth import x\n+import os\n"
    )
    assert any("protected" in v for v in patch_violations(diff))


def test_path_traversal_is_rejected() -> None:
    diff = "--- a/../evil.py\n+++ b/../evil.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    assert any("unsafe" in v for v in patch_violations(diff))


def test_empty_and_garbage_patches_rejected() -> None:
    assert patch_violations("")
    assert patch_violations("this is not a diff")


def test_apply_and_failed_apply(auth_src, tmp_path) -> None:
    import shutil

    ws = tmp_path / "ws"
    shutil.copytree(auth_src, ws)
    ok, _ = apply_patch(ws, fixture_text("auth_correct.diff"))
    assert ok and 'token_type == "refresh"' in (ws / "auth.py").read_text()
    ok_again, message = apply_patch(ws, fixture_text("auth_correct.diff"))
    assert not ok_again and message


def test_snapshot_hash_is_content_sensitive(tmp_path) -> None:
    (tmp_path / "a.py").write_text("x = 1")
    first = snapshot_hash(tmp_path)
    assert first == snapshot_hash(tmp_path)
    (tmp_path / "a.py").write_text("x = 2")
    assert first != snapshot_hash(tmp_path)


def test_patch_hash_ignores_trailing_whitespace() -> None:
    assert normalized_patch_hash("a \nb\n") == normalized_patch_hash("a\nb")


# --- line-ending handling (Windows checkouts / CRLF repositories) ---------------------------


def _crlf_copy(src, dest, name="auth.py", mixed=False):
    import shutil

    shutil.copytree(src, dest)
    path = dest / name
    data = path.read_bytes().replace(b"\r\n", b"\n")
    crlf = data.replace(b"\n", b"\r\n")
    if mixed:  # first line CRLF, rest LF
        crlf = data.replace(b"\n", b"\r\n", 1)
    path.write_bytes(crlf)
    return dest


def test_lf_diff_applies_to_crlf_file_and_preserves_crlf(auth_src, tmp_path) -> None:
    ws = _crlf_copy(auth_src, tmp_path / "ws")
    ok, message = apply_patch(ws, fixture_text("auth_correct.diff"))
    assert ok, message
    result = (ws / "auth.py").read_bytes()
    assert b'token_type == "refresh"' in result
    assert result.count(b"\n") == result.count(b"\r\n")  # still uniformly CRLF


def test_crlf_diff_applies_to_lf_file(auth_src, tmp_path) -> None:
    import shutil

    ws = tmp_path / "ws"
    shutil.copytree(auth_src, ws)
    (ws / "auth.py").write_bytes((ws / "auth.py").read_bytes().replace(b"\r\n", b"\n"))
    crlf_diff = fixture_text("auth_correct.diff").replace("\n", "\r\n")
    ok, message = apply_patch(ws, crlf_diff)
    assert ok, message
    assert b"\r" not in (ws / "auth.py").read_bytes()


def test_matching_is_still_strict_on_content_and_leaves_workspace_untouched(
    auth_src, tmp_path
) -> None:
    ws = _crlf_copy(auth_src, tmp_path / "ws")
    path = ws / "auth.py"
    path.write_bytes(path.read_bytes().replace(b"if not value:", b"if  not value:"))  # 1 space
    before = path.read_bytes()
    ok, message = apply_patch(ws, fixture_text("auth_correct.diff"))
    assert not ok and message
    assert path.read_bytes() == before


def test_mixed_line_endings_are_refused_not_guessed(auth_src, tmp_path) -> None:
    ws = _crlf_copy(auth_src, tmp_path / "ws", mixed=True)
    before = (ws / "auth.py").read_bytes()
    ok, message = apply_patch(ws, fixture_text("auth_correct.diff"))
    assert not ok and "mixed line endings" in message
    assert (ws / "auth.py").read_bytes() == before


def test_no_newline_at_eof_marker_with_crlf_file(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_bytes(b"a = 1\r\nb = 2")  # CRLF, no trailing newline
    diff = (
        "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n"
        "\\ No newline at end of file\n+b = 3\n\\ No newline at end of file\n"
    )
    ok, message = apply_patch(ws, diff)
    assert ok, message
    assert (ws / "m.py").read_bytes() == b"a = 1\r\nb = 3"
