# FixProof

> **AI proposes the fix. Evidence earns the merge.**

FixProof is an **automated, secure, multi-language AI QA engineering pipeline** that bridges your local IDE with an isolated cloud sandbox. It does not just generate code — it puts every AI-proposed patch through a gauntlet of deterministic verification, differential security scanning, and spec-grounded adversarial attacks before issuing a cryptographically sealed **Fix Certificate**.

Built for the **Nebius × NVIDIA Global AI Hackathon 2026** · Coding & Agentic Engineering track.

---

## 🏗️ Architecture at a Glance

```
Your Editor (any language)
       │  watchdog + 300ms debounce
       ▼
sync_worker.py  ──POST──►  FastAPI Backend  ──WebSocket──►  React Frontend
                            │
                ┌───────────┴─────────────────────────────────────┐
                │              Verification Pipeline              │
                │                                                 │
                │  1. Reproduce failure (red run)                 │
                │  2. Investigate AST + dependency graph          │
                │  3. Nemotron: root cause + minimal patch        │
                │  4. Patch scope validation + git apply          │
                │  5. Regression run (green run)                  │
                │  6. SAST differential security scan (B101–B203) │
                │  7. Adversarial spec-grounded attack tests      │
                │  8. Bounded repair loop (counterexample → fix)  │
                │  9. Verdict policy + sealed Fix Certificate     │
                │ 10. GitHub Git Data API → Pull Request          │
                └─────────────────────────────────────────────────┘
```

---

## 🌟 Project Hook & Vision

The software industry has a trust problem: AI models that write code are also trusted to declare that code correct. FixProof breaks that conflict of interest.

Every patch goes through five independent gates before it is promoted:

| Gate | Who runs it |
|---|---|
| Bug reproduction (fail → pass) | Deterministic sandbox |
| Patch scope & traversal safety | Rules engine |
| Full regression suite | Deterministic sandbox |
| Differential SAST security scan | Pure-Python AST engine |
| Spec-quoted adversarial attack tests | Deterministic sandbox + Nemotron authorship |

Only patches that clear every gate receive a **Fix Certificate** — a tamper-evident, SHA-256-sealed record of every executable piece of evidence. That certificate, not the model's confidence score, earns the merge.

---

## 🏗️ Core Architecture & Features

### 🔒 Isolation & Verification Engine

- **Process sandbox** — scrubbed environment variables, `rlimits`, configurable timeout, optional network namespace. Every execution is offline by design.
- **Docker sandbox adapter** — `--network none`, read-only source mount, non-root user, full capability drop. Code and configuration tested; awaiting a daemon target for live runs.
- **Deterministic verdict policy v1** — a strict policy object that aggregates check outcomes and emits one of `VERIFIED`, `VERIFIED_WITH_CONDITIONS`, or a failing verdict. The policy is evaluated identically on every run; the model never touches it.
- **Sealed Fix Certificate** — SHA-256 over the entire certificate payload, recorded at issuance. The seal is verified on every read. The certificate includes: root cause, patch diff, attack test results, check outcomes, model usage (calls + tokens), and disclaimers.
- **Human re-verify flow** — a reviewer can dispute one or more spec-grounded attack tests. FixProof re-runs all checks on the same patch excluding only the disputed tests, recording the reason in the certificate. No model calls are made during re-verification.

### ⚡ Real-Time Sync Loop

- **`sync_worker.py`** — a zero-dependency CLI watcher (`watchdog`) that monitors your local project directory recursively. A 300 ms debounce buffer coalesces burst saves (Ctrl+S in your editor) into a single HTTP POST to the backend.
  - Ignores: `.git`, `__pycache__`, `node_modules`, `.venv`, `.fixproof_projects`, editor temporaries (`.swp`, `.tmp`, `~`, `.DS_Store`).
  - Works with Python, TypeScript, and Go source trees — the runner is auto-detected by the backend.
