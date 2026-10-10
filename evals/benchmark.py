"""Baseline vs FixProof benchmark. Requires a real NEBIUS_API_KEY and a sandbox.

    python evals/benchmark.py --validate-cases      # no model needed
    python evals/benchmark.py --trials 3 --out evals/results/run1.json

Baseline : Nemotron patch -> visible repro + existing regression suite, N attempts.
FixProof : same model/cases/attempt budget, plus adversarial tests + counterexample feedback.
Ground truth: held-out oracle tests (evals/cases/*/oracle) never shown to either system.
No results are bundled; every number must come from a run of this script.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.fixer import FixAgent  # noqa: E402
from app.agents.investigator import InvestigatorAgent  # noqa: E402
from app.agents.verifier import VerificationPlannerAgent  # noqa: E402
from app.evaluation import (  # noqa: E402
    BenchmarkReport,
    environment_record,
    load_cases,
    oracle_passes,
    score_trial,
    summarize,
    write_report,
)
from app.llm.nebius import NebiusClient  # noqa: E402
from app.pipeline.runner import RepairPipeline  # noqa: E402
from app.sandbox.factory import get_sandbox  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--attempts", type=int, default=3, help="max patch attempts per system")
    parser.add_argument("--out", type=Path, default=Path("evals/results/latest.json"))
    parser.add_argument("--validate-cases", action="store_true")
    args = parser.parse_args()

    sandbox = get_sandbox()
    cases = load_cases()
    if args.validate_cases:
        for case in cases:
            clean = oracle_passes(sandbox, case, None)
            print(f"{case.name}: buggy source passes oracle = {clean} (must be False)")
        return 0

    client = NebiusClient()
    report = BenchmarkReport(
        environment=environment_record(client.model, sandbox, cases)
        | {"attempt_budget": args.attempts, "trials_per_case": args.trials},
        notes=["LLM sampling is stochastic; read results as rates over n trials, not proofs."],
    )
    for case in cases:
        for trial in range(1, args.trials + 1):
            for mode in ("baseline", "fixproof"):
                pipeline = RepairPipeline(
                    sandbox=sandbox,
                    fixer=FixAgent(client),
                    planner=VerificationPlannerAgent(client) if mode == "fixproof" else None,
                    investigator=InvestigatorAgent(client) if mode == "fixproof" else None,
                    max_iterations=args.attempts,
                    model_info=lambda: client.usage.model_dump(),
                )
                result = score_trial(sandbox, case, mode, trial, pipeline, client.usage)
                report.trials.append(result)
                print(f"{case.name} t{trial} {mode}: accepted={result.accepted} "
                      f"oracle={result.oracle_passed} err={result.error}")  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_report(report, args.out)
    print(summarize(report))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
