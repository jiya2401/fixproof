"""Typed, machine-readable Fix Certificate. Used unchanged by the API and the frontend."""

import hashlib
import json
from datetime import UTC, datetime

# ---- Feature 3: explanation model ----
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.models import AdversarialTest, FileEdit
from app.security import VulnerabilityFinding
from app.verification.results import (
    CheckOutcome,
    CheckResult,
    SandboxInfo,
    VerificationVerdict,
)
from app.verification.verdict import POLICY_VERSION

STANDING_DISCLAIMERS = [
    "Not a proof of correctness: no counterexample was found by the executed checks.",
    "Adversarial tests are model-authored; a failing one is a candidate counterexample "
    "that should be reviewed, and a passing one is only as strong as its assertions.",
    "Root-cause hypotheses are model-proposed and were not experimentally discriminated.",
]

TOOL_ATTRIBUTION = {
    "root_cause_hypotheses": "nemotron",
    "patch_proposal": "nemotron",
    "adversarial_test_authoring": "nemotron",
    "bug_reproduction": "deterministic (pytest in sandbox)",
    "patch_scope_and_apply": "deterministic (unidiff + git apply)",
    "regression": "deterministic (pytest in sandbox)",
    "adversarial_execution": "deterministic (pytest in sandbox)",
    "verdict": "deterministic (verdict policy)",
}


class TimelineEvent(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stage: str
    message: str


class HypothesisRecord(BaseModel):
    title: str
    rationale: str
    suspect_files: list[str] = Field(default_factory=list)
    status: str = "proposed_untested"
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class IterationRecord(BaseModel):
    index: int
    patch_sha256: str | None = None
    summary: str = ""
    rationale: str = ""
    diff: str = ""
    changed_files: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    counterexamples: list[str] = Field(default_factory=list)
    feedback_to_fixer: str | None = None
    note: str = ""
    edits: list[FileEdit] = Field(default_factory=list)
    # attack test key -> passed|failed|error for THIS attempt's patch (filled by cross-running)
    test_results: dict[str, str] = Field(default_factory=dict)
    score: int | None = None  # lower is better; used to pick the least-bad attempt


class ModelInfo(BaseModel):
    provider: str = "Nebius Token Factory"
    model: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    retries_for_malformed_output: int = 0


class FixCertificate(BaseModel):
    certificate_id: str = Field(default_factory=lambda: str(uuid4()))
    policy_version: str = POLICY_VERSION
    investigation_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    source_label: str = ""
    snapshot_sha256: str = ""
    issue: str = ""
    reproduction_targets: list[str] = Field(default_factory=list)
    language: str = "python"

    model: ModelInfo = Field(default_factory=ModelInfo)
    sandbox: SandboxInfo = Field(default_factory=SandboxInfo)
    tool_attribution: dict[str, str] = Field(default_factory=lambda: dict(TOOL_ATTRIBUTION))

    hypotheses: list[HypothesisRecord] = Field(default_factory=list)
    selected_root_cause: str = ""
    confidence_notes: str = ""

    final_patch: str | None = None
    final_patch_sha256: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    patch_summary: str = ""

    checks: list[CheckResult] = Field(default_factory=list)
    unexecuted_checks: list[str] = Field(default_factory=list)
    iterations: list[IterationRecord] = Field(default_factory=list)
    # Every model-authored test that was executed, with its spec quote, so passes can be audited.
    adversarial_tests: list[AdversarialTest] = Field(default_factory=list)
    max_iterations: int = 0
    selected_attempt: int | None = None  # the attempt whose patch and checks this verdict is about
    contested: list[str] = Field(default_factory=list)  # attack tests that contradict each other
    derived_from: str | None = None  # certificate hash this one re-verifies
    reverified_attempt: int | None = None

    limitations: list[str] = Field(default_factory=list)

    # ---- Security SAST scan results (Feature 4) ----
    vulnerabilities: list[VulnerabilityFinding] = Field(
        default_factory=list,
        description="New HIGH/MEDIUM security findings introduced by the patch.",
    )
    security_verified: bool | None = Field(
        default=None,
        description="None=scan not run; True=clean; False=new vulnerabilities found.",
    )
    security_seal: str | None = Field(
        default=None,
        description="Human-readable security verdict seal.",
    )

    # ---- Feature 3: Visual Explanations ----
    explanation: Any | None = Field(
        default=None,
        description="Structured dashboard explanation of the root cause and fix.",
    )

    disclaimers: list[str] = Field(default_factory=lambda: list(STANDING_DISCLAIMERS))
    verdict: VerificationVerdict = VerificationVerdict.INSUFFICIENT_EVIDENCE
    verdict_reasons: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    certificate_sha256: str = ""

    def seal(self) -> "FixCertificate":
        """Fill derived fields and set a content hash over everything except the hash."""
        self.unexecuted_checks = [
            c.name
            for c in self.checks
            if c.outcome not in (CheckOutcome.PASSED, CheckOutcome.FAILED)
        ]
        payload = self.model_dump(mode="json", exclude={"certificate_sha256"})
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        self.certificate_sha256 = hashlib.sha256(blob).hexdigest()
        return self

    def hash_is_valid(self) -> bool:
        stored = self.certificate_sha256
        return stored == self.model_copy(deep=True).seal().certificate_sha256
