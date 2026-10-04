# FixProof Build Roadmap

The purpose of this roadmap is to keep implementation aligned with the hackathon thesis and prevent feature drift.

## M0 — Core repository scaffold (included in this starter)

Acceptance criteria:
- backend starts
- frontend starts
- health endpoint works
- typed investigation state exists
- Nebius client wrapper exists
- sandbox interface exists
- verification result/verdict primitives exist
- Python code graph parser works on a simple project
- backend tests pass

## M1 — Red/green repair loop

Goal: prove the technical heart before adding polish.

Acceptance criteria:
- copy/clone one small Python target into an isolated workspace
- execute an explicitly selected failing pytest reproduction
- preserve failing evidence
- send repository context + issue to Nemotron
- produce a candidate patch
- apply patch to workspace
- execute the exact same reproduction
- preserve passing/failing evidence
- no UI dependency

## M2 — Existing regression suite

Acceptance criteria:
- discover relevant pytest suite
- execute after patch
- reject patch on regression
- persist stdout/stderr/exit codes

## M3 — Structured verification planner

Nemotron must return typed JSON containing:
- adversarial scenarios
- invariants/properties
- targeted files/functions
- recommended test commands
- risk areas

No free-form verifier verdict is accepted.

## M4 — Adversarial generated tests

Acceptance criteria:
- planner-generated tests are written into an isolated temporary test location
- tests execute rather than being judged by text
- failed adversarial tests feed evidence back to repair loop

## M5 — Repair iteration

Acceptance criteria:
- failed evidence creates next repair attempt
- maximum iteration budget enforced
- every patch version is preserved

## M6 — Property-based testing

Acceptance criteria:
- convert suitable invariants into Hypothesis strategies/tests
- record number of generated examples and counterexamples

## M7 — Dependency impact graph

Acceptance criteria:
- Python AST builds import/function-call graph
- changed symbols map to likely dependent modules
- impacted test modules are prioritized

## M8 — Mutation testing

Acceptance criteria:
- mutmut runs only on scoped changed code where practical
- mutation score and surviving mutants recorded
- surviving high-risk mutant can downgrade verdict

## M9 — Fix Certificate

Certificate contains:
- issue
- reproduction before/after
- root-cause hypothesis/evidence summary
- patch summary
- regression results
- adversarial test results
- property-test results
- mutation results
- impact graph summary
- limitations
- evidence-based verdict

## M10 — Product dashboard

UI priorities:
- one-page investigation creation
- live pipeline status
- hypothesis/evidence ledger
- patch diff
- verification evidence
- Fix Certificate

Do not build an IDE clone.

## M11 — Evaluation

Compare:

```text
Baseline: Nemotron → patch → existing tests
FixProof: Nemotron → patch → adversarial strategy → evidence engine → repair loop
```

Track:
- true fixes accepted
- incorrect fixes accepted
- regressions introduced
- counterexamples discovered
- repair iterations
- execution time
- model/token usage

## M12 — Nebius deployment and demo

Acceptance criteria:
- real Nemotron calls through Nebius Token Factory
- isolated execution path demonstrated
- public working demo/test build
- public repository + MIT license
- README accurately identifies sponsor technologies
- <=3-minute public demo video
