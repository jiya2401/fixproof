# FixProof

**AI proposes the fix. Evidence earns the merge.**

FixProof is an evidence-driven autonomous software repair system being built for the **Nebius × NVIDIA Global AI Hackathon 2026** in the **Coding & Agentic Engineering** track.

The project is intentionally not another code generator. FixProof separates **AI reasoning** from **verification evidence**:

- NVIDIA Nemotron reasons about the repository, root cause, minimal repair, and verification strategy.
- A deterministic execution engine runs reproduction tests, existing regression tests, generated adversarial tests, property-based tests, mutation tests, and impact-aware checks.
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

## Current status

This repository is the **core project scaffold**. It contains a runnable backend and frontend, the agreed architecture, typed investigation state, Nebius/Nemotron client wrapper, agent interfaces, verification primitives, Python code-graph analysis, sandbox abstractions, tests, and a deliberately buggy example project.

The autonomous repair loop is intentionally built milestone-by-milestone rather than faked in the starter repository.

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

The starter wrapper reads these environment variables:

```env
NEBIUS_API_KEY=
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/Nemotron-3_5-Lightning
```

The exact production model can be changed later without changing the agent architecture.

## Initial API

- `GET /health` — backend health check
- `GET /api/v1/about` — project capability summary
- `POST /api/v1/investigations` — create an investigation record
- `GET /api/v1/investigations/{id}` — read its current state

The create endpoint **does not pretend to repair code yet**. It creates a typed investigation state that the upcoming milestones will drive through the real repair pipeline.

## Development milestones

1. **M1 — Red/green repair loop:** reproduce a failing test, ask Nemotron for a minimal repair, apply patch, rerun the same reproduction.
2. **M2 — Regression suite:** run existing tests before accepting a repair.
3. **M3 — Verification planner:** Nemotron outputs structured edge cases, invariants, and attack scenarios.
4. **M4 — Generated adversarial tests:** execution engine runs model-designed tests.
5. **M5 — Repair iteration:** failed evidence automatically returns to the fixer.
6. **M6 — Property-based testing:** add Hypothesis-generated counterexamples.
7. **M7 — Impact graph:** use AST + NetworkX to identify affected modules/tests.
8. **M8 — Mutation testing:** measure whether verification tests can detect deliberately broken variants.
9. **M9 — Fix Certificate:** evidence-backed `VERIFIED / VERIFIED WITH CONDITIONS / NOT VERIFIED / INSUFFICIENT EVIDENCE` verdicts.
10. **M10 — Product dashboard:** live investigation + evidence + certificate UI.
11. **M11 — Benchmark:** compare baseline Nemotron repair vs FixProof verification loop.
12. **M12 — Nebius deployment and demo polish.**

See [`docs/roadmap.md`](docs/roadmap.md) for acceptance criteria.

## Safety model

Target repositories must eventually execute only inside an isolated sandbox with resource limits. API keys and GitHub credentials must never be exposed inside target-repository execution environments.

See [`docs/verification-policy.md`](docs/verification-policy.md).

## Contributing during the hackathon

Keep each milestone small and demonstrable. Do not add a feature to the README as "implemented" until there is code and a test proving it.

## License

MIT — see [`LICENSE`](LICENSE).
