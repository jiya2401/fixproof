from app.config import get_settings
from app.sandbox.base import SandboxRunner


class SandboxUnavailable(RuntimeError):
    pass


def get_sandbox() -> SandboxRunner:
    mode = get_settings().sandbox_mode
    if mode == "docker":
        from app.sandbox.docker import DockerSandbox, DockerUnavailable

        try:
            sandbox = DockerSandbox()
        except DockerUnavailable as exc:
            raise SandboxUnavailable(f"Docker sandbox unavailable: {exc}") from exc
        sandbox.self_test()
        return sandbox
    if mode == "local":
        from app.sandbox.local import LocalSandbox, UnsafeLocalExecutionDisabled

        try:
            return LocalSandbox()
        except UnsafeLocalExecutionDisabled as exc:
            raise SandboxUnavailable(str(exc)) from exc
    raise SandboxUnavailable(f"Unsupported FIXPROOF_SANDBOX_MODE '{mode}'")
