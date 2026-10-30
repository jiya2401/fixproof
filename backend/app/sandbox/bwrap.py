import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.sandbox.base import CommandResult, SandboxRunner
from app.sandbox.common import _IGNORE, MAX_OUTPUT_CHARS
from app.verification.results import SandboxInfo


class BwrapUnavailable(RuntimeError):
    pass


class BwrapSandbox(SandboxRunner):
    """Linux user-namespace sandbox using bubblewrap (`bwrap`).

    Provides genuine container-grade isolation without requiring a Docker daemon:
    - Mount namespace: host root mounted read-only (--ro-bind / /), fresh /proc and /dev,
      private empty tmpfs for /tmp, and /app is hidden via tmpfs to prevent reading backend
      source or stored projects when /app exists on the host.
    - Network namespace: unshared (--unshare-all includes --unshare-net), blocking all
      outbound network connections.
    - PID, UTS, IPC namespaces: untrusted code runs isolated from other processes.
    - Environment isolation: --clearenv scrubs all host environment variables, ensuring
      secrets like NEBIUS_API_KEY or GITHUB_TOKEN are never visible.
    - Timeout & killing: processes die with parent (--die-with-parent) and are terminated
      with SIGKILL on timeout.
    """

    def __init__(self) -> None:
        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            raise BwrapUnavailable(
                "bubblewrap (bwrap) not found on PATH. "
                "Install it via `apt-get install -y bubblewrap`."
            )
        self._bwrap = bwrap_path

        # Probe unprivileged user namespace support
        probe = subprocess.run(
            [
                bwrap_path,
                "--ro-bind", "/", "/",
                "--proc", "/proc",
                "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
                "--clearenv",
                "--",
                "true",
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if probe.returncode != 0:
            err = probe.stderr.decode(errors="replace")[:300]
            raise BwrapUnavailable(
                f"bwrap cannot create user namespaces (exit {probe.returncode}): {err}. "
                "Ensure the host kernel supports unprivileged user namespaces."
            )
        self._self_tested = False

    def bwrap_argv(self, workspace: Path, command: list[str]) -> list[str]:
        cmd = [sys.executable if command[0] == "python" else command[0], *command[1:]]
        argv = [
            self._bwrap,
            "--ro-bind", "/", "/",          # read-only root filesystem
            "--proc", "/proc",              # private fresh /proc
            "--dev", "/dev",                # private fresh /dev
            "--tmpfs", "/tmp",              # private writable /tmp
        ]
        # Only mask /app if it exists on the host (e.g. inside the Docker production container).
        # On hosts where /app does not exist, mounting a tmpfs over a non-existent path
        # on a read-only root causes bwrap to fail with EROFS
        # ("Can't mkdir /app: Read-only file system").
        if os.path.exists("/app"):
            argv.extend(["--tmpfs", "/app"])

        argv.extend([
            "--bind", str(workspace), "/tmp/work",  # isolated workspace writable in tmpfs
            "--chdir", "/tmp/work",
            "--unshare-all",                # user, mount, net, pid, ipc, uts isolation
            "--die-with-parent",
            "--new-session",
            "--clearenv",                   # scrub all host environment variables
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONHASHSEED", "0",
            "--setenv", "PYTHONPATH", "/tmp/work:/tmp/work/src",
            "--",
            *cmd,
        ])
        return argv

    def prepare_workspace(self, source: Path) -> Path:
        destination = Path(tempfile.mkdtemp(prefix="fixproof-bwrap-")) / "repo"
        shutil.copytree(source, destination, ignore=_IGNORE)
        # Ensure files are writable by the unshared namespace user
        for root, dirs, files in os.walk(destination):
            for entry in [*dirs, *files]:
                p = Path(root) / entry
                if not p.is_symlink():
                    try:
                        p.chmod(0o777 if p.is_dir() else 0o666)
                    except OSError:
                        pass
        try:
            destination.chmod(0o777)
        except OSError:
            pass
        return destination

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        argv = self.bwrap_argv(workspace, command)
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            code, out, err = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code = -9
            out = str(exc.stdout or "")
            err = str(exc.stderr or "")

        return CommandResult(
            command=" ".join(command),
            exit_code=code,
            stdout=out[:MAX_OUTPUT_CHARS],
            stderr=err[:MAX_OUTPUT_CHARS],
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
        )

    def destroy(self, workspace: Path) -> None:
        shutil.rmtree(workspace.parent, ignore_errors=True)

    def self_test(self) -> list[str]:
        failures: list[str] = []
        tmp_dir = Path(tempfile.mkdtemp(prefix="fixproof-bwrap-test-"))
        try:
            ws = self.prepare_workspace(tmp_dir)
            try:
                probes = {
                    "network is blocked": [
                        "python",
                        "-c",
                        ("import socket,sys\ntry:\n"
                        " socket.create_connection(('1.1.1.1',53),2)\n"
                        " sys.exit(1)\nexcept OSError:\n sys.exit(0)"),
                    ],
                    "filesystem root is read-only": [
                        "python",
                        "-c",
                        ("import sys\ntry:\n open('/etc/fixproof_probe','w').close()\n"
                        " sys.exit(1)\nexcept OSError:\n sys.exit(0)"),
                    ],
                    "backend source is hidden": [
                        "python",
                        "-c",
                        ("import os,sys\n"
                        "sys.exit(1 if os.path.exists('/app') and os.listdir('/app') else 0)"),
                    ],
                    "host environment is not visible": [
                        "python",
                        "-c",
                        ("import os,sys\nsys.exit(1 if 'NEBIUS_API_KEY' in os.environ or "
                        "'FIXPROOF_GITHUB_TOKEN' in os.environ else 0)"),
                    ],
                }
                for label, cmd in probes.items():
                    res = self.run(ws, cmd, timeout_seconds=30)
                    if not res.passed:
                        failures.append(label)
            finally:
                self.destroy(ws)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self._self_tested = not failures
        return failures

    def describe(self) -> SandboxInfo:
        notes = [
            "bubblewrap namespace sandbox: mount, network, PID, UTS, IPC isolation.",
            ("Root filesystem read-only; /app hidden via tmpfs (when present); "
             "workspace at /tmp/work."),
            "Environment completely cleared (--clearenv); no host variables visible.",
        ]
        if not self._self_tested:
            notes.append("self_test() has not passed on this host")
        return SandboxInfo(
            kind="bwrap",
            isolation="bwrap",
            network_blocked=True,
            isolation_self_tested=self._self_tested,
            notes=notes,
        )
