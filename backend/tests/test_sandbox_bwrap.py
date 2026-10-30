"""Tests for BwrapSandbox and its factory integration."""

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.sandbox.bwrap import BwrapSandbox, BwrapUnavailable
from app.sandbox.factory import SandboxUnavailable, get_sandbox

BWRAP_AVAILABLE = shutil.which("bwrap") is not None


def test_bwrap_argv_contains_isolation_flags() -> None:
    """Command line contains all required namespace and filesystem isolation flags."""
    sandbox = BwrapSandbox.__new__(BwrapSandbox)
    sandbox._bwrap = "/usr/bin/bwrap"
    sandbox._self_tested = False
    ws = Path("/tmp/ws/repo")
    with patch("os.path.exists", side_effect=lambda p: True if p == "/app" else os.path.exists(p)):
        argv = sandbox.bwrap_argv(ws, ["python", "-m", "pytest"])
        joined = " ".join(argv)

        assert "--unshare-all" in joined
    assert "--clearenv" in joined
    assert "--tmpfs /tmp" in joined
    assert "--tmpfs /app" in joined
    assert "--ro-bind / /" in joined
    assert "--proc /proc" in joined
    assert "--dev /dev" in joined
    assert "--die-with-parent" in joined
    assert f"--bind {ws} /work" in joined
    assert "--chdir /work" in joined
    assert "NEBIUS" not in joined
    assert "GITHUB" not in joined


def test_bwrap_unavailable_when_not_on_path() -> None:
    with patch("shutil.which", return_value=None):
        with pytest.raises(BwrapUnavailable, match="not found on PATH"):
            BwrapSandbox()


def test_bwrap_user_ns_probe_failure_raises() -> None:
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = b"bwrap: No user namespaces allowed"
    with patch("shutil.which", return_value="/usr/bin/bwrap"), \
         patch("subprocess.run", return_value=fake_result):
        with pytest.raises(BwrapUnavailable, match="user namespaces"):
            BwrapSandbox()


def test_factory_resolves_bwrap_and_calls_self_test(monkeypatch) -> None:
    fake_sandbox = MagicMock(spec=BwrapSandbox)
    fake_sandbox.self_test.return_value = []

    monkeypatch.setenv("FIXPROOF_SANDBOX_MODE", "bwrap")
    # Clear lru_cache on get_settings so new env is read
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.sandbox.bwrap.BwrapSandbox", return_value=fake_sandbox):
        sb = get_sandbox()
        assert sb is fake_sandbox
        fake_sandbox.self_test.assert_called_once()


def test_factory_bwrap_unavailable_raises_sandbox_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("FIXPROOF_SANDBOX_MODE", "bwrap")
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.sandbox.bwrap.BwrapSandbox", side_effect=BwrapUnavailable("bwrap not found")):
        with pytest.raises(SandboxUnavailable, match="bubblewrap sandbox unavailable"):
            get_sandbox()


def test_factory_bwrap_failed_self_test_refuses_to_start(monkeypatch) -> None:
    fake_sandbox = MagicMock(spec=BwrapSandbox)
    fake_sandbox.self_test.return_value = ["network is blocked", "root filesystem is read-only"]

    monkeypatch.setenv("FIXPROOF_SANDBOX_MODE", "bwrap")
    from app.config import get_settings
    get_settings.cache_clear()

    with patch("app.sandbox.bwrap.BwrapSandbox", return_value=fake_sandbox):
        with pytest.raises(SandboxUnavailable, match="bubblewrap sandbox self-test failed"):
            get_sandbox()


def test_factory_rejects_unsupported_mode(monkeypatch) -> None:
    monkeypatch.setenv("FIXPROOF_SANDBOX_MODE", "invalid-mode")
    from app.config import get_settings
    get_settings.cache_clear()

    with pytest.raises(SandboxUnavailable, match="Unsupported FIXPROOF_SANDBOX_MODE"):
        get_sandbox()


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap (bwrap) not installed on host")
def test_bwrap_runs_simple_command(tmp_path: Path) -> None:
    sandbox = BwrapSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        result = sandbox.run(ws, ["python", "-c", "print('hello_from_bwrap')"])
        assert result.passed
        assert "hello_from_bwrap" in result.stdout
    finally:
        sandbox.destroy(ws)


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap (bwrap) not installed on host")
def test_bwrap_network_is_blocked(tmp_path: Path) -> None:
    sandbox = BwrapSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        result = sandbox.run(
            ws,
            [
                "python",
                "-c",
                "import socket,sys\ntry:\n socket.create_connection(('1.1.1.1',53),2)\n sys.exit(1)\nexcept OSError:\n sys.exit(0)",
            ],
        )
        assert result.passed, f"Network should be blocked: {result.stderr}"
    finally:
        sandbox.destroy(ws)


@pytest.mark.skipif(not BWRAP_AVAILABLE, reason="bubblewrap (bwrap) not installed on host")
def test_bwrap_env_is_cleared(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret-key-1234")
    monkeypatch.setenv("FIXPROOF_GITHUB_TOKEN", "ghp_secrettoken")
    sandbox = BwrapSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        result = sandbox.run(
            ws,
            [
                "python",
                "-c",
                "import os,sys\nsys.exit(1 if 'NEBIUS_API_KEY' in os.environ or 'FIXPROOF_GITHUB_TOKEN' in os.environ else 0)",
            ],
        )
        assert result.passed, "Host secrets must be stripped from sandbox environment"
    finally:
        sandbox.destroy(ws)