- **`POST /api/v1/project/sync`** — receives the file delta, writes it atomically to the project workspace (with strict path-traversal protection), triggers a sandboxed test run, and broadcasts two WebSocket events: `TESTS_RE_RUNNING` → `RUN_COMPLETE`.
- **`WebSocket /api/v1/ws/sync`** — a persistent channel. The React frontend connects on load; `SyncConnectionManager` broadcasts to all active subscribers without blocking the HTTP layer.
- The entire loop — file save → sync POST → test run → WS broadcast — completes in under two seconds on local hardware for typical Python/JS projects.

### 🌐 Multi-Runtime Factory

All three runtimes conform to the same `LanguageRunner` interface: `run_tests()`, `reproduce_bug()`, `install_deps()`. A single factory call auto-detects the project language from filesystem signatures and returns the right runner — no configuration file required.

| Language | Detector signal | Runner | Output format |
|---|---|---|---|
| **Python** | any `*.py` file | `PythonRunner` → `pytest --junitxml` | JUnit XML |
| **JavaScript / TypeScript** | `package.json` | `JSRunner` → `npx vitest run --reporter=json` | Vitest JSON |
| **Go** | `go.mod` | `GoRunner` → `go test -json ./...` | NDJSON stream |

Detection priority: `go.mod` > `package.json` > `*.py` > Python (fallback). The detector scans at depth ≤ 2 to prevent false positives from vendored sub-modules.

**NDJSON streaming parser** (`parsers/gotest_parser.py`) — parses `go test -json` output line by line, accumulates per-test output buffers, extracts file+line references from `--- FAIL` annotations, and produces a normalized `TestRunResult`. Malformed lines are silently skipped; the parser never raises.

**Vitest JSON parser** (`parsers/vitest_parser.py`) — maps Vitest's single-blob JSON to the same `TestRunResult` schema, including per-assertion failure messages and line numbers from `location` objects.

**Boundary protection map** (`boundary.py`) — classifies every file in a project into `editable` or `locked` before a repair attempt. Test files, config manifests (`go.mod`, `package.json`, `conftest.py`), and lock files are always locked. The AI patch is rejected if it touches a locked path.

### 🛡️ Security Perimeter — Differential SAST Engine

`backend/app/security.py` is a **zero-dependency, pure-Python AST vulnerability scanner** that runs a *differential* analysis: it scans the pre-patch source (baseline) and the post-patch workspace, then reports only the **net-new** findings introduced by the AI fix. Pre-existing issues are noted but do not block the patch.

| Rule | Category | Severity | Detection method |
|---|---|---|---|
| **B101** | SQL Injection | HIGH | Dynamic values in `execute()`, `executemany()`, `raw()`, `filter()`, `extra()`, `RawSQL()` — detects f-strings, `%`-format, `.format()`, string concat |
| **B102** | Command Injection | HIGH | `subprocess.*` with `shell=True` + dynamic arg; `os.system()` / `os.popen()` with dynamic arg |
| **B103** | Path Traversal | HIGH | `open()` or `Path()` called with a dynamically constructed path (f-string or `+` concat) |
| **B201** | Hardcoded Secret | MEDIUM | Assignment of a string literal to a variable whose name contains `password`, `secret`, `api_key`, `token`, `private_key`, etc. |
| **B202** | Unsafe Deserialization | HIGH/MEDIUM | `pickle.loads()` / `pickle.load()` / `Unpickler`; `yaml.load()` without `Loader=` |
| **B203** | Weak Crypto Hash | MEDIUM | `hashlib.md5()` / `hashlib.sha1()` — flags both `import hashlib` and `from hashlib import md5` styles |

The scanner tracks import aliases across `import X as Y` and `from X import Y as Z` forms. It is fail-open: scanner exceptions never block the repair pipeline. The `run_comparative_scan()` convenience function returns a structured `SecurityScanResult` including `passed`, `new_vulnerabilities`, `baseline_count`, `post_patch_count`, `files_scanned`, and `scan_duration_seconds`.

### 🚀 Automated Cloud Delivery — GitHub Git Data API Engine

