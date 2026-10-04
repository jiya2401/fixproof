# Contributing to FixProof

FixProof is being built milestone-first for the Nebius × NVIDIA Global AI Hackathon.

## Rule 1: do not fake capabilities

A feature may be described as implemented only when code and a reproducible check exist for it.

## Rule 2: keep model reasoning separate from evidence

Nemotron can plan, hypothesize, propose patches, and design verification strategies. Test outcomes, command results, and verification verdict inputs must come from executed tools.

## Rule 3: keep pull requests narrow

Recommended branch names:

```text
feat/m1-red-green-loop
feat/m2-regression-suite
feat/m3-verification-planner
feat/m4-adversarial-tests
feat/m5-repair-loop
feat/m6-property-tests
feat/m7-impact-graph
feat/m8-mutation-testing
feat/m9-fix-certificate
feat/m10-dashboard
feat/m11-benchmark
feat/m12-deployment
```

## Local checks before merging

Backend:

```bash
cd backend
pytest -q
ruff check app tests
```

Frontend:

```bash
cd frontend
npm run build
```

## Secrets

Never commit `.env`, Nebius credentials, GitHub tokens, SSH keys, or credentials belonging to a target repository.
