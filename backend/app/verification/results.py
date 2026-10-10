"""Typed evidence primitives shared by the pipeline, verdict policy, API and UI."""

from enum import StrEnum

from pydantic import BaseModel, Field


class VerificationVerdict(StrEnum):
    VERIFIED = "verified"
    VERIFIED_WITH_CONDITIONS = "verified_with_conditions"
    NOT_VERIFIED = "not_verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CheckOutcome(StrEnum):
    PASSED = "passed"  # executed, and no counterexample was found
    FAILED = "failed"  # executed, and a concrete counterexample / failure was found
    ERROR = "error"  # tried to execute but could not produce a trustworthy result
    SKIPPED = "skipped"  # deliberately not run (e.g. an earlier blocking check failed)
    NOT_RUN = "not_run"  # never attempted


class CheckRole(StrEnum):
    # Establishes that the evidence itself is usable (e.g. the bug was reproduced).
    # Anything but PASSED means INSUFFICIENT_EVIDENCE, never NOT_VERIFIED.
    PRECONDITION = "precondition"
    # A failure here is a concrete reason to reject the patch.
    CORRECTNESS = "correctness"


class CheckResult(BaseModel):
    name: str
    role: CheckRole = CheckRole.CORRECTNESS
    required: bool = True
    outcome: CheckOutcome = CheckOutcome.NOT_RUN
    summary: str = ""
    command: str | None = None
    exit_code: int | None = None
    duration_seconds: float | None = None
    # Tests that actually ran (not skipped, not collection errors).
    tests_executed: int = 0
    counterexamples: list[str] = Field(default_factory=list)
    stdout_sha256: str | None = None
    output_excerpt: str = ""


class SandboxInfo(BaseModel):
    kind: str = "unknown"
    # "container": verified container isolation. "process": rlimits/env scrubbing only.
    isolation: str = "none"
    network_blocked: bool = False
    isolation_self_tested: bool = False
    notes: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    checks: list[CheckResult] = Field(default_factory=list)
    # Anything listed here downgrades VERIFIED to VERIFIED_WITH_CONDITIONS.
    limitations: list[str] = Field(default_factory=list)
    sandbox: SandboxInfo = Field(default_factory=SandboxInfo)
