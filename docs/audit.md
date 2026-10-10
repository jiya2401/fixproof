# Audit — repository at commit 3ba7585 ("Initial FixProof core scaffold")

All statements below were checked against the code unless marked *(unverified)*.

## 1. Status at audit time

| Area | Status |
|---|---|
| FastAPI app, health, in-memory investigations | working (8 tests passed) |
| Typed state + transition guard | working, but **never driven by anything** |
| Nebius client | written, never executed against a live endpoint; default model id not found in any listing I could reach |
| Agents (investigator/fixer/verifier) | prompt wrappers only; nothing called them |
| Sandbox | `DockerSandbox`/`NebiusSandbox` raised `NotImplementedError`; `LocalSandbox` unhardened (inherited full env incl. API keys; unhandled `TimeoutExpired`) |
| Verification | pytest runner, red/green dataclass, code graph/impact: primitives. Property/mutation: docstring-only files |
| Verdict | **unsafe**: any one passing check ⇒ `VERIFIED`; test asserted that; ignored non-required failures; no notion of zero tests executed |
| Pipeline / repair loop / certificate | did not exist |
| Frontend | static marketing page; only `/about` was called |
| Benchmark | `print("scaffold")` |
| CI | lint step failed (13 ruff errors); frontend job could not pass (no lockfile, `import.meta.env` type error) |

## 2. Findings by severity

- **Critical** — Verdict function could issue `VERIFIED` from a single check. Fixed (policy v1).
- **Critical** — No executable path from issue to patch to verdict. Fixed for a Python/pytest slice.
- **High** — `LocalSandbox` leaked the environment (API keys) to target code. Fixed + tested.
- **High** — Model could cheat by editing tests. Fixed: protected-path rejection.
- **High** — Default model id `nvidia/Nemotron-3_5-Lightning` not found in any Nebius listing I could
  access; listings show ids like `nvidia/nemotron-3-super-120b-a12b`. Default changed; **must be confirmed
  with `scripts/check_nebius.py`** (cannot be verified without a key).
- **High** — Verifier schema let the model suggest shell commands. Removed; only pytest source is executed.
- **Medium** — README claimed capabilities (mutation, property tests, impact checks, serverless) with no code.
  Corrected below. README also references a LICENSE file that does not exist.
- **Medium** — CI never passed. Fixed lint, lockfile, tsconfig/type errors.
- **Low** — In-memory investigation store (lost on restart); `networkx` call graph is name-based and unresolved.

## 3. Effect on the submission

A judge running the original repo would see a landing page and no repair. The thesis is credible only
if a live run shows: a real reproduction, a rejected weak patch, a repair, and a certificate. That path now
exists in code and is tested with a scripted model; it has **not** been exercised with live Nemotron.

## 4. Competitiveness (equal-weight criteria: Technological Implementation, Design, Potential Impact,
Quality of the Idea — per hackathon listings)

| Criterion | Before | After this slice | What moves it most |
|---|---|---|---|
| Technological implementation | scaffold, nothing runs | real executed pipeline, honest sandbox, tests | live Nemotron run, real container/Token Factory sandbox, measured benchmark |
| Design | static page | evidence-first certificate UI | a polished 3-minute demo of reject→repair→certificate |
| Potential impact | asserted | argued by prior art (below) but unmeasured | benchmark numbers on ≥6 cases |
| Quality of idea | strong framing | unchanged framing; now demonstrable | showing the counterexample actually changes outcomes |

The track description reads "coding agents … that write, run, and test code in Token Factory Sandboxes"
(per a hackathon event write-up). Not using Token Factory Sandboxes is the largest alignment risk. *(I could not
verify the Sandboxes API.)*

## 5. Prior art (verified from papers/leaderboard analyses; not exhaustive)

- Patch/test overfitting is long established (plausible patches, Qi et al.; Smith et al.). Surveys of
  SWE-bench leaderboards note overfitting in Agentless, AutoCodeRover and others (arXiv 2506.17208).
- Agentless-style systems already generate reproduction tests and use them to validate/select patches;
  e-Otter++ reproduction tests still showed 21.8–33.0% test overfitting in one study (arXiv 2511.16858).
- SWE-ABS (arXiv 2603.00520) and STING (arXiv 2604.01518) use adversarial/mutation-driven test
  generation to strengthen SWE-bench suites; SWE-ABS reports rejecting ~20% of previously passing patches.
  These work **offline with a ground-truth patch**.

Implication: "adversarial tests catch plausible-but-wrong patches" is **not novel**. What may be
differentiating — and needs evidence — is doing it *online without ground truth*, in a bounded repair loop,
with a policy-governed, tamper-evident certificate that distinguishes counterexample / execution failure /
not run. The main technical risk is the same one those papers study: model-written tests can be wrong,
causing false rejections. This is why the benchmark must report false rejections too, and why P1 includes
a test-validity gate.