`backend/app/github_pr.py` opens production pull requests **entirely through the GitHub REST API** — no local clone, no credentials on disk, no `git push`.

**Full flow:**
1. Validates the certificate verdict (`VERIFIED` or `VERIFIED_WITH_CONDITIONS` only).
2. Re-validates the patch with the same strict scope rules used during repair.
3. Authenticates via `PyGithub` with the provided token (header `X-GitHub-Token`, never stored or logged) or `FIXPROOF_GITHUB_TOKEN`.
4. Reads the target branch's recursive tree via the Git Data API.
5. Applies the patch in a throwaway `tempfile.TemporaryDirectory` using the same `git apply` the pipeline uses — POSIX-safe path resolution prevents traversal.
6. Uploads changed blobs, creates a new tree, and commits — all through the API.
7. Creates branch `fixproof/patch-<id>` (retries with a random suffix on name collision, up to 3 attempts).
8. Opens the PR with an auto-generated body: root cause, fix summary, full attack-test table, verification evidence table, files changed, conditions, and a tamper-evident footer with the certificate SHA-256.
9. Polls mergeability (up to 3×) and reports the result synchronously.
10. Publishing the same certificate twice returns the existing open PR (`reused=True`).

**Stable machine-readable error codes:** `TOKEN_EXPIRED`, `TOKEN_MISSING`, `PATCH_CONFLICT`, `BRANCH_CONFLICT`, `RATE_LIMITED`, `INSUFFICIENT_PERMISSIONS`, `SSO_REQUIRED`, `NOT_FOUND`, `EMPTY_REPOSITORY`, `REPO_ARCHIVED`, `NO_CHANGES`, `PR_ALREADY_EXISTS`, `GITHUB_UNREACHABLE`.

---

## 📊 Current Capabilities — Honest Status Matrix

> Legend: ✅ implemented and tested · 🟡 implemented, not yet exercised live · ⛔ not implemented

| Capability | Status |
|---|---|
| **Reproduce original failure** — pytest exit code + JUnit XML parsed; "bug not reproduced" ⇒ stop | ✅ |
| **Patch scope validation** — rejects edits to tests/config, rejects path traversal + `git apply` | ✅ |
| **Re-run reproduction + full regression suite** after every patch | ✅ |
| **Model-authored adversarial pytest tests executed** in the sandbox | ✅ (scripted model) / 🟡 (live Nemotron) |
| **Spec-grounded adversarial tests** — quote verified mechanically; ungrounded failures = condition, not veto | ✅ |
| **Contradictory attack tests** detected across attempts; least-bad attempt reported; human dispute + no-model re-verify | ✅ |
| **Counterexample → fixer feedback**, bounded retries, repeated-patch detection | ✅ |
| **Verdict policy v1**, sealed tamper-evident Fix Certificate, certificate UI | ✅ |
| **Process sandbox** — scrubbed env, rlimits, timeout, network namespace | ✅ tested; **no filesystem isolation** |
| **Docker sandbox** — `--network none`, read-only, non-root, cap-drop | 🟡 code + test coverage; never run against a live Docker daemon |
| **Multi-Language Factory** — Python (pytest), JS/TS (Vitest), Go (go test) | ✅ |
| **NDJSON streaming parser** for `go test -json` output | ✅ |
| **Vitest JSON parser** for `npx vitest run --reporter=json` output | ✅ |
| **Language auto-detection** from filesystem signatures (`go.mod` / `package.json` / `*.py`) | ✅ |
| **Boundary protection map** — test/config files locked; enforced across all three runtimes | ✅ |
| **Differential SAST Security Scan** — pure-Python AST engine, rules B101–B203 | ✅ |
| **Real-time WebSocket Live Local File Sync** — `sync_worker.py` + `POST /project/sync` + `WS /ws/sync` | ✅ |
| **Automated GitHub PR via Git Data API** — branch, apply, commit, push, PR body | ✅ |
| **Project sources** — zip upload, GitHub URL clone, local folder (allowlisted path roots) | ✅ |
| **Nebius / Nemotron client** — retries, JSON validation, usage tracking | 🟡 `python scripts/check_nebius.py` verifies with a key |
| **Benchmark harness, 2 validated cases, held-out oracles** | ✅ harness / ⛔ **no model results published yet** |
| **Hypothesis property tests, mutation testing** | ⛔ |
| **Hypothesis experiments** (hypotheses recorded as untested) | ⛔ |
| **Nebius Token Factory Sandboxes / Serverless Jobs** | ⛔ |
| **Arbitrary repository cloning** (only bundled `examples/` cases run end-to-end) | ⛔ |

