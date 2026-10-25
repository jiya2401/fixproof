# Evaluations

Compares, on identical cases with the same model and attempt budget:

- **baseline** — Nemotron patch → visible reproduction + existing regression suite (accept if both pass).
- **review** — baseline, plus the same model reviews its own patch (reading only, nothing executed)
  and retries on REJECT. This is the "LLM reviews LLM" comparator FixProof's thesis argues against.
- **fixproof** — baseline, plus spec-grounded adversarial tests executed in the sandbox, counterexample
  feedback and the verdict policy.

Token budgets are **not** matched: report tokens and runtime next to every rate.

Ground truth is a held-out oracle per case (`evals/cases/*/oracle`) that neither system sees.

```bash
python evals/benchmark.py --validate-cases       # checks the cases themselves (no model)
python evals/benchmark.py --trials 3 --attempts 3 --out evals/results/run1.json
python evals/benchmark.py --modes review fixproof --cases dedupe truncate   # subset
```

Metrics per mode: resolved rate (accepted ∧ oracle-correct), false-acceptance rate among accepted,
**false-rejection rate** (rejected although the patch satisfied the oracle), visible-regression rate,
iterations, runtime, tokens, errors. The report records model id, sandbox description and case snapshot hashes.

Cases (7): auth-refresh-token, paginate, slugify, dedupe, intervals, parse_bool, truncate. Each has visible
tests that a minimal fix passes, a documented contract the visible tests miss, a held-out oracle, a reference
fix and a plausible weak fix (all validated, see tests below).

Status: harness and 7 cases are validated by `backend/tests/test_eval_cases.py` (buggy fails; reference fix
passes oracle; a plausible weak fix passes visible tests but fails oracle). **No model run has been
performed, so there are no results.** Two cases are far too few to claim superiority; expand before drawing
conclusions, and include cases where FixProof may lose. LLM output is stochastic: report rates over n trials.
