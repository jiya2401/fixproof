from pydantic import BaseModel, Field


class InvestigationPlan(BaseModel):
    relevant_files: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)


class PatchProposal(BaseModel):
    summary: str
    rationale: str
    diff: str


class VerificationPlan(BaseModel):
    adversarial_scenarios: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    regression_targets: list[str] = Field(default_factory=list)
    suggested_commands: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)