In local-process sandbox mode every verdict is capped at `VERIFIED_WITH_CONDITIONS`.
No benchmark numbers are published because none have been measured with a live model.

---

## 🚀 Quick Start & Installation

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 20+ |
| Git | any recent |
| Docker Desktop | optional — required for Docker sandbox mode |

### 1 · Clone & configure

```bash
git clone https://github.com/<your-org>/fixproof.git
cd fixproof
cp .env.example .env          # macOS / Linux
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Open `.env` and set your keys:

```env
NEBIUS_API_KEY=<your-key>
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b

# Optional — required only for the GitHub PR feature
FIXPROOF_GITHUB_TOKEN=<fine-grained-PAT>

# Optional — enables the "local folder" project source
# FIXPROOF_LOCAL_PATH_ROOTS=/home/you/projects

# Sandbox mode: "local" for development, "docker" when Docker is available
FIXPROOF_SANDBOX_MODE=local
FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true
```

> **Never commit `.env`** — it is in `.gitignore`.

---

### 2 · Backend (FastAPI)

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

API docs live at **http://localhost:8000/docs**

---

### 3 · Frontend (React + Vite)

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** — pick a bundled example case, hit **Run**, and read the certificate.

---

### 4 · Verify Nebius / Nemotron connection

```bash
python scripts/check_nebius.py
```

---

### 5 · Launch the Live Local File Sync Worker

Open a third terminal in the root of **the project you want to repair**:

```bash
# Basic — watches the current directory, auto-detects the active FixProof project
python /path/to/fixproof/sync_worker.py

# Explicit — point at a directory and a known project ID
python /path/to/fixproof/sync_worker.py \
  --dir /path/to/your/project \
  --project-id <id-from-the-ui> \
  --debounce 0.3

