from pydantic import BaseModel, Field


class HypothesisProposal(BaseModel):
    title: str
    rationale: str
    suspect_files: list[str] = Field(default_factory=list)


class InvestigationPlan(BaseModel):
    relevant_files: list[str] = Field(default_factory=list)
    hypotheses: list[HypothesisProposal] = Field(default_factory=list)
    selected_root_cause: str = ""
    confidence_notes: str = ""


class PatchProposal(BaseModel):
    summary: str
    rationale: str
    diff: str


class AdversarialTest(BaseModel):
    name: str  # short identifier; used for the generated file name
    rationale: str  # what behavior this test attacks
    code: str  # complete pytest module source


class VerificationPlan(BaseModel):
    """Model-authored attack plan. Only `tests` are executed; prose is documentation.

    Model-suggested shell commands are deliberately not part of this schema: the pipeline
    never executes commands chosen by the model.
    """

    tests: list[AdversarialTest] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)
