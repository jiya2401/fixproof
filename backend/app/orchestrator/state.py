from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class InvestigationStage(StrEnum):
    CREATED = "created"
    REPRODUCING = "reproducing"
    INVESTIGATING = "investigating"
    FIXING = "fixing"
    PLANNING_VERIFICATION = "planning_verification"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationVerdict(StrEnum):
    VERIFIED = "verified"
    VERIFIED_WITH_CONDITIONS = "verified_with_conditions"
    NOT_VERIFIED = "not_verified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Hypothesis(BaseModel):
    title: str
    rationale: str
    status: str = "unproven"
    evidence: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    kind: str
    summary: str
    passed: bool | None = None
    command: str | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None


class InvestigationState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    repo_url: str
    issue: str
    stage: InvestigationStage = InvestigationStage.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    relevant_files: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    root_cause: str | None = None
    patch: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    repair_iteration: int = 0
    verdict: VerificationVerdict | None = None
    limitations: list[str] = Field(default_factory=list)
