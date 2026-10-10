# Verification Policy v1.0

Implemented in `backend/app/verification/verdict.py` and tested in
`backend/tests/test_verdict.py`. An LLM statement is never evidence. A verdict is computed
only from executed checks.

## Check outcomes

| Outcome | Meaning |
|---|---|
| `passed` | Executed; no counterexample found (bug-reproduction: the failure *was* reproduced) |
| `failed` | Executed; a concrete failing test / counterexample exists |
| `error` | Tried to run but produced no trustworthy result (collection error, timeout, no tests, planner failure) |
| `skipped` / `not_run` | Not executed |

A check that "passes" while executing **zero** tests is treated as `not_run`.
Tests skipped inside pytest are not counted as executed.
A **counterexample** (`failed`) is distinct from an **execution failure** (`error`).

## Mandatory checks

`reproduction_red` (precondition) · `patch_applies_in_scope` · `reproduction_green` ·
`regression` · `adversarial`.

- `reproduction_red`: the original reproduction must fail before patching.
- `patch_applies_in_scope`: diff parses, applies with `git apply`, stays inside the repo, and
  does **not** modify tests/conftest/test config (otherwise a model could "fix" a bug by editing the test).
- `reproduction_green`: the same reproduction passes after patching.
- `regression`: the repository's full pytest suite passes after patching.
- `adversarial`: model-authored pytest tests, executed in the sandbox, find no counterexample.

All mandatory checks are re-run on a fresh workspace after **every** patch.

## Verdicts (evaluated in this order)

1. **NOT_VERIFIED** — a required correctness check `failed` (counterexample, failed regression,
   reproduction still failing, patch touching tests or not applying).
2. **INSUFFICIENT_EVIDENCE** — a mandatory check is missing/`error`/`skipped`/`not_run`; the bug was
   never reproduced (`reproduction_red` not passed); or a check passed with zero executed tests.
3. **VERIFIED_WITH_CONDITIONS** — all mandatory checks passed, but: the sandbox is not self-tested
   container isolation, an optional check did not pass, or limitations were recorded.
4. **VERIFIED** — none of the above.

`VERIFIED` is not a proof. It means: *no counterexample was found within the executed checks and
budget.* The certificate lists exactly what ran and what did not.

## Known weaknesses of this policy (read before trusting a verdict)

- Adversarial tests are model-written. A failing one may be a wrong test (false rejection); a passing
  one may be weak (false acceptance). Until mutation testing / test-validity gates exist, treat
  counterexamples as candidates for human review.
- Hypotheses are not experimentally discriminated (recorded as `proposed_untested`).
- Local-process sandbox mode caps every verdict at `VERIFIED_WITH_CONDITIONS` by design.

## Sandbox requirements

- `LocalSandbox` (dev only, tested): scrubbed env (no keys/credentials), rlimits, timeout + process-group
  kill, workspace copy, empty network namespace when the kernel permits. **No filesystem isolation.**
- `DockerSandbox` (implemented, **not yet run in a real Docker environment**): `--network none`,
  read-only root, non-root, `--cap-drop ALL`, pids/memory/cpu limits. `self_test()` must pass on the host
  before the policy treats isolation as verified.
- Nebius-hosted sandbox: **not implemented**.
