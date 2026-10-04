# Verification Policy

FixProof must never treat an LLM statement such as "the patch looks correct" as proof.

## Minimum acceptance evidence

A candidate repair should not be marked `VERIFIED` unless all required checks for the run have produced concrete evidence.

For the initial Python/pytest scope:

1. The original failure must be reproducible before the patch when a deterministic reproduction is available.
2. The same reproduction must pass after the patch.
3. Relevant existing regression tests must pass.
4. Generated verification scenarios that are executable must pass.
5. No blocking static-analysis failure may remain.
6. The verification engine must preserve command output and exit status.

## Conditional verdicts

Use `VERIFIED_WITH_CONDITIONS` when core behavior is fixed but some requested evidence could not be fully established, for example:
- mutation score below the configured target
- unsupported dependency path
- non-deterministic reproduction
- verification budget exhausted

Use `INSUFFICIENT_EVIDENCE` when the system cannot establish a trustworthy reproduction or cannot execute the relevant verification environment.

Use `NOT_VERIFIED` when a concrete counterexample, failed regression, failed original reproduction, or other blocking check remains.

## Security

Target repository code is untrusted.

Production sandbox requirements:
- non-root execution
- CPU/memory/PID/time limits
- no host Docker socket
- no host filesystem mounts except an isolated workspace
- no Nebius API key inside the target environment
- no GitHub credentials inside the target environment
- network disabled during verification unless a narrowly scoped setup step explicitly requires it
- sandbox destroyed after the run

## Wording

FixProof should report:

> No counterexample was found within the configured verification strategy and execution budget.

It should not report:

> This patch is universally correct.
