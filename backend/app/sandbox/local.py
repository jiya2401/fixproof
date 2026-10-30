import logging
import os
import shutil

try:
    import resource
except ImportError:
    resource = None

import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.sandbox.base import CommandResult, SandboxRunner
from app.sandbox.common import _IGNORE, MAX_OUTPUT_CHARS
from app.verification.results import SandboxInfo

logger = logging.getLogger("fixproof.sandbox.local")


class UnsafeLocalExecutionDisabled(RuntimeError):
    pass


def _network_namespace_available() -> bool:
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    try:
        probe = subprocess.run(
            [unshare, "-rn", "true"], capture_output=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def _limit_resources() -> None:
    if resource is None:
        raise RuntimeError("LocalSandbox resource limits require a Unix-like OS.")

    os.setsid()
    limits = [
        (resource.RLIMIT_CORE, (0, 0)),
        (resource.RLIMIT_CPU, (120, 120)),
        (resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3)),
        (resource.RLIMIT_FSIZE, (50 * 1024**2, 50 * 1024**2)),
        (resource.RLIMIT_NPROC, (512, 512)),
    ]
    for res, val in limits:
        try:
            resource.setrlimit(res, val)
        except (ValueError, OSError):
            pass


class LocalSandbox(SandboxRunner):
    """Hardened *process* sandbox for development.

    Provides: scrubbed environment (no API keys / credentials inherited), rlimits (CPU,
    memory, file size, processes), wall-clock timeout with process-group kill, a throwaway
    workspace copy, and — when the kernel allows it — an empty network namespace.

    Does NOT provide: filesystem isolation. Target code can still read host files that the
    server user can read. Therefore describe().isolation == "process" and the verdict policy
    caps results at VERIFIED_WITH_CONDITIONS. Disabled unless explicitly enabled.
    """

    def __init__(self) -> None:
        if resource is None:
            raise UnsafeLocalExecutionDisabled(
                "LocalSandbox requires a Unix-like OS. Use DockerSandbox on Windows."
            )

        if not get_settings().allow_unsafe_local_execution:
            raise UnsafeLocalExecutionDisabled(
                "Local target-code execution is disabled. Use an isolated sandbox or set "
                "FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true for local development only."
            )
        self._net_blocked = _network_namespace_available()

    def prepare_workspace(self, source: Path) -> Path:
        destination = Path(tempfile.mkdtemp(prefix="fixproof-local-")) / "repo"
        shutil.copytree(source, destination, ignore=_IGNORE)
        return destination

    @staticmethod
    def _env(workspace: Path) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(workspace),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": os.pathsep.join([str(workspace), str(workspace / "src")]),
        }

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        cmd_str = " ".join(command)
        argv = [sys.executable if command[0] == "python" else command[0], *command[1:]]
        if self._net_blocked:
            argv = ["unshare", "-rn", "--", *argv]
        started = time.monotonic()
        timed_out = False
        logger.info(
            "LocalSandbox.run: starting cmd='%s' timeout=%ds",
            cmd_str[:120],
            timeout_seconds,
        )
        proc = subprocess.Popen(
            argv,
            cwd=workspace,
            env=self._env(workspace),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            preexec_fn=_limit_resources,  # noqa: PLW1509 - required for rlimits/setsid
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning(
                "LocalSandbox.run: cmd timed out after %ds, killing pid %d",
                timeout_seconds,
                proc.pid,
            )
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        duration = time.monotonic() - started
        exit_code = -9 if timed_out else proc.returncode
        logger.info(
            "LocalSandbox.run: completed exit_code=%d timed_out=%s in %.2fs",
            exit_code,
            timed_out,
            duration,
        )
        return CommandResult(
            command=cmd_str,
            exit_code=exit_code,
            stdout=(stdout or "")[:MAX_OUTPUT_CHARS],
            stderr=(stderr or "")[:MAX_OUTPUT_CHARS],
            duration_seconds=duration,
            timed_out=timed_out,
        )

    def destroy(self, workspace: Path) -> None:
        shutil.rmtree(workspace.parent, ignore_errors=True)

    def describe(self) -> SandboxInfo:
        notes = [
            "Process-level limits only: host filesystem is readable by target code.",
            "Environment variables (incl. API keys) are not inherited by target code.",
        ]
        if not self._net_blocked:
            notes.append("Network namespace unavailable: target code has network access.")
        return SandboxInfo(
            kind="local-process",
            isolation="process",
            network_blocked=self._net_blocked,
            isolation_self_tested=False,
            notes=notes,
        )
