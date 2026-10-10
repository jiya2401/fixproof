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
