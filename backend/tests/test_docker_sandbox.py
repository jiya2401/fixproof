"""DockerSandbox could not be executed where this was written (no Docker daemon).
These tests only check the constructed command line, NOT real isolation."""

from pathlib import Path

from app.sandbox.docker import DockerSandbox


def test_docker_argv_contains_isolation_flags() -> None:
    sandbox = DockerSandbox.__new__(DockerSandbox)
    sandbox.image = "fixproof-sandbox:latest"
    argv = sandbox.docker_argv(Path("/tmp/ws"), "n", ["python", "-m", "pytest"])
    joined = " ".join(argv)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--pids-limit",
        "--memory",
        "no-new-privileges",
        "--user 65534:65534",
    ):
        assert flag in joined
    assert "NEBIUS" not in joined and "-v /tmp/ws:/work:rw" in joined
    assert "docker.sock" not in joined
