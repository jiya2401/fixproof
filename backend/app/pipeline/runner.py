"""Evidence-driven repair pipeline.

Model calls (Nemotron): hypotheses, patch, adversarial test authoring.
Everything else is deterministic: snapshotting, applying patches, running pytest in the
sandbox, parsing results, deciding the verdict. The model never grades its own patch.
"""

import ast
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.agents.models import (
    AdversarialTest,
    InvestigationPlan,
    PatchProposal,
    ReviewResult,
    VerificationPlan,
)
from app.certificate import (
    FixCertificate,
    HypothesisRecord,
    IterationRecord,
    ModelInfo,
    TimelineEvent,
)
from app.repair.edits import build_diff_from_edits
from app.repair.patching import (
    apply_patch,
    is_protected_path,
    normalized_patch_hash,
    patch_violations,
    snapshot_hash,
    touched_paths,
)
from app.sandbox.base import SandboxRunner
from app.security import SecurityScanResult, VulnerabilityFinding, run_security_scan
from app.verification.contest import find_contests
from app.verification.grounding import build_spec_corpus, check_grounding
from app.verification.pytest_runner import run_pytest_check
from app.verification.results import (
    CheckOutcome,
    CheckResult,
    CheckRole,
    VerificationReport,
)
from app.verification.suite import SuiteRun, compare, matches_target, parse_outcomes, run_suite
from app.verification.verdict import MANDATORY_CHECKS, evaluate_policy

MAX_CODE_CHARS = 40_000
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


class Reviewer(Protocol):
    def review(self, *, issue: str, patch_diff: str, relevant_code: str) -> ReviewResult: ...


class Investigator(Protocol):
    def plan(self, *, issue: str, evidence: str, relevant_code: str) -> InvestigationPlan: ...


_TRACE_PATH = re.compile(r"([A-Za-z0-9_./\\-]+\.py):\d+")


def collect_code(
    workspace: Path,
    limit: int = MAX_CODE_CHARS,
    focus_text: str = "",
    test_files: list[str] | None = None,
) -> str:
    """Repository context for the model. Failing tests come first (read-only context), then files
    named in the failure traceback, then everything else, until `limit` characters."""
    mentioned = {m.replace("\\", "/").lstrip("/") for m in _TRACE_PATH.findall(focus_text)}

    def relevance(rel: str) -> int:
        return 0 if any(rel.endswith(m.removeprefix("work/")) for m in mentioned) else 1

    chunks: list[tuple[int, str, str]] = []
    for name in test_files or []:
        path = workspace / name
        if path.is_file():
            body = path.read_text(encoding="utf-8", errors="replace")
            chunks.append(
                (-1, name, f"### {name}  (FAILING TEST - read-only context, do not edit)\n{body}\n")
            )
    for path in sorted(workspace.rglob("*.py")):
        rel = path.relative_to(workspace).as_posix()
        if rel.startswith((".", ADV_DIR)) or "/." in rel or is_protected_path(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks.append((relevance(rel), rel, f"### {rel}\n{text}\n"))
    chunks.sort(key=lambda c: (c[0], c[1]))
    parts: list[str] = []
    used = 0
    for _rank, _rel, chunk in chunks:
        if used + len(chunk) > limit:
            continue
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:40] or "case"


def _feedback(checks: list[CheckResult]) -> str:
    lines: list[str] = []
    for check in checks:
        if (
            check.name not in MANDATORY_CHECKS and check.name != "self_review"
        ) or check.outcome in (
            CheckOutcome.PASSED,
            CheckOutcome.SKIPPED,
        ):
            continue  # unvalidated (ungrounded) findings are never fed back to the fixer
        lines.append(f"- check '{check.name}' {check.outcome.value}: {check.summary}")
        lines.extend(f"    counterexample: {c}" for c in check.counterexamples[:5])
        if check.output_excerpt and check.outcome == CheckOutcome.FAILED:
            lines.append("    output tail:\n" + check.output_excerpt[-1200:])
    return "\n".join(lines)


def _results_by_key(outcomes: dict[str, str]) -> dict[str, str]:
    """Collapse per-test outcomes into one result per attack-test file key."""
    by_key: dict[str, list[str]] = {}
    for node, outcome in outcomes.items():
        match = re.search(r"test_adv_(.+?)\.py", node)
        if match:
            by_key.setdefault(match.group(1), []).append(outcome)
    result: dict[str, str] = {}
    for key, values in by_key.items():
        if "failed" in values:
            result[key] = "failed"
        elif "error" in values:
            result[key] = "error"
        elif "passed" in values:
            result[key] = "passed"
    return result


