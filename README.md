# FixProof

**AI proposes the fix. Evidence earns the merge.**

FixProof is an evidence-driven autonomous software repair system being built for the **Nebius × NVIDIA Global AI Hackathon 2026** in the **Coding & Agentic Engineering** track.

The project is intentionally not another code generator. FixProof separates **AI reasoning** from **verification evidence**:

- NVIDIA Nemotron reasons about the repository, root cause, minimal repair, and verification strategy.
- A deterministic execution engine runs the reproduction test, the existing regression suite, and model-authored adversarial tests (property-based and mutation testing are planned, not implemented).
- A patch receives a Fix Certificate only when the collected executable evidence satisfies the verification policy.

## Core workflow

```text
Issue
  ↓
Reproduce failure
  ↓
Investigate repository
  ↓
Generate / test root-cause hypotheses
  ↓
Propose minimal patch
  ↓
Design adversarial verification strategy
  ↓
Execute verification in an isolated sandbox
  ↓
PASS ──→ Fix Certificate
FAIL ──→ Repair iteration
```

## Hackathon thesis

> AI should not be trusted to declare its own code correct. A patch should earn verification through executable evidence.

## Honest status

Legend: ✅ implemented and tested · 🟡 implemented, not yet exercised live · ⛔ not implemented

| Capability | Status |
|---|---|
| Reproduce original failure (pytest exit code + JUnit parsed; "bug not reproduced" ⇒ stop) | ✅ |
| Patch scope validation (rejects edits to tests/config, traversal) + `git apply` | ✅ |
| Re-run reproduction **and** full regression suite after every patch | ✅ |
| Model-authored adversarial pytest tests **executed** in the sandbox | ✅ (with scripted model) / 🟡 (live Nemotron) |
| Spec-grounded adversarial tests (quote verified mechanically; ungrounded failures = condition, not veto) | ✅ |
| Contradictory attack tests detected across attempts; least-bad attempt reported; human dispute + no-model re-verify | ✅ |
| Counterexample → fixer feedback, bounded retries, repeated-patch detection | ✅ |
| Verdict policy v1, sealed tamper-evident Fix Certificate, certificate UI | ✅ |
| Process sandbox: scrubbed env, rlimits, timeout, network namespace | ✅ tested; **no filesystem isolation** |
| Docker sandbox (`--network none`, read-only, non-root, cap-drop) | 🟡 code + argv test only; never run against a Docker daemon |
| Nebius/Nemotron client (retries, JSON validation, usage tracking) | 🟡 `python scripts/check_nebius.py` verifies it with a key |
| Benchmark harness, 2 validated cases, held-out oracles | ✅ harness / ⛔ **no model results yet** |
| Hypothesis *experiments* (hypotheses are recorded as untested) | ⛔ |
| Hypothesis property tests, mutation testing, impact-selected tests | ⛔ (code-graph primitive exists, unused by the pipeline) |
| Nebius Token Factory Sandboxes / Serverless Jobs | ⛔ |
| Arbitrary repository cloning (only bundled `examples/` cases run) | ⛔ |

In local-process sandbox mode every verdict is capped at `VERIFIED_WITH_CONDITIONS`.
No benchmark numbers are published here because none have been measured.

## Test your own project

In the UI choose **Upload your project** (zip), **GitHub URL**, or **Local folder** (enable it with
`FIXPROOF_LOCAL_PATH_ROOTS`). FixProof runs your test suite in the sandbox, lists the failing tests, and you pick
the one to repair and describe the expected behavior. The sandbox is **offline**: your project may use the
standard library plus the packages in `backend/sandbox-image/extra-requirements.txt` (rebuild the image after
editing it). Missing imports are detected and reported. Projects with a `src/` layout are supported.
Attack tests must quote your issue, docstrings or README, so write the expected behavior down.

## What the model does vs. what tools do

| Step | Who |
|---|---|
| Root-cause hypotheses, patch, adversarial test authoring | NVIDIA Nemotron via Nebius Token Factory |
| Snapshot hash, reproduction, patch apply, regression, executing adversarial tests, verdict | deterministic code |

The certificate records this attribution plus live model usage (calls, tokens).

## Try it

```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt && pytest      # no key needed
cp .env.example .env   # add NEBIUS_API_KEY, then:
python scripts/check_nebius.py                       # verifies endpoint + model id
FIXPROOF_SANDBOX_MODE=local FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true \
  uvicorn app.main:app --port 8000                    # dev only; or build backend/sandbox-image and use docker
cd ../frontend && npm ci && npm run dev               # pick a bundled case, run, read the certificate
python evals/benchmark.py --trials 3                  # baseline vs FixProof (needs key)
```

See `docs/audit.md`, `docs/verification-policy.md`, `docs/roadmap.md`.

## Tech stack

### AI and infrastructure
- NVIDIA Nemotron via Nebius Token Factory
- OpenAI-compatible Python client
- Isolated sandbox execution adapter
- Nebius Serverless Jobs planned for longer verification workloads

### Backend
- Python 3.12 target
- FastAPI
- Pydantic / pydantic-settings

### Verification
- pytest
- Hypothesis (property-based testing)
- mutmut (mutation testing)
- pytest-cov / coverage.py
- Ruff
- mypy

### Code analysis
- Python `ast`
- NetworkX
- ripgrep (optional local tool)
- Git CLI

### Frontend
- React 19
- TypeScript
- Vite
- Tailwind CSS v4

## Repository layout

```text
fixproof/
├── backend/
│   ├── app/
│   │   ├── agents/          # investigator, fixer, verification planner
│   │   ├── api/             # FastAPI routes
│   │   ├── codegraph/       # Python AST + dependency graph
│   │   ├── llm/             # Nebius Token Factory client
│   │   ├── orchestrator/    # typed state + workflow engine
│   │   ├── sandbox/         # execution-environment adapters
│   │   ├── tools/           # filesystem / git / search helpers
│   │   ├── verification/    # deterministic verification engine
│   │   └── main.py
│   ├── tests/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/
│   ├── Dockerfile
│   └── package.json
├── evals/                   # benchmark harness and evaluation cases
├── examples/
│   └── buggy-python-app/    # small target used for development
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   └── verification-policy.md
├── scripts/
│   ├── setup.ps1
│   └── setup.sh
├── .env.example
├── .gitignore
├── docker-compose.yml
├── LICENSE
└── README.md
```

## Quick start

### 1. Prerequisites

- Python 3.12 recommended
- Node.js 20+
- Docker Desktop (recommended for future sandbox milestones)
- Git

### 2. Configure environment

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Add your Nebius API key to `.env` when you are ready to connect Token Factory. Never commit `.env`.

### 3. Backend

From the repository root:

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs`.

### 4. Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 5. Run backend tests

```bash
cd backend
pytest -q
```

## Nebius / Nemotron configuration

The client reads these environment variables (confirm the model id with `scripts/check_nebius.py`):

```env
NEBIUS_API_KEY=
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b
```

The exact production model can be changed later without changing the agent architecture.

## Safety model

Target repositories must eventually execute only inside an isolated sandbox with resource limits. API keys and GitHub credentials must never be exposed inside target-repository execution environments.

See [`docs/verification-policy.md`](docs/verification-policy.md).

## Contributing during the hackathon

Keep each milestone small and demonstrable. Do not add a feature to the README as "implemented" until there is code and a test proving it.

## License

MIT — see [`LICENSE`](LICENSE).
