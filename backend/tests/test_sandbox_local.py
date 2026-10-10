import os
import time

from app.sandbox.local import LocalSandbox


def test_env_secrets_are_not_inherited(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    sandbox = LocalSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        out = sandbox.run(ws, ["python", "-c", "import os;print(sorted(os.environ))"])
        assert "NEBIUS_API_KEY" not in out.stdout and "GITHUB_TOKEN" not in out.stdout
        assert "super-secret" not in out.stdout
    finally:
        sandbox.destroy(ws)


def test_timeout_kills_process_group(tmp_path) -> None:
    sandbox = LocalSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        started = time.monotonic()
        result = sandbox.run(
            ws,
            [
                "python",
                "-c",
                "import subprocess,time;subprocess.Popen(['sleep','60']);time.sleep(60)",
            ],
            timeout_seconds=2,
        )
        assert result.timed_out and not result.passed
        assert time.monotonic() - started < 15
    finally:
        sandbox.destroy(ws)


def test_network_is_blocked_when_namespace_available(tmp_path) -> None:
    sandbox = LocalSandbox()
    info = sandbox.describe()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        probe = (
            "import socket,sys\n"
            "try:\n socket.create_connection(('1.1.1.1', 53), 2)\n"
            "except OSError:\n sys.exit(0)\nsys.exit(1)\n"
        )
        result = sandbox.run(ws, ["python", "-c", probe])
        if info.network_blocked:
            assert result.passed, result.stderr
        else:
            assert any("network" in n.lower() for n in info.notes)
    finally:
        sandbox.destroy(ws)


def test_memory_limit_is_enforced(tmp_path) -> None:
    sandbox = LocalSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        result = sandbox.run(ws, ["python", "-c", "x = bytearray(4 * 1024**3)"])
        assert not result.passed
    finally:
        sandbox.destroy(ws)


def test_local_sandbox_honestly_reports_process_isolation_only(tmp_path) -> None:
    sandbox = LocalSandbox()
    info = sandbox.describe()
    assert info.isolation == "process" and not info.isolation_self_tested
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        # Known limitation, asserted so it can never silently be described as secure:
        result = sandbox.run(ws, ["python", "-c", "print(open('/etc/passwd').read()[:4])"])
        assert result.passed and os.path.exists("/etc/passwd")
    finally:
        sandbox.destroy(ws)


def test_workspace_is_a_copy(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x")
    sandbox = LocalSandbox()
    ws = sandbox.prepare_workspace(tmp_path)
    try:
        sandbox.run(ws, ["python", "-c", "open('a.txt','w').write('changed')"])
        assert (tmp_path / "a.txt").read_text() == "x"
    finally:
        sandbox.destroy(ws)
