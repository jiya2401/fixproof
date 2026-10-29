from app.config import get_settings
from app.sandbox.base import SandboxRunner


class SandboxUnavailable(RuntimeError):
    pass


def get_sandbox() -> SandboxRunner:
    """Instantiate the configured sandbox runner based on FIXPROOF_SANDBOX_MODE.

    Supported modes:
    - 'local':  Process sandbox with rlimits (used for Render deployment and local dev).
                Requires FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true.
    - 'docker': Docker container sandbox (requires Docker CLI and running Docker daemon).
    - 'bwrap':  bubblewrap Linux user-namespace sandbox (requires Linux host supporting user namespaces).

    There is NO silent fallback between modes: untrusted code will never run without
    the configured security boundary.
    """
    mode = get_settings().sandbox_mode.strip().lower()

    if mode == "local":
        from app.sandbox.local import LocalSandbox, UnsafeLocalExecutionDisabled

        try:
            return LocalSandbox()
        except UnsafeLocalExecutionDisabled as exc:
            raise SandboxUnavailable(str(exc)) from exc

    if mode == "docker":
        from app.sandbox.docker import DockerSandbox, DockerUnavailable

        try:
            sandbox = DockerSandbox()
        except DockerUnavailable as exc:
            raise SandboxUnavailable(
                f"Docker sandbox unavailable: {exc}. "
                "For cloud deployments like Render, set FIXPROOF_SANDBOX_MODE=local "
                "with FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true."
            ) from exc

        failures = sandbox.self_test()
        if failures:
            raise SandboxUnavailable(
                f"Docker sandbox self-test failed ({', '.join(failures)}). "
                "Run the server-side diagnostic in docs/audit.md or check `docker run` manually."
            )
        return sandbox

    if mode == "bwrap":
        from app.sandbox.bwrap import BwrapSandbox, BwrapUnavailable

        try:
            sandbox = BwrapSandbox()
        except BwrapUnavailable as exc:
            raise SandboxUnavailable(
                f"bubblewrap sandbox unavailable: {exc}. "
                "For cloud platforms that block user namespaces, set FIXPROOF_SANDBOX_MODE=local."
            ) from exc

        failures = sandbox.self_test()
        if failures:
            raise SandboxUnavailable(
                f"bubblewrap sandbox self-test failed ({', '.join(failures)}). "
                "Ensure the host kernel supports unprivileged user namespaces."
            )
        return sandbox

    raise SandboxUnavailable(
        f"Unsupported FIXPROOF_SANDBOX_MODE '{mode}'. Supported modes: 'local', 'docker', 'bwrap'."
    )