# Custom backend URL
python /path/to/fixproof/sync_worker.py --url http://localhost:8000/api/v1/project/sync
```

Every **Ctrl+S** in your editor now triggers a sandboxed test run and streams the result back to the React dashboard over WebSocket — no browser refresh needed.

---

### 6 · Run backend unit tests

```bash
cd backend
pytest -q
```

Expected output: all tests pass in under 30 seconds without a network connection or a running Docker daemon.

---

### 7 · Docker Compose (full stack)

```bash
docker compose up --build
```

---

## 🧪 Comprehensive Testing Traceability

The entire backend is covered by a dedicated test module for every major subsystem. Tests run offline — no API keys, no Docker daemon, no network access required.

| Test module | Subsystem | What is verified |
|---|---|---|
| `test_security.py` | Differential SAST Engine | All 6 rule classes (B101–B203) with true-positive and true-negative cases; multi-file directory scan; baseline vs post-patch delta comparison; fail-open behaviour on scanner exceptions; `SecurityScanResult` schema; `VulnerabilityFinding.fingerprint()` stability |
| `test_multi_lang.py` | Multi-Language Factory | Language auto-detection for Python / JS / Go and all fallback/priority edge cases; boundary map disjointness; Vitest JSON parser (all-pass, failures, line numbers, malformed input); `go test -json` NDJSON parser (pass/fail/file+line extraction, partial lines); factory returns correct runner for each language; `ProjectStore._finish()` accepts JS and Go stubs |
| `test_sync.py` | Live Local File Sync | `sync_worker.py` ignore filters (systemic dirs, temp files, hidden files); debounce coalescing (3 rapid events → 1 dispatch); `POST /project/sync` writes file + runs tests + returns result; file deletion flow; path-traversal protection (400 on `../../`); WebSocket connection lifecycle; `SyncConnectionManager.broadcast()` delivers to all subscribers |
| `test_github_pr.py` | Git Data API / PR Engine | Full PR lifecycle against an in-memory PyGithub stand-in; branch name collision retry; existing-PR reuse (`reused=True`); all stable error codes (`TOKEN_EXPIRED`, `PATCH_CONFLICT`, `RATE_LIMITED`, `SSO_REQUIRED`, `INSUFFICIENT_PERMISSIONS`, `NOT_FOUND`, `BRANCH_CONFLICT`, `REPO_ARCHIVED`); PR body construction (root cause, adversarial test table, evidence table, conditions, footer); `@mention` defanging in model-authored text |
| `test_patching.py` | Patch Scope Validation | `git apply` integration; traversal rejection; test-file edit rejection; config-file edit rejection; `touched_paths()` extraction |
| `test_verdict.py` | Verdict Policy | All verdict transitions; `VERIFIED` vs `VERIFIED_WITH_CONDITIONS` rules; policy sealing |
| `test_pipeline.py` | Orchestration Pipeline | End-to-end workflow with scripted model doubles; bounded repair loop; repeated-patch detection |
| `test_api.py` / `test_api_projects.py` | FastAPI Routes | Project CRUD; investigation lifecycle; re-verify endpoint; certificate retrieval; PR endpoint wiring |
| `test_sandbox_local.py` / `test_docker_sandbox.py` | Sandbox Adapters | Process sandbox scrub; timeout enforcement; Docker adapter command construction |
| `test_explanation.py` | Explanation Engine | Structured root-cause + fix narrative generation |
| `test_codegraph.py` | Python AST + Dep Graph | Import resolution; call graph construction; affected-file selection |
| `test_grounding.py` | Spec Grounding | Quote extraction; mechanical grounding check; ungrounded test classification |
| `test_contest.py` | Contradictory Attack Detection | Cross-attempt conflict detection; least-bad attempt selection |
| `test_llm_client.py` | Nebius Client | Retry logic; JSON validation; usage accumulation |
| `test_suite.py` | JUnit XML Parser | pytest exit-code mapping; failure extraction; edge cases (empty suites, malformed XML) |
| `test_parsing.py` | NDJSON / Vitest Parsing | Shared parser edge cases |
| `test_scan.py` | Project Scan | Failing-test discovery; repro target validation |
| `test_projects.py` | Project Store | Zip upload; git clone; local path allowlist enforcement |
| `test_eval_cases.py` | Benchmark Harness | Case loading; oracle validation |
| `test_infra_errors.py` | Error Propagation | Sandbox unavailable; model config errors; certificate-not-found paths |
| `test_edits.py` | Workspace Edits | Atomic write; rollback on failure |
| `test_workflow.py` | Full Workflow | Scripted end-to-end with all check outcomes exercised |

---

## 📐 Repository Layout

```text
fixproof/
├── backend/
│   ├── app/
│   │   ├── agents/          # investigator, fixer, verification planner (Nemotron)
│   │   ├── api/             # FastAPI routes + WebSocket sync manager
│   │   ├── codegraph/       # Python AST + NetworkX dependency graph
│   │   ├── llm/             # Nebius Token Factory client (retries, usage tracking)
│   │   ├── orchestrator/    # typed state + workflow engine
│   │   ├── repair/          # patch application + scope validation
│   │   ├── runners/         # multi-language factory + parsers
│   │   │   ├── parsers/     # gotest_parser.py (NDJSON), vitest_parser.py (JSON)
│   │   │   ├── base_runner.py
│   │   │   ├── boundary.py  # editable/locked file classification
│   │   │   ├── detector.py  # language auto-detection
│   │   │   ├── go_runner.py
│   │   │   ├── js_runner.py
│   │   │   └── python_runner.py
│   │   ├── sandbox/         # local + docker execution adapters
│   │   ├── tools/           # filesystem / git / search helpers
│   │   ├── verification/    # deterministic verification engine + verdict policy
│   │   ├── certificate.py   # Fix Certificate model + SHA-256 seal
│   │   ├── github_pr.py     # Git Data API → Pull Request engine
│   │   ├── security.py      # pure-Python AST SAST scanner (B101–B203)
│   │   └── main.py
│   ├── tests/               # 22 test modules, all offline
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/                 # React 19 + TypeScript + Vite + Tailwind CSS v4
│   └── Dockerfile
├── evals/                   # benchmark harness + 2 validated cases
├── examples/
│   └── buggy-python-app/    # bundled target used for development
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   └── verification-policy.md
├── scripts/
│   ├── check_nebius.py      # validates Nebius endpoint + model ID
│   ├── setup.ps1
│   └── setup.sh
├── sync_worker.py           # Live Local File Sync CLI
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## 🧠 What the Model Does vs. What Tools Do