def _score(iteration: IterationRecord) -> int:
    """Lower is better. Counterexamples cost 1 each; other failures cost more; unrun checks most."""
    if not iteration.checks:
        return 10_000
    total = 0
    for check in iteration.checks:
        if check.name not in MANDATORY_CHECKS or check.outcome == CheckOutcome.PASSED:
            continue
        if check.name == "adversarial" and check.outcome == CheckOutcome.FAILED:
            total += max(1, len(check.counterexamples))
        elif check.outcome == CheckOutcome.FAILED:
            total += 100
        else:
            total += 1000
    return total


def _skipped(name: str, reason: str) -> CheckResult:
    return CheckResult(name=name, outcome=CheckOutcome.SKIPPED, summary=reason)


class _NoModel:
    """Placeholder agent for re-verification, which must never call a model."""

    def propose(self, **_kwargs: Any) -> PatchProposal:
        raise RuntimeError("re-verification makes no model calls")

    def plan(self, **_kwargs: Any) -> VerificationPlan:
        raise RuntimeError("re-verification makes no model calls")


def _scan_to_check(result: SecurityScanResult) -> CheckResult:
    """Convert a :class:`SecurityScanResult` into a pipeline :class:`CheckResult`."""
    if result.error:
        return CheckResult(
            name="security_sast",
            required=False,
            outcome=CheckOutcome.ERROR,
            summary=f"SAST scanner error (non-blocking): {result.error}",
        )
    new_count = len(result.new_vulnerabilities)
    if result.passed:
        summary = (
            f"Security SAST: no new HIGH/MEDIUM vulnerabilities introduced "
            f"({result.files_scanned} file(s) scanned, "
            f"{result.post_patch_count} pre-existing finding(s), "
            f"scan took {result.scan_duration_seconds:.2f}s)"
        )
        return CheckResult(
            name="security_sast",
            required=False,
            outcome=CheckOutcome.PASSED,
            summary=summary,
        )
    # Failed — new vulnerabilities introduced
    counterexamples = [
        f"[{v.severity}] {v.file}:{v.line_number} {v.rule_id}: {v.issue_description}"
        for v in result.new_vulnerabilities
    ]
    summary = (
        f"Security SAST: {new_count} NEW vulnerability(ies) introduced by the patch "
        f"({result.files_scanned} file(s) scanned). "
        f"Findings: {chr(10).join(counterexamples[:5])}"
    )
    return CheckResult(
        name="security_sast",
        required=False,
        outcome=CheckOutcome.FAILED,
        summary=summary,
        counterexamples=counterexamples,
    )


