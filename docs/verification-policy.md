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

## Patch format

The model proposes SEARCH/REPLACE edits (exact text, must match exactly once); deterministic
code verifies them and generates the unified diff (`repair/edits.py`). A failed match is fed back
with the closest line in the file. Reason: a live Nemotron patch used bare `@@` hunk headers and
was rejected by `git apply`; models are unreliable at diff line numbers. A fenced unified diff is
still accepted as a fallback.

## Mandatory checks

`reproduction_red` (precondition) · `patch_applies_in_scope` · `reproduction_green` ·
`regression` · `adversarial`.

- `reproduction_red`: the original reproduction must fail before patching.
- `patch_applies_in_scope`: diff parses, applies with `git apply`, stays inside the repo, and
  does **not** modify tests/conftest/test config (otherwise a model could "fix" a bug by editing the test).
- `reproduction_green`: the same reproduction passes after patching.
- `regression`: judged against a **pre-patch baseline**. The full suite runs once before the patch and once
  after; the check fails if any test that passed before no longer passes (including tests that stop being
  collected, e.g. through a new import error). Tests that were already failing, and collection errors, are not
  blamed on the patch, but their number is disclosed as a limitation (verdict at most `VERIFIED_WITH_CONDITIONS`).
  If the baseline or the post-patch run cannot complete (timeout, crash), the check is `error` and the verdict
  is `INSUFFICIENT_EVIDENCE`.
- `adversarial`: model-authored **spec-grounded** pytest tests, executed in the sandbox, find no counterexample. At least one grounded test must have executed.
- `adversarial_ungrounded` (optional): tests whose spec quote was missing or not found. Their failures are reported as a condition for human review, never as a veto, and are never fed back to the fixer.

All mandatory checks are re-run on a fresh workspace after **every** patch.

## Spec grounding of model-written tests

Each adversarial test must quote, verbatim, a sentence from the issue or from the ORIGINAL
(pre-patch) source docstrings that it enforces (whitespace/case-insensitive, min 15 chars;
test files are not a source of spec). The check is mechanical (`verification/grounding.py`).
Counterexamples are printed with their `[SPEC: "..."]` quote for review. Grounding proves
traceability, not that the assertion truly follows from the quote.

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

- Adversarial tests are model-written. Grounding reduces invented-rule rejections (observed once in a
  live run: a test required rejecting `"refresh: abc123"`, which no stated rule covers), but a grounded
  test can still over-interpret its quote, and a passing one may be weak. Treat counterexamples as
  candidates for human review; mutation testing is not implemented.
- **False counterexamples that grounding cannot catch (seen in two live paginate runs):** a test quoted the
  real docstring sentence about a page past the end, then asserted `paginate([1,2,3,4,5], 3, 2) == []`. Page 3 is
  `[5]`, so the assertion was wrong. Effects seen live: a correct patch was rejected, and the fixer, steered by the
  wrong test, produced a worse patch (returning `[]` for partial last pages), which the executed tests then correctly
  rejected. Mitigations now built:
  1. every attack test is run against every attempt's patch; tests that cannot all be satisfied by the attempts
     (one group passes only on attempt i, the other only on attempt j) are reported as **contested** and the fixer
     is warned not to trade one group for the other;
  2. the certificate reports the **least-bad attempt** (fewest executed failures; ties go to the later attempt),
     not blindly the last one;
  3. **human dispute**: a reviewer can exclude a failing, spec-grounded attack test with a written reason, and
     every check is re-run on that attempt's patch with no model calls. The exclusion is a recorded condition
     (verdict at most `VERIFIED_WITH_CONDITIONS`); only tests that failed on that attempt can be excluded, and
     excluding tests never hides a failure from another test.
  Not solved: nothing decides *automatically* which side of a contradiction is right.
- If the test-author reply cannot be parsed in an iteration, tests from earlier iterations still run and
  a limitation is recorded (verdict at most `VERIFIED_WITH_CONDITIONS`).
- Hypotheses are not experimentally discriminated (recorded as `proposed_untested`).
- Local-process sandbox mode caps every verdict at `VERIFIED_WITH_CONDITIONS` by design.

## Sandbox requirements

- `LocalSandbox` (dev only, tested): scrubbed env (no keys/credentials), rlimits, timeout + process-group
  kill, workspace copy, empty network namespace when the kernel permits. **No filesystem isolation.**
- `DockerSandbox` (implemented, **not yet run in a real Docker environment**): `--network none`,
  read-only root, non-root, `--cap-drop ALL`, pids/memory/cpu limits. `self_test()` must pass on the host
  before the policy treats isolation as verified.
- Nebius-hosted sandbox: **not implemented**.
