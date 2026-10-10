"""Test doubles. They script *model* behavior only; sandbox, patching, pytest and the
verdict policy used with them are the real implementations."""

from app.agents.models import (
    AdversarialTest,
    InvestigationPlan,
    PatchProposal,
    VerificationPlan,
)


class ScriptedFixer:
    def __init__(self, diffs: list[str]) -> None:
        self.diffs = diffs
        self.calls: list[str | None] = []

    def propose(self, *, issue, evidence, relevant_code, feedback=None) -> PatchProposal:
        self.calls.append(feedback)
        diff = self.diffs[min(len(self.calls) - 1, len(self.diffs) - 1)]
        return PatchProposal(summary=f"attempt {len(self.calls)}", rationale="scripted", diff=diff)


class ScriptedPlanner:
    def __init__(self, tests: list[AdversarialTest]) -> None:
        self.tests = tests
        self.calls = 0

    def plan(self, **_kwargs) -> VerificationPlan:
        self.calls += 1
        return VerificationPlan(tests=self.tests, invariants=["scripted"], risk_areas=[])


class ScriptedInvestigator:
    def plan(self, **_kwargs) -> InvestigationPlan:
        return InvestigationPlan(selected_root_cause="scripted", hypotheses=[])


AUTH_ADVERSARIAL = AdversarialTest(
    name="unknown_token_type",
    rationale="only refresh tokens may be accepted",
    code=(
        "from auth import validate_refresh_token\n\n"
        "def test_unknown_type_rejected():\n"
        "    assert validate_refresh_token('other:abc123') is False\n"
    ),
)

PAGINATE_ADVERSARIAL = AdversarialTest(
    name="invalid_args",
    rationale="docstring contract: ValueError for page<1 / per_page<1",
    code=(
        "import pytest\nfrom paginate import paginate\n\n"
        "def test_page_zero_raises():\n"
        "    with pytest.raises(ValueError):\n        paginate([1, 2, 3], 0, 2)\n"
    ),
)
