"""Evidence-driven repair pipeline.

Model calls (Nemotron): hypotheses, patch, adversarial test authoring.
Everything else is deterministic: snapshotting, applying patches, running pytest in the
sandbox, parsing results, deciding the verdict. The model never grades its own patch.
"""

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.agents.models import (
    AdversarialTest,
    InvestigationPlan,
    PatchProposal,
    VerificationPlan,
)
from app.certificate import (
    FixCertificate,
    HypothesisRecord,
    IterationRecord,
    ModelInfo,
    TimelineEvent,
)
from app.repair.patching import (
    apply_patch,
    is_protected_path,
    normalized_patch_hash,
    patch_violations,
    snapshot_hash,
    touched_paths,
)
from app.sandbox.base import SandboxRunner
from app.verification.grounding import build_spec_corpus, check_grounding
from app.verification.pytest_runner import run_pytest_check
from app.verification.results import (
    CheckOutcome,
    CheckResult,
    CheckRole,
    VerificationReport,
)
from app.verification.verdict import MANDATORY_CHECKS, evaluate_policy

MAX_CODE_CHARS = 30_000
ADV_DIR = "fixproof_adv"


class Fixer(Protocol):
    def propose(
        self, *, issue: str, evidence: str, relevant_code: str, feedback: str | None = None
    ) -> PatchProposal: ...


class Planner(Protocol):
    def plan(
        self,
        *,
        issue: str,
        patch_diff: str,
        reproduction_evidence: str,
        relevant_code: str,
        prior_counterexamples: list[str] | None = None,
    ) -> VerificationPlan: ...


class Investigator(Protocol):
    def plan(self, *, issue: str, evidence: str, relevant_code: str) -> InvestigationPlan: ...


def collect_code(workspace: Path, limit: int = MAX_CODE_CHARS) -> str:
    parts: list[str] = []
    used = 0
    for path in sorted(workspace.rglob("*.py")):
        rel = path.relative_to(workspace).as_posix()
        if rel.startswith((".", ADV_DIR)) or "/." in rel or is_protected_path(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunk = f"### {rel}\n{text}\n"
        if used + len(chunk) > limit:
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:40] or "case"


def _feedback(checks: list[CheckResult]) -> str:
    lines: list[str] = []
    for check in checks:
        if check.name not in MANDATORY_CHECKS or check.outcome in (
            CheckOutcome.PASSED,
            CheckOutcome.SKIPPED,
        ):
            continue  # unvalidated (ungrounded) findings are never fed back to the fixer
        lines.append(f"- check '{check.name}' {check.outcome.value}: {check.summary}")
        lines.extend(f"    counterexample: {c}" for c in check.counterexamples[:5])
        if check.output_excerpt and check.outcome == CheckOutcome.FAILED:
            lines.append("    output tail:\n" + check.output_excerpt[-1200:])
    return "\n".join(lines)


def _skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, outcome=CheckOutcome.SKIPPED, summary=reason)


