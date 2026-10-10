import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from app.config import get_settings
from app.sandbox.base import CommandResult, SandboxRunner
from app.sandbox.local import _IGNORE, MAX_OUTPUT_CHARS
from app.verification.results import SandboxInfo


class DockerUnavailable(RuntimeError):
    pass


class DockerSandbox(SandboxRunner):
    """Container sandbox: no network, read-only root, non-root, dropped caps, cgroup limits.

    STATUS: implemented but NOT yet exercised in the development environment used to write
    it (no Docker daemon was available). describe().isolation_self_tested stays False until
    self_test() has passed on the machine running the pipeline, and the verdict policy
    requires that before it will award a plain VERIFIED.
    """

    def __init__(self, image: str | None = None) -> None:
        if not shutil.which("docker"):
            raise DockerUnavailable("docker CLI not found on PATH")
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False)
        if info.returncode != 0:
            raise DockerUnavailable("docker daemon is not reachable")
        self.image = image or get_settings().sandbox_image
        self._self_tested = False

    def docker_argv(self, workspace: Path, name: str, command: list[str]) -> list[str]:
        return [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,size=256m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--memory", "1g", "--cpus", "1",
            "--user", "65534:65534",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HOME=/tmp", "-e", "PYTHONPATH=/work",
            "-v", f"{workspace}:/work:rw", "-w", "/work",
            self.image, *command,
        ]  # fmt: skip

    def prepare_workspace(self, source: Path) -> Path:
        destination = Path(tempfile.mkdtemp(prefix="fixproof-docker-")) / "repo"
        shutil.copytree(source, destination, ignore=_IGNORE)
        for root, dirs, files in os.walk(destination):
            for entry in [*dirs, *files]:
                path = Path(root) / entry
                if not path.is_symlink():
                    path.chmod(0o777 if path.is_dir() else 0o666)
        destination.chmod(0o777)
        return destination

    def run(self, workspace: Path, command: list[str], timeout_seconds: int = 120) -> CommandResult:
        name = f"fixproof-{uuid.uuid4().hex[:12]}"
        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                self.docker_argv(workspace, name, command),
                capture_output=True, text=True, errors="replace",
                timeout=timeout_seconds, check=False,
            )  # fmt: skip
            code, out, err = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            subprocess.run(["docker", "kill", name], capture_output=True, check=False)
            code, out, err = -9, str(exc.stdout or ""), str(exc.stderr or "")
        return CommandResult(
            command=" ".join(command), exit_code=code,
            stdout=out[:MAX_OUTPUT_CHARS], stderr=err[:MAX_OUTPUT_CHARS],
            duration_seconds=time.monotonic() - started, timed_out=timed_out,
        )  # fmt: skip

    def destroy(self, workspace: Path) -> None:
        shutil.rmtree(workspace.parent, ignore_errors=True)

    def self_test(self) -> list[str]:
        """Probe the isolation claims on this machine. Returns failures (empty = passed)."""
        failures: list[str] = []
        ws = self.prepare_workspace(Path(tempfile.mkdtemp()))
        try:
            probes = {
                "network is blocked": ["python", "-c",
                    "import socket,sys\ntry:\n socket.create_connection(('1.1.1.1',53),2)\n"
                    "except OSError:\n sys.exit(0)\nsys.exit(1)"],
                "root filesystem is read-only": ["python", "-c",
                    "import sys\ntry:\n open('/etc/fixproof_probe','w')\nexcept OSError:\n"
                    " sys.exit(0)\nsys.exit(1)"],
                "process is not root": ["python", "-c",
                    "import os,sys;sys.exit(0 if os.getuid()!=0 else 1)"],
                "host env is not visible": ["python", "-c",
                    "import os,sys;sys.exit(1 if 'NEBIUS_API_KEY' in os.environ else 0)"],
            }  # fmt: skip
            for label, cmd in probes.items():
                if not self.run(ws, cmd, timeout_seconds=60).passed:
                    failures.append(label)
        finally:
            self.destroy(ws)
        self._self_tested = not failures
        return failures

    def describe(self) -> SandboxInfo:
        return SandboxInfo(
            kind="docker",
            isolation="container",
            network_blocked=True,
            isolation_self_tested=self._self_tested,
            notes=[f"image={self.image}"]
            + ([] if self._self_tested else ["self_test() has not passed on this host"]),
        )
