"""Benchmark library: same cases, same model, comparable budgets; ground truth from a
held-out oracle the pipeline never sees. Results are only ever produced by real runs."""

import json
import platform
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.pipeline.runner import RepairPipeline
from app.repair.patching import apply_patch, snapshot_hash
from app.sandbox.base import SandboxRunner
from app.verification.pytest_runner import run_pytest_check
from app.verification.results import CheckOutcome, VerificationVerdict

REPO_ROOT = Path(__file__).resolve().parents[2]


class EvalCase(BaseModel):
    name: str
    source: str
    issue: str
    repro_targets: list[str]
    oracle_dir: str

    @property
    def source_path(self) -> Path:
        return REPO_ROOT / self.source

    @property
    def oracle_path(self) -> Path:
        return REPO_ROOT / self.oracle_dir


class TrialResult(BaseModel):
    case: str
    mode: str
    trial: int
    accepted: bool
    oracle_passed: bool | None
    resolved: bool = False
    false_accept: bool = False
    false_reject: bool = False  # not accepted although the final patch satisfies the oracle
    visible_regression_failed: bool = False
    counterexamples_found: int = 0
    iterations: int = 0
    runtime_seconds: float = 0.0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    verdict: str = ""
    patch_sha256: str | None = None
    error: str | None = None


class BenchmarkReport(BaseModel):
    environment: dict[str, Any] = Field(default_factory=dict)
    trials: list[TrialResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def load_cases(cases_dir: Path | None = None) -> list[EvalCase]:
    root = cases_dir or REPO_ROOT / "evals" / "cases"
    return [
        EvalCase.model_validate_json((p / "case.json").read_text())
        for p in sorted(root.iterdir())
        if (p / "case.json").exists()
    ]


def oracle_passes(sandbox: SandboxRunner, case: EvalCase, diff: str | None) -> bool:
    """Apply `diff` to a fresh copy of the buggy source and run the hidden oracle tests."""
    ws = sandbox.prepare_workspace(case.source_path)
    try:
        if diff:
            ok, _ = apply_patch(ws, diff)
            if not ok:
                return False
        for f in case.oracle_path.glob("test_*.py"):
            shutil.copy(f, ws / f.name)
        oracle_files = [f.name for f in case.oracle_path.glob("test_*.py")]
        result = run_pytest_check(sandbox, ws, name="oracle", targets=oracle_files)
        return result.outcome == CheckOutcome.PASSED
    finally:
        sandbox.destroy(ws)


def score_trial(
    sandbox: SandboxRunner, case: EvalCase, mode: str, trial: int, pipeline: RepairPipeline,
    usage: Any = None,
) -> TrialResult:  # fmt: skip
    started = time.monotonic()
    before = usage.model_dump() if usage else {}
    try:
        cert = pipeline.run(
            source=case.source_path, issue=case.issue, repro_targets=case.repro_targets,
            source_label=case.name,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - failures are results too
        return TrialResult(
            case=case.name, mode=mode, trial=trial, accepted=False, oracle_passed=None,
            runtime_seconds=time.monotonic() - started, error=f"{type(exc).__name__}: {exc}",
        )  # fmt: skip
    final = {c.name: c for c in cert.checks}
    last = cert.iterations[-1].checks if cert.iterations else []
    last_by = {c.name: c for c in last}
    if mode == "baseline":
        accepted = bool(
            cert.final_patch
            and last_by.get("reproduction_green")
            and last_by["reproduction_green"].outcome == CheckOutcome.PASSED
            and last_by.get("regression")
            and last_by["regression"].outcome == CheckOutcome.PASSED
        )
    else:
        accepted = cert.verdict in (
            VerificationVerdict.VERIFIED, VerificationVerdict.VERIFIED_WITH_CONDITIONS,
        )  # fmt: skip
    oracle = oracle_passes(sandbox, case, cert.final_patch) if cert.final_patch else False
    after = usage.model_dump() if usage else {}
    reg = last_by.get("regression")
    return TrialResult(
        case=case.name, mode=mode, trial=trial, accepted=accepted, oracle_passed=oracle,
        resolved=accepted and oracle, false_accept=accepted and not oracle,
        false_reject=(not accepted) and oracle,
        visible_regression_failed=bool(reg and reg.outcome == CheckOutcome.FAILED),
        counterexamples_found=sum(len(i.counterexamples) for i in cert.iterations),
        iterations=len(cert.iterations), runtime_seconds=round(time.monotonic() - started, 2),
        model_calls=after.get("calls", 0) - before.get("calls", 0),
        prompt_tokens=after.get("prompt_tokens", 0) - before.get("prompt_tokens", 0),
        completion_tokens=after.get("completion_tokens", 0) - before.get("completion_tokens", 0),
        verdict=cert.verdict.value, patch_sha256=cert.final_patch_sha256,
        error=None if "reproduction_red" in final else "no reproduction",
    )  # fmt: skip


def environment_record(model: str, sandbox: SandboxRunner, cases: list[EvalCase]) -> dict[str, Any]:
    return {
        "model": model,
        "provider": "Nebius Token Factory",
        "sandbox": sandbox.describe().model_dump(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "case_snapshots": {c.name: snapshot_hash(c.source_path) for c in cases},
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def summarize(report: BenchmarkReport) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for mode in sorted({t.mode for t in report.trials}):
        rows = [t for t in report.trials if t.mode == mode]
        n = len(rows)
        accepted = [t for t in rows if t.accepted]
        out[mode] = {
            "trials": n,
            "resolved_rate": sum(t.resolved for t in rows) / n,
            "false_acceptance_rate_of_accepted": (
                sum(t.false_accept for t in accepted) / len(accepted) if accepted else None
            ),
            "false_rejection_rate": sum(t.false_reject for t in rows) / n,
            "visible_regression_rate": sum(t.visible_regression_failed for t in rows) / n,
            "mean_iterations": sum(t.iterations for t in rows) / n,
            "mean_runtime_seconds": sum(t.runtime_seconds for t in rows) / n,
            "total_tokens": sum(t.prompt_tokens + t.completion_tokens for t in rows),
            "errors": sum(t.error is not None for t in rows),
        }
    return out


def write_report(report: BenchmarkReport, path: Path) -> None:
    payload = report.model_dump(mode="json") | {"summary": summarize(report)}
    path.write_text(json.dumps(payload, indent=2))
