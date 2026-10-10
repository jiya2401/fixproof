> **Target architecture, not current status.** Property-based testing, mutation testing and Nebius-hosted execution below are planned. See the status table in README.md and docs/audit.md for what is implemented.

# FixProof Architecture

## Design principle

FixProof separates **reasoning** from **evidence**.

Nemotron may propose hypotheses, patches, test strategies, invariants, and likely impact areas. It must not be the final authority on whether a patch worked. The verdict is derived from executable evidence produced by deterministic tools.

## Logical pipeline

```text
Issue
  ↓
Repository Analyzer
  ↓
Investigator Agent (Nemotron)
  ↓
Reproduction Gate
  ↓
Fix Agent (Nemotron)
  ↓
Minimal Candidate Patch
  ↓
Verification Planner (Nemotron)
  ↓
Execution / Evidence Engine
  ├─ original reproduction
  ├─ existing tests
  ├─ generated adversarial tests
  ├─ property-based tests
  ├─ mutation tests
  ├─ static checks
  └─ impact-aware regressions
  ↓
Verdict Policy
  ├─ FAIL → repair iteration
  └─ PASS → Fix Certificate
```

## Important boundaries

### AI layer
Responsible for:
- repository reasoning
- relevant-file selection
- hypothesis generation
- root-cause reasoning
- minimal patch planning
- adversarial verification planning

Not responsible for:
- inventing command results
- claiming tests passed
- issuing a verification verdict without evidence

### Execution layer
Responsible for:
- isolated repository execution
- command stdout/stderr/exit status
- test results
- before/after reproduction
- coverage and mutation results
- evidence persistence

### Verdict layer
Responsible for applying explicit policy to collected evidence. Initial verdicts:
- `VERIFIED`
- `VERIFIED_WITH_CONDITIONS`
- `NOT_VERIFIED`
- `INSUFFICIENT_EVIDENCE`

## First supported target

The first end-to-end version intentionally targets **Python + pytest repositories**. JavaScript/TypeScript support is an extension, not an MVP requirement.