class RepairPipeline:
    def __init__(
        self,
        *,
        sandbox: SandboxRunner,
        fixer: Fixer,
        planner: Planner | None,
        investigator: Investigator | None = None,
        reviewer: Reviewer | None = None,
        max_iterations: int = 3,
        model_info: Callable[[], dict[str, Any]] | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.fixer = fixer
        self.planner = planner  # None => no adversarial phase (used for the baseline)
        self.investigator = investigator
        self.reviewer = reviewer  # comparison baseline only (LLM reviews LLM, nothing executed)
        self.max_iterations = max(1, max_iterations)
        self._spec_corpus = ""
        self._baseline: SuiteRun | None = None
        self._skip_planning = False
        self._test_files: list[str] = []
        self._focus_text = ""
        self._adv_suite: dict[str, AdversarialTest] = {}
        self.model_info = model_info
        self.on_event = on_event
        # Feature 4: iteration_index -> SecurityScanResult (avoids touching Pydantic model)
        self._sast_results: dict[int, SecurityScanResult] = {}

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

        self._sast_results = {}  # reset for each pipeline.run() call

        def event(stage: str, message: str) -> None:
            cert.timeline.append(TimelineEvent(stage=stage, message=message))
            if self.on_event:
                self.on_event(stage, message)

        self._spec_corpus = build_spec_corpus(issue, source)
        event("snapshot", f"snapshot {cert.snapshot_sha256[:12]} of {source_label or source}")

        # 1. Reproduce the original failure (deterministic) and take the full-suite baseline.
        red, code0 = self._reproduce(source, repro_targets, event)
        cert.checks = [red]
        if red.outcome != CheckOutcome.PASSED:
            cert.limitations.append("original failure was not reproduced; no model calls made")
            return self._finish(cert, [red])
        note = self._baseline_note(repro_targets)
        if note:
            cert.limitations.append(note)

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
        self._adv_suite = adv_suite
        seen_hashes: set[str] = set()
        feedback: str | None = None
        history: list[str] = []  # every counterexample seen so far
        repeat_streak = 0
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
            if proposal.edits:
                proposal.diff, proposal.edit_errors = build_diff_from_edits(source, proposal.edits)
            record.edits = list(proposal.edits)
            record.summary, record.rationale, record.diff = (
                proposal.summary, proposal.rationale, proposal.diff,
            )  # fmt: skip
            record.patch_sha256 = normalized_patch_hash(
                proposal.diff
                or json.dumps([e.model_dump() for e in proposal.edits], sort_keys=True)
            )
            if record.patch_sha256 in seen_hashes:
                repeat_streak += 1
                record.note = "repeated an earlier patch"
                cert.iterations.append(record)
                event("repairing", record.note)
                if repeat_streak >= 2:
                    record.note += "; stopping"
                    break
                feedback = (feedback or "") + (
                    "\nYour last patch was IDENTICAL to an earlier rejected attempt. "
                    "Do not resubmit it; change the approach so every counterexample passes."
                )
                continue
            repeat_streak = 0
            seen_hashes.add(record.patch_sha256)

            checks = self._verify(
                source, proposal, repro_targets, red, adv_suite, issue, record, event
            )
            record.checks = checks
            record.counterexamples = [c for chk in checks for c in chk.counterexamples]
            record.score = _score(record)
            cert.iterations.append(record)
            last_checks, last_good_iteration = [red, *checks], record
            if self.planner is not None and adv_suite and record.test_results:
                for earlier in cert.iterations[:-1]:
                    if earlier.diff and any(
                        c.name == "patch_applies_in_scope" and c.outcome == CheckOutcome.PASSED
                        for c in earlier.checks
                    ):
                        earlier.test_results.update(
                            self._cross_run(source, earlier.diff, adv_suite)
                        )
            contests = find_contests(
                {it.index: it.test_results for it in cert.iterations if it.test_results}
            )

            blocking = [
                c
                for c in checks
                if c.name in MANDATORY_CHECKS
                and c.outcome != CheckOutcome.PASSED
                # Baseline mode (no planner) has no adversarial phase to wait for.
                and not (c.name == "adversarial" and self.planner is None)
            ] + [c for c in checks if c.name == "self_review" and c.outcome == CheckOutcome.FAILED]
            if not blocking:
                break
            for counterexample in record.counterexamples:
                if counterexample not in history:
                    history.append(counterexample)
            feedback = _feedback(checks)
            if history:
                feedback += (
                    "\nAll counterexamples found so far (the next patch must satisfy every one):\n"
                    + "\n".join(f"- {c}" for c in history)
                )
            if contests:
                feedback += (
                    "\nWARNING - contradictory attack tests were detected across your attempts:\n"
                    + "\n".join(f"- {c.describe()}" for c in contests)
                    + "\nDo not trade one group of tests for the other. Follow the documented "
                    "contract; keep behaviour that tests you already satisfy depend on."
                )
                flagged = sorted(set().union(*[c.keys for c in contests]))
                event("repairing", f"contradictory attack tests detected: {flagged}")
            event(
                "repairing", f"iteration {index} rejected: " + ", ".join(c.name for c in blocking)
            )

        verified = [it for it in cert.iterations if it.checks]
        best = last_good_iteration
        if self.planner is not None and verified:
            best = min(verified, key=lambda it: (_score(it), -it.index))  # tie: later attempt
            last_checks = [red, *best.checks]
        all_contests = find_contests(
            {it.index: it.test_results for it in cert.iterations if it.test_results}
        )
        if all_contests:
            cert.contested = sorted(set().union(*[c.keys for c in all_contests]))
            cert.limitations.append(
                "Contradictory attack tests: "
                + " | ".join(c.describe() for c in all_contests)
                + " Use re-verify to exclude tests you judge to be wrong."
            )
        if best is not None:
            cert.selected_attempt = best.index
            if best is not last_good_iteration:
                cert.limitations.append(
                    f"Attempt {best.index} is reported instead of the last attempt "
                    f"({last_good_iteration.index if last_good_iteration else '?'}) because it "
                    "failed fewer executed checks."
                )
            if "planner failed" in best.note:
                cert.limitations.append(best.note)
            cert.final_patch = best.diff
            cert.final_patch_sha256 = best.patch_sha256
            cert.changed_files = best.changed_files
            cert.patch_summary = best.summary
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
            problems = proposal.edit_errors or patch_violations(proposal.diff)
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
            regression = self._regression(ws)
            event("verifying", f"regression: {regression.outcome.value} - {regression.summary}")

            if green.outcome != CheckOutcome.PASSED or regression.outcome != CheckOutcome.PASSED:
                adversarial = [_skipped("adversarial", "earlier blocking check did not pass")]
            else:
                adversarial = self._adversarial(ws, proposal, red, adv_suite, issue, event, record)
            if self.reviewer is not None and self.planner is None:
                if (
                    green.outcome == CheckOutcome.PASSED
                    and regression.outcome == CheckOutcome.PASSED
                ):
                    adversarial.append(self._review(ws, proposal, issue, event))
            # ---- Feature 4: Security SAST scan ----
            sast_result = run_security_scan(
                source=source,
                workspace=ws,
                changed_files=record.changed_files if record.changed_files else None,
            )
            sast_check = _scan_to_check(sast_result)
            # Store against iteration index so _finish() can look it up
            # without touching the sealed Pydantic IterationRecord model.
            self._sast_results[record.index] = sast_result
            return [scope, green, regression, *adversarial, sast_check]
        finally:
            self.sandbox.destroy(ws)

    def _reproduce(
        self, source: Path, repro_targets: list[str], event: Callable[[str, str], None]
    ) -> tuple[CheckResult, str]:
        event("reproducing", "running original reproduction before any patch")
        ws0 = self.sandbox.prepare_workspace(source)
        try:
            red = run_pytest_check(
                self.sandbox, ws0, name="reproduction_red", targets=repro_targets,
                role=CheckRole.PRECONDITION, expect_failure=True,
            )  # fmt: skip
            self._baseline = (
                run_suite(self.sandbox, ws0) if red.outcome == CheckOutcome.PASSED else None
            )
            self._test_files = [t.split("::", 1)[0] for t in repro_targets]
            self._focus_text = red.output_excerpt
            code = self._code(ws0)
        finally:
            self.sandbox.destroy(ws0)
        event("reproducing", f"reproduction_red: {red.outcome.value} - {red.summary}")
        return red, code

    def _baseline_note(self, repro_targets: list[str]) -> str | None:
        if self._baseline is None or not self._baseline.usable:
            return None
        other = [
            n for n, o in self._baseline.outcomes.items()
            if o in ("failed", "error") and not matches_target(n, repro_targets)
        ]  # fmt: skip
        if not other:
            return None
        return (
            f"{len(other)} other test(s) or collection error(s) were already failing before the "
            "patch and are excluded from the regression check, which compares against that "
            "pre-patch baseline."
        )

    def reverify(
        self,
        *,
        source: Path,
        issue: str,
        repro_targets: list[str],
        base: FixCertificate,
        attempt: int,
        disputed: list[str],
        reason: str,
        investigation_id: str | None = None,
        source_label: str = "",
    ) -> FixCertificate:
        """Re-run every mandatory check on one earlier attempt's patch, excluding attack tests a
        human reviewer judged wrong. No model calls. The exclusion is recorded as a condition."""
        iteration = next(it for it in base.iterations if it.index == attempt)
        cert = FixCertificate(
            investigation_id=investigation_id, source_label=source_label,
            snapshot_sha256=snapshot_hash(source), issue=issue,
            reproduction_targets=list(repro_targets), sandbox=self.sandbox.describe(),
            max_iterations=base.max_iterations, derived_from=base.certificate_sha256,
            reverified_attempt=attempt, hypotheses=list(base.hypotheses),
            selected_root_cause=base.selected_root_cause, confidence_notes=base.confidence_notes,
            iterations=[it.model_copy(deep=True) for it in base.iterations],
            timeline=list(base.timeline), contested=list(base.contested),
        )  # fmt: skip

        def event(stage: str, message: str) -> None:
            cert.timeline.append(TimelineEvent(stage=stage, message=message))
            if self.on_event:
                self.on_event(stage, message)

        event(
            "reverifying",
            f"re-verifying attempt {attempt} without {len(disputed)} disputed "
            "test(s); no model calls",
        )
        self._spec_corpus = build_spec_corpus(issue, source)
        red, _ = self._reproduce(source, repro_targets, event)
        cert.checks = [red]
        if red.outcome != CheckOutcome.PASSED:
            cert.limitations.append("original failure was not reproduced; nothing re-verified")
            return self._finish(cert, [red])

        suite: dict[str, AdversarialTest] = {}
        for test in base.adversarial_tests:
            key = test.key or _slug(test.name)
            hit = key in disputed
            suite[key] = test.model_copy(
                update={
                    "key": key,
                    "disputed": test.disputed or hit,
                    "dispute_reason": reason if hit else test.dispute_reason,
                }
            )
        self._adv_suite = suite
        record = IterationRecord(
            index=len(cert.iterations) + 1,
            summary=f"re-verification of attempt {attempt} (human review)",
            rationale=reason, diff=iteration.diff, edits=list(iteration.edits),
            patch_sha256=iteration.patch_sha256, changed_files=list(iteration.changed_files),
            note=f"{len(disputed)} attack test(s) excluded by a human reviewer",
        )  # fmt: skip
        proposal = PatchProposal(
            summary=record.summary, rationale=reason, diff=iteration.diff, edits=iteration.edits
        )
        checks = self._verify(source, proposal, repro_targets, red, suite, issue, record, event)
        record.checks = checks
        record.counterexamples = [c for chk in checks for c in chk.counterexamples]
        record.score = _score(record)
        cert.iterations.append(record)

        excluded = [t for t in suite.values() if t.disputed]
        cert.limitations.extend(lim for lim in base.limitations if lim.startswith("Human review:"))
        cert.limitations.append(
            "Human review: "
            + "; ".join(
                f'{t.key} (spec: "{t.spec_quote[:80]}")' for t in excluded if t.key in disputed
            )
            + f" excluded from the attack tests. Reviewer's reason: {reason} "
            "The verdict depends on that judgement."
        )
        note = self._baseline_note(repro_targets)
        if note:
            cert.limitations.append(note)
        cert.adversarial_tests = list(suite.values())
        cert.selected_attempt = record.index
        cert.final_patch, cert.final_patch_sha256 = record.diff, record.patch_sha256
        cert.changed_files, cert.patch_summary = record.changed_files, record.summary
        return self._finish(cert, [red, *checks])

    @classmethod
    def for_reverification(
        cls,
        sandbox: SandboxRunner,
        *,
        model_info: Callable[[], dict[str, Any]] | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> "RepairPipeline":
        pipeline = cls(
            sandbox=sandbox, fixer=_NoModel(), planner=_NoModel(), model_info=model_info,
            on_event=on_event, max_iterations=1,
        )  # fmt: skip
        pipeline._skip_planning = True
        return pipeline

    def _regression(self, ws: Path) -> CheckResult:
        """Full suite after the patch, judged against the pre-patch baseline."""
        baseline = self._baseline
        after = run_suite(self.sandbox, ws)
        check = CheckResult(
            name="regression", command=after.command, exit_code=after.exit_code,
            duration_seconds=after.duration_seconds, tests_executed=after.executed,
            stdout_sha256=after.stdout_sha256, output_excerpt=after.excerpt,
        )  # fmt: skip
        if baseline is None or not baseline.usable:
            check.outcome = CheckOutcome.ERROR
            check.summary = "no usable pre-patch baseline, so regressions cannot be judged"
        elif not after.usable:
            check.outcome = CheckOutcome.ERROR
            check.summary = (
                "post-patch suite run did not complete "
                f"(exit {after.exit_code}{', timed out' if after.timed_out else ''})"
            )
        else:
            diff = compare(baseline, after)
            if diff.regressions:
                check.outcome = CheckOutcome.FAILED
                check.summary = f"{len(diff.regressions)} previously passing test(s) no longer pass"
                check.counterexamples = [
                    f"previously passing test no longer passes: {n}" for n in diff.regressions[:20]
                ]
            else:
                check.outcome = CheckOutcome.PASSED
                check.summary = (
                    f"no previously passing test broke ({baseline.count('passed')} checked; "
                    f"{len(diff.still_failing)} pre-existing failure(s) unchanged; "
                    f"{len(diff.fixed)} newly passing)"
                )
        return check

    def _code(self, workspace: Path) -> str:
        return collect_code(workspace, focus_text=self._focus_text, test_files=self._test_files)

    def _review(
        self, ws: Path, proposal: PatchProposal, issue: str, event: Callable[[str, str], None]
    ) -> CheckResult:
        """Baseline-only: model self-review. An ERROR here counts as 'no objection'."""
        assert self.reviewer is not None
        event("reviewing", "asking Nemotron to review its own patch (baseline, nothing executed)")
        try:
            result = self.reviewer.review(
                issue=issue, patch_diff=proposal.diff, relevant_code=self._code(ws)
            )
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                name="self_review", required=False, outcome=CheckOutcome.ERROR,
                summary=f"review failed, treated as no objection: {exc}",
            )  # fmt: skip
        return CheckResult(
            name="self_review", required=False,
            outcome=CheckOutcome.PASSED if result.accept else CheckOutcome.FAILED,
            summary="reviewer accepted" if result.accept else "reviewer rejected",
            counterexamples=[] if result.accept else list(result.defects),
        )  # fmt: skip

    def _adversarial(
        self,
        ws: Path,
        proposal: PatchProposal,
        red: CheckResult,
        adv_suite: dict[str, AdversarialTest],
        issue: str,
        event: Callable[[str, str], None],
        record: IterationRecord,
    ) -> list[CheckResult]:
        """Returns [adversarial] (spec-grounded, mandatory) plus optionally
        [adversarial_ungrounded] (unvalidated tests; a failure there is a condition, not a veto)."""
        if self.planner is None:
            return [_skipped("adversarial", "adversarial phase disabled")]
        if self._skip_planning:  # re-verification: run the stored tests, ask no model
            return self._run_adv_suite(ws, adv_suite, event, record)
        event("planning_verification", "asking Nemotron to design adversarial tests")
        discarded: list[str] = []
        planner_error: str | None = None
        plan = None
        try:
            plan = self.planner.plan(
                issue=issue, patch_diff=proposal.diff, reproduction_evidence=red.output_excerpt,
                relevant_code=self._code(ws),
                prior_counterexamples=[f"existing adversarial test: {name}" for name in adv_suite],
            )  # fmt: skip
        except Exception as exc:  # noqa: BLE001
            planner_error = str(exc)
            event("planning_verification", f"planner failed: {planner_error[:200]}")
        for test in plan.tests if plan else []:
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
            adv_suite[key] = test.model_copy(
                update={"grounded": grounded, "grounding_note": note, "key": key}
            )
        if not adv_suite:
            why = (
                f"verification planner failed: {planner_error}"
                if planner_error
                else "no executable adversarial tests were produced; discarded: "
                + ("; ".join(discarded) or "none proposed")
            )
            return [CheckResult(name="adversarial", outcome=CheckOutcome.ERROR, summary=why)]
        return self._run_adv_suite(ws, adv_suite, event, record, planner_error, discarded)

    def _write_adv_suite(self, ws: Path, adv_suite: dict[str, AdversarialTest]) -> None:
        adv_dir = ws / ADV_DIR
        adv_dir.mkdir(exist_ok=True)
        for key, test in adv_suite.items():
            (adv_dir / f"test_adv_{key}.py").write_text(test.code, encoding="utf-8")

    def _run_adv_suite(
        self,
        ws: Path,
        adv_suite: dict[str, AdversarialTest],
        event: Callable[[str, str], None],
        record: IterationRecord,
        planner_error: str | None = None,
        discarded: list[str] | None = None,
    ) -> list[CheckResult]:
        discarded = discarded or []
        self._write_adv_suite(ws, adv_suite)
        groups = {
            True: [k for k, t in adv_suite.items() if t.grounded and not t.disputed],
            False: [k for k, t in adv_suite.items() if not t.grounded and not t.disputed],
        }
        event(
            "verifying",
            f"executing {sum(len(v) for v in groups.values())} adversarial test file(s): "
            f"{len(groups[True])} spec-grounded, {len(groups[False])} ungrounded",
        )

        def run_group(name: str, keys: list[str]) -> CheckResult:
            result = run_pytest_check(
                self.sandbox, ws, name=name, targets=["--continue-on-collection-errors"]
                + [f"{ADV_DIR}/test_adv_{k}.py" for k in keys],
            )  # fmt: skip
            record.test_results.update(
                _results_by_key(parse_outcomes(ws / f".fixproof_junit_{name}.xml"))
            )
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
            reasons = "; ".join(
                f"{k}: {t.grounding_note}" for k, t in adv_suite.items() if not t.disputed
            )
            grounded_check = CheckResult(
                name="adversarial", outcome=CheckOutcome.ERROR,
                summary=f"no spec-grounded adversarial test was produced ({reasons})",
            )  # fmt: skip
        if planner_error:
            record.note = (
                f"planner failed this iteration ({planner_error[:150]}); "
                f"patch checked only against {len(adv_suite)} earlier test(s)"
            )
            grounded_check.summary += f" [{record.note}]"
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

    def _cross_run(
        self, source: Path, diff: str, adv_suite: dict[str, AdversarialTest]
    ) -> dict[str, str]:
        """Run every attack test against another attempt's patch (no model calls)."""
        ws = self.sandbox.prepare_workspace(source)
        try:
            ok, _ = apply_patch(ws, diff)
            if not ok or not adv_suite:
                return {}
            self._write_adv_suite(ws, adv_suite)
            run_pytest_check(
                self.sandbox,
                ws,
                name="crossrun",
                targets=["--continue-on-collection-errors", ADV_DIR],
            )
            return _results_by_key(parse_outcomes(ws / ".fixproof_junit_crossrun.xml"))
        finally:
            self.sandbox.destroy(ws)

    def _finish(self, cert: FixCertificate, checks: list[CheckResult]) -> FixCertificate:
        cert.checks = checks
        cert.adversarial_tests = list(self._adv_suite.values())
        info = self.model_info() if self.model_info else {}
        cert.model = ModelInfo(**info) if info else ModelInfo()
        report = VerificationReport(
            checks=checks, limitations=list(cert.limitations), sandbox=cert.sandbox
        )
        decision = evaluate_policy(report)
        cert.verdict, cert.verdict_reasons = decision.verdict, decision.reasons
        cert.policy_version = decision.policy_version

        # ---- Feature 4: aggregate security findings onto the certificate ----
        all_new_vulns: list[VulnerabilityFinding] = []
        for it in cert.iterations:
            sast = self._sast_results.get(it.index)
            if sast is not None and not sast.passed:
                all_new_vulns.extend(sast.new_vulnerabilities)
        # De-duplicate by fingerprint, keeping first occurrence
        seen_fps: set[str] = set()
        deduped: list[VulnerabilityFinding] = []
        for v in all_new_vulns:
            fp = v.fingerprint()
            if fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(v)
        cert.vulnerabilities = deduped
        # The *selected* attempt's SAST result drives the top-level verdict seal
        selected_sast: SecurityScanResult | None = None
        if cert.selected_attempt is not None:
            selected_sast = self._sast_results.get(cert.selected_attempt)
        if selected_sast is None and cert.iterations:
            selected_sast = self._sast_results.get(cert.iterations[-1].index)
        if selected_sast is not None:
            cert.security_verified = selected_sast.passed
            cert.security_seal = (
                "Verified Secure"
                if selected_sast.passed
                else "SECURITY COMPROMISED"
            )

        # ---- Feature 3: Visual Explanations - generate "Why I Fixed It" before sealing ----
        if cert.final_patch:
            try:
                from app.explanation import generate_explanation

                # Collect the best traceback from the reproduction check
                repro_check = next(
                    (c for c in checks if c.name == "reproduction_red"), None
                )
                traceback_text = (
                    repro_check.output_excerpt if repro_check else ""
                ) or ""
                # Collect a snapshot of the pre-patch code (stored in focus text)
                buggy_code_snapshot = self._focus_text or ""
                llm_client = (
                    getattr(self, "_explanation_llm_client", None)
                )  # injectable for tests
                cert.explanation = generate_explanation(
                    buggy_code_snapshot,
                    traceback_text,
                    cert.final_patch,
                    llm_client=llm_client,
                )
            except Exception as _exc:  # noqa: BLE001 — never fatal
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "explanation hook failed: %s", _exc
                )

        if self.on_event:
            self.on_event("completed", f"verdict: {cert.verdict.value}")
        cert.timeline.append(TimelineEvent(stage="verdict", message=cert.verdict.value))
        return cert.seal()
