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


class FileEdit(BaseModel):
    path: str
    search: str  # must match the current file text exactly, and exactly once
    replace: str


class PatchProposal(BaseModel):
    summary: str
    rationale: str
    diff: str = ""  # produced by code from `edits`, or supplied directly (legacy diff reply)
    edits: list[FileEdit] = Field(default_factory=list)
    edit_errors: list[str] = Field(default_factory=list)


class AdversarialTest(BaseModel):
    name: str  # short identifier; used for the generated file name
    rationale: str  # what behavior this test attacks
    code: str  # complete pytest module source
    spec_quote: str = ""  # verbatim sentence from the issue/docstrings this test enforces
    grounded: bool = False  # set by the pipeline, never by the model
    grounding_note: str = ""
    key: str = ""  # stable id used for the generated test file; set by the pipeline
    disputed: bool = False  # excluded by a human reviewer (never by the model)
    dispute_reason: str = ""


class VerificationPlan(BaseModel):
    """Model-authored attack plan. Only `tests` are executed; prose is documentation.

    Model-suggested shell commands are deliberately not part of this schema: the pipeline
    never executes commands chosen by the model.
    """

    tests: list[AdversarialTest] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    risk_areas: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    accept: bool
    defects: list[str] = Field(default_factory=list)
