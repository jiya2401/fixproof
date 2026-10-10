# FixProof Roadmap (reordered; status is what is actually in the code)

Deadline: Oct 30, 2026 10:00 PDT (submission period per the hackathon listing).

## Done in the current slice (tested)
- Verdict policy v1 + sealed, typed Fix Certificate (backend + frontend types)
- Process sandbox (env scrubbing, rlimits, timeout, network namespace) with isolation tests
- Patch scope validation (no test edits) + `git apply`
- Red → patch → green → regression → adversarial pipeline, bounded repair loop with counterexample
  feedback, repeated-patch detection
- Validated Nebius client (timeouts/retries, JSON validation, usage tracking) — **live call unverified**
- Benchmark harness + 2 validated cases + held-out oracles — **no model results yet**
- Certificate UI with expandable evidence, iterations, timeline

## P0 — must happen before submission
1. Run `python scripts/check_nebius.py` with a real key; fix `NEBIUS_MODEL` to the exact listed id.
2. Run the pipeline end-to-end with real Nemotron on both example cases; fix prompt/format failures.
3. Establish the real sandbox: build `backend/sandbox-image`, run `DockerSandbox.self_test()`.
   Also investigate the **Token Factory Sandboxes** named in the track description and implement
   `NebiusSandbox` behind the existing `SandboxRunner` interface (API not verified here).
4. Run `evals/benchmark.py` (≥3 trials/case) and publish whatever it measures, wins or not.
5. Add LICENSE file (README references MIT; none present). Record the ≤3 min demo.

## P1 — raises credibility
- Test-validity gate for model-written tests (reduce false rejections): e.g. require the
  repro-derived test semantics to hold, run adversarial tests on the original code to record which
  ones discriminate, and surface "needs human review" instead of a hard fail when a test cannot be
  validated.
- Hypothesis experiments: run model-authored probes to support/contradict hypotheses.
- Hypothesis property tests (only for invariants expressible as templates).
- More benchmark cases (≥6), including cases where FixProof is expected to *lose*.

## P2 — conditional
- mutmut on changed code (measures test strength), deeper call graph / impact-selected tests,
  arbitrary repository cloning, Nebius Serverless Jobs, multi-language.
