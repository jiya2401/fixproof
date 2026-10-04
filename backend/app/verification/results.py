from pydantic import BaseModel, Field


class CheckResult(BaseModel):
    name: str
    required: bool = True
    executed: bool = True
    passed: bool = False
    summary: str = ""
    details: dict[str, object] = Field(default_factory=dict)


class VerificationReport(BaseModel):
    checks: list[CheckResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
