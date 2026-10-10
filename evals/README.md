# Evaluations

Compares, on identical cases with the same model and attempt budget:

- **Baseline** — Nemotron patch → visible reproduction + existing regression suite (accept if both pass).
- **FixProof** — same, plus model-authored adversarial tests, counterexample feedback, verdict policy.

Ground truth is a held-out oracle per case (`evals/cases/*/oracle`) that neither system sees.

```bash
python evals/benchmark.py --validate-cases       # checks the cases themselves (no model)
python evals/benchmark.py --trials 3 --attempts 3 --out evals/results/run1.json
```

Metrics per mode: resolved rate (accepted ∧ oracle-correct), false-acceptance rate among accepted,
**false-rejection rate** (rejected although the patch satisfied the oracle), visible-regression rate,
iterations, runtime, tokens, errors. The report records model id, sandbox description and case snapshot hashes.

Status: harness and 2 cases are validated by `backend/tests/test_eval_cases.py` (buggy fails; reference fix
passes oracle; a plausible weak fix passes visible tests but fails oracle). **No model run has been
performed, so there are no results.** Two cases are far too few to claim superiority; expand before drawing
conclusions, and include cases where FixProof may lose. LLM output is stochastic: report rates over n trials.