| Step | Who |
|---|---|
| Root-cause hypotheses, patch code, adversarial test authoring | NVIDIA Nemotron via Nebius Token Factory |
| Reproduction run, regression run, adversarial test execution, verdict | Deterministic pipeline |
| Differential SAST scan (B101–B203) | Pure-Python AST engine (no model) |
| Patch scope validation, `git apply`, traversal check | Rules engine (no model) |
| Branch creation, commit, PR body, mergeability poll | GitHub Git Data API (no model) |
| Real-time sync, debounce, filesystem watch | `sync_worker.py` + `watchdog` (no model) |

The Fix Certificate records this attribution plus live model usage (calls, tokens, model ID, policy version).

---

## ⚙️ Environment Variables Reference

```env
# ── AI ───────────────────────────────────────────────────────────────────────
NEBIUS_API_KEY=                            # required for live Nemotron calls
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b

# ── Sandbox ──────────────────────────────────────────────────────────────────
FIXPROOF_SANDBOX_MODE=local               # "local" | "docker"
FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true # dev only

# ── GitHub ───────────────────────────────────────────────────────────────────
FIXPROOF_GITHUB_TOKEN=                    # optional; or pass X-GitHub-Token header

# ── Projects ─────────────────────────────────────────────────────────────────
FIXPROOF_LOCAL_PATH_ROOTS=               # colon-separated allowlist for local folders
FIXPROOF_MAX_PROJECT_MB=50              # zip upload size limit
```

---

## 🔐 Safety Model

- Target repositories execute only inside an isolated sandbox. API keys and GitHub credentials are **never** injected into the target execution environment.
- Patches are validated for scope (no test/config edits) and traversal before any execution.
- The SAST scanner runs in the backend process — the target project is never executed during scanning.
- GitHub tokens sent in `X-GitHub-Token` are used for a single request and discarded; they are never written to disk or logs.

See [`docs/verification-policy.md`](docs/verification-policy.md) for the full policy.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| AI model | NVIDIA Nemotron via Nebius Token Factory |
| Backend | Python 3.12, FastAPI, Pydantic v2 / pydantic-settings |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Test runners | pytest (JUnit XML), Vitest (JSON), go test (NDJSON) |
| Code analysis | Python `ast` (built-in), NetworkX |
| GitHub integration | PyGithub (Git Data API) |
| File watching | watchdog |
| Containerization | Docker, Docker Compose |

---

## 🤝 Hackathon Integrity Pledge

> *Add a feature to this README as "implemented" only when there is code and a test proving it.*

Every ✅ in this document is backed by at least one test in `backend/tests/`. Every ⛔ is an honest admission. The Fix Certificate itself enforces this discipline: it is physically impossible to issue a `VERIFIED` certificate without the deterministic pipeline executing and passing — the model cannot self-certify.

---

## License

MIT — see [`LICENSE`](LICENSE).
