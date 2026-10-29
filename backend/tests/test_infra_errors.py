from pathlib import Path

import pytest

from app.sandbox.base import CommandResult
from app.sandbox.factory import SandboxUnavailable, get_sandbox
from app.verification.pytest_runner import run_pytest_check
from app.verification.results import CheckOutcome


class BrokenDockerSandbox:
    def run(self, workspace, command, timeout_seconds=120):
        return CommandResult(
            " ".join(command),
            125,
            "",
            "docker: Error response from daemon: pull access denied",
            0.1,
        )


def test_docker_run_failure_is_reported_as_infrastructure_with_message(tmp_path: Path) -> None:
    check = run_pytest_check(BrokenDockerSandbox(), tmp_path, name="reproduction_red")  # type: ignore[arg-type]
    assert check.outcome == CheckOutcome.ERROR
    assert "infrastructure" in check.summary and "pull access denied" in check.summary


def test_failed_self_test_refuses_to_start(monkeypatch) -> None:
    import app.sandbox.docker as docker_mod
    from app.config import get_settings

    class Fake:
        def __init__(self) -> None: ...
        def self_test(self) -> list[str]:
            return ["network is blocked"]

    monkeypatch.setattr(docker_mod, "DockerSandbox", Fake)
    monkeypatch.setattr(get_settings(), "sandbox_mode", "docker")
    with pytest.raises(SandboxUnavailable, match="self-test failed"):
        get_sandbox()
