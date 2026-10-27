from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.certificate import FixCertificate, TimelineEvent
from app.verification.results import VerificationVerdict


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
    repo_url: str = ""
    issue: str
    stage: InvestigationStage = InvestigationStage.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    relevant_files: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    root_cause: str | None = None
    patch: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    repair_iteration: int = 0
    verdict: VerificationVerdict | None = None
    limitations: list[str] = Field(default_factory=list)
    example_case: str | None = None
    project_id: str | None = None
    parent_id: str | None = None  # set when this run re-verifies another investigation
    project_name: str | None = None
    events: list[TimelineEvent] = Field(default_factory=list)
    repro_targets: list[str] = Field(default_factory=list)
    certificate: FixCertificate | None = None
    error: str | None = None