class RepairPipeline:
    def __init__(
        self,
        *,
        sandbox: SandboxRunner,
        fixer: Fixer,
        planner: Planner | None,
        investigator: Investigator | None = None,
        max_iterations: int = 3,
        model_info: Callable[[], dict[str, Any]] | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.fixer = fixer
        self.planner = planner  # None => no adversarial phase (used for the baseline)
        self.investigator = investigator
        self.max_iterations = max(1, max_iterations)
        self._spec_corpus = ""
        self.model_info = model_info
        self.on_event = on_event

    def run(
        self,
        *,
        source: Path,
        issue: str,
        repro_targets: list[str],
        investigation_id: str | None = None,
        source_label: str = "",
    ) -> FixCertificate:
        cert = FixCertificate(
            investigation_id=investigation_id,
            source_label=source_label,
            snapshot_sha256=snapshot_hash(source),
            issue=issue,
            reproduction_targets=list(repro_targets),
            sandbox=self.sandbox.describe(),
            max_iterations=self.max_iterations,
        )

        def event(stage: str, message: str) -> None:
            cert.timeline.append(TimelineEvent(stage=stage, message=message))
            if self.on_event:
                self.on_event(stage, message)

        self._spec_corpus = build_spec_corpus(issue, source)
        event("snapshot", f"snapshot {cert.snapshot_sha256[:12]} of {source_label or source}")

        # 1. Reproduce the original failure (deterministic).
        event("reproducing", "running original reproduction before any patch")
        ws0 = self.sandbox.prepare_workspace(source)
        try:
            red = run_pytest_check(
                self.sandbox, ws0, name="reproduction_red", targets=repro_targets,
                role=CheckRole.PRECONDITION, expect_failure=True,
            )  # fmt: skip
            code0 = collect_code(ws0)
        finally:
            self.sandbox.destroy(ws0)
        event("reproducing", f"reproduction_red: {red.outcome.value} - {red.summary}")
        cert.checks = [red]
        if red.outcome != CheckOutcome.PASSED:
            cert.limitations.append("original failure was not reproduced; no model calls made")
            return self._finish(cert, [red])

        # 2. Hypotheses (model). Recorded, but not experimentally tested in this release.
        if self.investigator is not None:
            event("investigating", "asking Nemotron for root-cause hypotheses")
            try:
                plan = self.investigator.plan(
                    issue=issue, evidence=red.output_excerpt, relevant_code=code0
                )
                cert.hypotheses = [
                    HypothesisRecord(
                        title=h.title, rationale=h.rationale, suspect_files=h.suspect_files
                    )
                    for h in plan.hypotheses
                ]
                cert.selected_root_cause = plan.selected_root_cause
                cert.confidence_notes = plan.confidence_notes
            except Exception as exc:  # noqa: BLE001 - recorded, not fatal
                cert.limitations.append(f"investigation step failed: {exc}")

        # 3. Bounded repair loop. Fresh workspace per attempt; all mandatory checks re-run.
        adv_suite: dict[str, AdversarialTest] = {}
        seen_hashes: set[str] = set()
        feedback: str | None = None
        last_checks: list[CheckResult] = [red]
        last_good_iteration: IterationRecord | None = None

        for index in range(1, self.max_iterations + 1):
            record = IterationRecord(index=index, feedback_to_fixer=feedback)
            event("fixing", f"iteration {index}/{self.max_iterations}: asking Nemotron for a patch")
            try:
                proposal = self.fixer.propose(
                    issue=issue, evidence=red.output_excerpt, relevant_code=code0,
                    feedback=feedback,
                )  # fmt: skip
            except Exception as exc:  # noqa: BLE001
                record.note = f"model call failed: {exc}"
                cert.iterations.append(record)
                cert.limitations.append(f"iteration {index}: model call failed: {exc}")
                break
            record.summary, record.rationale, record.diff = (
                proposal.summary, proposal.rationale, proposal.diff,
            )  # fmt: skip
            record.patch_sha256 = normalized_patch_hash(proposal.diff)
            if record.patch_sha256 in seen_hashes:
                record.note = "repeated an earlier patch; stopping"
                cert.iterations.append(record)
                event("repairing", record.note)
                break
            seen_hashes.add(record.patch_sha256)

            checks = self._verify(
                source, proposal, repro_targets, red, adv_suite, issue, record, event
            )
            record.checks = checks
            record.counterexamples = [c for chk in checks for c in chk.counterexamples]
            cert.iterations.append(record)
            last_checks, last_good_iteration = [red, *checks], record

            blocking = [
                c
                for c in checks
                if c.name in MANDATORY_CHECKS
                and c.outcome != CheckOutcome.PASSED
                # Baseline mode (no planner) has no adversarial phase to wait for.
                and not (c.name == "adversarial" and self.planner is None)
            ]
            if not blocking:
                break
            feedback = _feedback(checks)
            event(
                "repairing", f"iteration {index} rejected: " + ", ".join(c.name for c in blocking)
            )

        if last_good_iteration is not None:
            cert.final_patch = last_good_iteration.diff
            cert.final_patch_sha256 = last_good_iteration.patch_sha256
            cert.changed_files = last_good_iteration.changed_files
            cert.patch_summary = last_good_iteration.summary
        return self._finish(cert, last_checks)

    def _verify(
        self,
        source: Path,
        proposal: PatchProposal,
        repro_targets: list[str],
        red: CheckResult,
        adv_suite: dict[str, AdversarialTest],
        issue: str,
        record: IterationRecord,
        event: Callable[[str, str], None],
    ) -> list[CheckResult]:
        ws = self.sandbox.prepare_workspace(source)
        try:
            problems = patch_violations(proposal.diff)
            applied = False
            if problems:
                scope = CheckResult(
                    name="patch_applies_in_scope", outcome=CheckOutcome.FAILED,
                    summary="; ".join(problems), counterexamples=problems,
                )  # fmt: skip
            else:
                applied, message = apply_patch(ws, proposal.diff)
                scope = CheckResult(
                    name="patch_applies_in_scope",
                    outcome=CheckOutcome.PASSED if applied else CheckOutcome.FAILED,
                    summary="patch applied" if applied else f"git apply failed: {message}",
                    counterexamples=[] if applied else [message],
                )  # fmt: skip
                if applied:
                    record.changed_files = touched_paths(proposal.diff)
            event("verifying", f"patch_applies_in_scope: {scope.outcome.value}")
            if not applied:
                reason = "patch did not apply in scope"
                return [
                    scope, _skipped("reproduction_green", reason),
                    _skipped("regression", reason), _skipped("adversarial", reason),
                ]  # fmt: skip

            green = run_pytest_check(
                self.sandbox, ws, name="reproduction_green", targets=repro_targets
            )
            event("verifying", f"reproduction_green: {green.outcome.value} - {green.summary}")
            regression = run_pytest_check(self.sandbox, ws, name="regression")
            event("verifying", f"regression: {regression.outcome.value} - {regression.summary}")

            if green.outcome != CheckOutcome.PASSED or regression.outcome != CheckOutcome.PASSED:
                adversarial = [_skipped("adversarial", "earlier blocking check did not pass")]
            else:
                adversarial = self._adversarial(ws, proposal, red, adv_suite, issue, event)
            return [scope, green, regression, *adversarial]
        finally:
            self.sandbox.destroy(ws)

    def _adversarial(
        self,
        ws: Path,
        proposal: PatchProposal,
        red: CheckResult,
        adv_suite: dict[str, AdversarialTest],
        issue: str,
        event: Callable[[str, str], None],
    ) -> list[CheckResult]:
        """Returns [adversarial] (spec-grounded, mandatory) plus optionally
        [adversarial_ungrounded] (unvalidated tests; a failure there is a condition, not a veto)."""
        if self.planner is None:
            return [_skipped("adversarial", "adversarial phase disabled")]
        event("planning_verification", "asking Nemotron to design adversarial tests")
        discarded: list[str] = []
        try:
            plan = self.planner.plan(
                issue=issue, patch_diff=proposal.diff, reproduction_evidence=red.output_excerpt,
                relevant_code=collect_code(ws),
                prior_counterexamples=[f"existing adversarial test: {name}" for name in adv_suite],
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            return [
                CheckResult(
                    name="adversarial",
                    outcome=CheckOutcome.ERROR,
                    summary=f"verification planner failed: {exc}",
                )  # fmt: skip
            ]
        for test in plan.tests:
            slug = _slug(test.name)
            try:
                ast.parse(test.code)
            except SyntaxError as exc:
                discarded.append(f"{slug}: not valid Python ({exc.msg})")
                continue
            key = slug
            while key in adv_suite and adv_suite[key].code != test.code:
                key += "_x"
            grounded, note = check_grounding(test.spec_quote, self._spec_corpus)
            adv_suite[key] = test.model_copy(update={"grounded": grounded, "grounding_note": note})
        if not adv_suite:
            return [
                CheckResult(
                    name="adversarial",
                    outcome=CheckOutcome.ERROR,
                    summary="no executable adversarial tests were produced; discarded: "
                    + ("; ".join(discarded) or "none proposed"),
                )  # fmt: skip
            ]
        adv_dir = ws / ADV_DIR
        adv_dir.mkdir(exist_ok=True)
        for key, test in adv_suite.items():
            (adv_dir / f"test_adv_{key}.py").write_text(test.code, encoding="utf-8")
        groups = {
            True: [k for k, t in adv_suite.items() if t.grounded],
            False: [k for k, t in adv_suite.items() if not t.grounded],
        }
        event(
            "verifying",
            f"executing {len(adv_suite)} adversarial test file(s): "
            f"{len(groups[True])} spec-grounded, {len(groups[False])} ungrounded",
        )

        def run_group(name: str, keys: list[str]) -> CheckResult:
            result = run_pytest_check(
                self.sandbox, ws, name=name, targets=["--continue-on-collection-errors"]
                + [f"{ADV_DIR}/test_adv_{k}.py" for k in keys],
            )  # fmt: skip
            tagged = []
            for counterexample in result.counterexamples:
                owner = next((k for k in keys if f"test_adv_{k}" in counterexample), None)
                quote = adv_suite[owner].spec_quote if owner else ""
                tagged.append(f'{counterexample} [SPEC: "{quote}"]' if quote else counterexample)
            result.counterexamples = tagged
            return result

        checks: list[CheckResult] = []
        if groups[True]:
            grounded_check = run_group("adversarial", groups[True])
        else:
            reasons = "; ".join(f"{k}: {t.grounding_note}" for k, t in adv_suite.items())
            grounded_check = CheckResult(
                name="adversarial", outcome=CheckOutcome.ERROR,
                summary=f"no spec-grounded adversarial test was produced ({reasons})",
            )  # fmt: skip
        if discarded:
            grounded_check.summary += f" [{len(discarded)} discarded: {'; '.join(discarded)}]"
        checks.append(grounded_check)
        event(
            "verifying", f"adversarial: {grounded_check.outcome.value} - {grounded_check.summary}"
        )
        if groups[False]:
            ungrounded = run_group("adversarial_ungrounded", groups[False])
            ungrounded.required = False
            ungrounded.summary += " (unvalidated model assumptions; human review, not a veto)"
            checks.append(ungrounded)
            event("verifying", f"adversarial_ungrounded: {ungrounded.outcome.value}")
        return checks

    def _finish(self, cert: FixCertificate, checks: list[CheckResult]) -> FixCertificate:
        cert.checks = checks
        info = self.model_info() if self.model_info else {}
        cert.model = ModelInfo(**info) if info else ModelInfo()
        report = VerificationReport(
            checks=checks, limitations=list(cert.limitations), sandbox=cert.sandbox
        )
        decision = evaluate_policy(report)
        cert.verdict, cert.verdict_reasons = decision.verdict, decision.reasons
        cert.policy_version = decision.policy_version
        if self.on_event:
            self.on_event("completed", f"verdict: {cert.verdict.value}")
        cert.timeline.append(TimelineEvent(stage="verdict", message=cert.verdict.value))
        return cert.seal()
