# FixProof

> **AI proposes the fix. Evidence earns the merge.**

FixProof is an **automated AI software repair and verification platform** that uses NVIDIA Nemotron to propose fixes and deterministic verification tools to evaluate them. FixProof focuses on Python repositories and pytest-based testing.

Its core objective is to ensure that AI-generated patches are not trusted merely because an LLM claims they are correct. Every patch must go through executable verification, patch-scope validation, security analysis, and evidence-grounded adversarial testing before receiving a verdict.

Built for the **Nebius × NVIDIA Global AI Hackathon 2026** · Coding & Agentic Engineering track.

---

## 🏗️ Architecture at a Glance

```text
Your Editor (Python)
       │  watchdog + 300ms debounce
       ▼
sync_worker.py  ──POST──►  FastAPI Backend  ──WebSocket──►  React Frontend
                            │
                ┌───────────┴─────────────────────────────────────┐
                │          14-Step Verification Pipeline          │
                │                                                 │
                │  1. Ingest: GitHub URL, ZIP, or local folder    │
                │  2. Python project inspection & config check    │
                │  3. Pytest test discovery & execution           │
                │  4. Original failure reproduction (red run)     │
                │  5. AST analysis & dependency investigation     │
                │  6. Nemotron: root-cause & minimal patch        │
                │  7. Patch scope validation & git apply          │
                │  8. Regression verification (green run)         │
                │  9. Differential Python AST SAST (B101–B203)    │
                │ 10. Spec-grounded adversarial test generation   │
                │ 11. Bounded repair loop (counterexample → fix)  │
                │ 12. Deterministic verdict policy evaluation     │
                │ 13. SHA-256-sealed Fix Certificate issuance     │
                │ 14. GitHub Git Data API → Pull Request          │
                └─────────────────────────────────────────────────┘
```

---

## 🌟 Project Hook & Vision

The software industry has a trust problem: AI models that write code are also trusted to declare that code correct. FixProof breaks that conflict of interest.

Every patch goes through five independent gates before it is promoted:

| Gate | Who runs it |
|---|---|
| Bug reproduction (fail → pass) | Deterministic sandbox + pytest |
| Patch scope & traversal safety | Deterministic rules engine |
| Full regression suite | Deterministic sandbox + pytest |
| Differential SAST security scan | Pure-Python AST engine (B101–B203) |
| Spec-quoted adversarial attack tests | Deterministic sandbox + Nemotron authorship |

Only patches that clear every gate receive a **Fix Certificate** — a tamper-evident, SHA-256-sealed record of every executable piece of evidence. That certificate, not the model's confidence score, earns the merge.

---

## 🏗️ Core Architecture & Features

### 🔒 Isolation & Verification Engine

- **Sandbox adapters** — FixProof isolates test execution behind a pluggable sandbox interface (`SandboxRunner`):
  - **Local process sandbox** (`FIXPROOF_SANDBOX_MODE=local`): Scrubs environment variables, enforces timeouts, and applies POSIX resource limits (`rlimits` on supported Unix systems; unavailable on Windows). *Crucial limitation: Local mode provides no filesystem isolation or root jail. It is never safe for arbitrary untrusted repository execution.*
  - **Docker sandbox** (`FIXPROOF_SANDBOX_MODE=docker`): Constructs container execution commands with `--network none`, read-only source mounts, a non-root user, and dropped capabilities (`cap-drop=ALL`). Command construction is covered by unit tests, but the implementation has not been validated through live production execution against a running Docker daemon.
  - **Bubblewrap sandbox** (`FIXPROOF_SANDBOX_MODE=bwrap`): Constructs Linux user-namespace commands with read-only root mounts and isolated tmpfs workspaces. Command construction is covered by unit tests, but the implementation has not been validated through live production execution and requires host Linux kernel user-namespace support.
- **Deterministic verdict policy v1** — A strict policy engine that aggregates executable check outcomes. The policy is designed to prevent a `VERIFIED` verdict unless all mandatory checks complete successfully (`reproduction_red`, `patch_applies_in_scope`, `reproduction_green`, `regression`, and `adversarial`). The LLM cannot directly assign or override the verdict.
- **Sealed Fix Certificate** — A tamper-evident (not tamper-proof) record of verification evidence. Payload integrity is verified on read by recomputing the SHA-256 hash over the canonical JSON payload (excluding the seal itself) and comparing it against the stored `certificate_sha256`. Any modification to the certificate text or outcomes invalidates the seal. The certificate records root cause, patch diff, attack test outcomes, regression results, differential SAST findings, model usage (calls + tokens), and execution conditions.
- **Human re-verify flow** — A code reviewer can dispute one or more spec-grounded adversarial tests. FixProof re-runs all checks against the existing patch excluding only the disputed tests, recording the dispute reason in the certificate. No model calls are made during re-verification.

### 🐍 Python & Pytest Toolchain

FixProof operates strictly on Python projects using pytest. Test discovery and execution support two distinct workflows:

- **Targeted Test Execution (Workflow A — Fast Path):** Users can supply a specific test file path or full pytest node ID, including class methods (e.g., `tests/test_orders.py::TestOrders::test_total`) and parameterized tests (e.g., `tests/test_calc.py::test_add[1-2]`). FixProof validates the target against path traversal, absolute paths, non-Python extensions, and complete node existence via a pre-pass collection check before running `pytest <target>` directly in the sandbox.
- **Global Test Discovery (Workflow B — Default Path):** When no test ID is provided, FixProof performs a collection pre-pass to discover tests and detect missing dependencies, followed by execution of the full baseline test suite.

| Phase | Pytest Invocation | Purpose | Execution & Security Semantics |
|---|---|---|---|
| **Targeted Test Scan** | `pytest <clean_node_id> -o junit_family=xunit1` | Pre-validates complete node ID via collection, then executes only the user-specified test. | Executes only the targeted test in the sandbox after strict path and node validation. |
| **Test Collection (Scan)** | `pytest --collect-only -q -p no:cacheprovider` | Discovers test node IDs and flags missing imports or syntax errors in ≤ 30s. | Does not execute test functions. However, **collection is not a read-only operation**: importing test modules, executing `conftest.py`, and running pytest plugin hooks execute repository-controlled Python code. **Collection must strictly run inside the sandbox under the same security boundaries as test execution.** |
| **Full Suite Baseline** | `pytest --continue-on-collection-errors -o junit_family=xunit1 --junitxml=...` | Maps pre-patch failures and establishes baseline suite health. | Executes all discovered tests in the sandbox. |
| **Original Failure Reproduction** | `pytest <target_node_id> -o junit_family=xunit1` | Verifies that the identified bug fails before the patch (red run). | Executes only the reproduction target in the sandbox. |
| **Post-Patch Regression** | `pytest --continue-on-collection-errors -o junit_family=xunit1 --junitxml=...` | Confirms the patch fixes the target and introduces no regressions (green run). | Executes the full test suite against the patched workspace in the sandbox. |
| **Adversarial Attack Suite** | `pytest fixproof_adv/test_attack.py -o junit_family=xunit1` | Executes model-authored attack tests grounded in project specifications. | Executes only new adversarial tests in an isolated subdirectory in the sandbox. |

**Scope Boundary Validation** (`backend/app/repair/patching.py`):
Patches must modify only project implementation code. Any diff touching test files (`test_*.py`, `*_test.py`, `tests/`), test configuration (`conftest.py`, `pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`), or containing path traversal (`..`, leading `/`, `.git`) is immediately rejected before execution.

### 🛡️ Security Perimeter — Differential SAST Engine

`backend/app/security.py` is a **zero-dependency, pure-Python AST vulnerability scanner** that performs differential analysis: it scans the pre-patch baseline and the post-patch workspace, reporting only **net-new** vulnerabilities introduced by the patch. Pre-existing issues in the repository are recorded but do not fail the patch.

| Rule | Category | Severity | Detection Method |
|---|---|---|---|
| **B101** | SQL Injection | HIGH | Dynamic values in `execute()`, `executemany()`, `raw()`, `filter()`, `extra()`, `RawSQL()` (detects f-strings, `%`-formatting, `.format()`, string concatenation) |
| **B102** | Command Injection | HIGH | `subprocess.*` with `shell=True` and dynamic arguments; `os.system()` / `os.popen()` with dynamic arguments |
| **B103** | Path Traversal | HIGH | `open()` or `Path()` called with dynamically constructed paths (f-strings, string concatenation) |
| **B201** | Hardcoded Secret | MEDIUM | Assignment of string literals to identifiers matching credential patterns (`password`, `secret`, `api_key`, `token`, `private_key`) |
| **B202** | Unsafe Deserialization | HIGH/MEDIUM | `pickle.loads()` / `pickle.load()` / `Unpickler`; `yaml.load()` without explicit safe `Loader=` |
| **B203** | Weak Crypto Hash | MEDIUM | `hashlib.md5()` / `hashlib.sha1()` (flags both `import hashlib` and `from hashlib import ...` forms) |

The scanner resolves import aliases (`import X as Y`, `from X import Y as Z`).

**Scan Failure & Inconclusive Semantics:**
Scanning is fail-open for pipeline availability: scanner exceptions do not abort the overall repair process. However, scanner exceptions, incomplete scans, or zero successfully scanned files produce an inconclusive security result (`CheckOutcome.ERROR` / unverified status), never a clean scan. **A failed security scan must never be interpreted as zero vulnerabilities.**

### ⚡ Real-Time Sync Loop

- **`sync_worker.py`** — A standalone CLI watcher based on `watchdog` that monitors your local Python project. A 300 ms debounce buffer coalesces rapid file saves into a single atomic payload.
  - Ignores: `.git`, `__pycache__`, `.fixproof_projects`, `node_modules`, `.venv`, `venv`, editor temporary files (`.swp`, `.tmp`, `~`, `.DS_Store`).
  - Watches Python source files and synchronizes changes with the active project workspace.
- **`POST /api/v1/project/sync`** — Atomically updates workspace files with traversal checks, executes a sandboxed test pass, and emits WebSocket notifications: `TESTS_RE_RUNNING` → `RUN_COMPLETE`.
- **`WebSocket /api/v1/ws/sync`** — Persistent real-time event channel connected to the React frontend.

### 🚀 Automated Cloud Delivery — GitHub Git Data API Engine

`backend/app/github_pr.py` opens pull requests **purely through the GitHub REST API** without requiring a local clone, git credentials on disk, or `git push`.

**Workflow:**
1. Validates the certificate verdict (`VERIFIED` or `VERIFIED_WITH_CONDITIONS`).
2. Re-validates patch scope rules against the target repository tree.
3. Authenticates via `PyGithub` using a fine-grained token (`X-GitHub-Token` header or `FIXPROOF_GITHUB_TOKEN`).
4. Reads the target branch's tree using the Git Data API.
5. Applies the unified diff in a clean temporary directory.
6. Uploads updated blobs, creates a Git tree, and generates a commit.
7. Creates a branch `fixproof/patch-<id>` (with collision retries).
8. Opens the Pull Request containing root-cause analysis, adversarial test evidence, verification outcomes, and certificate SHA-256 seal.
9. Polls mergeability status synchronously. Publishing an already-opened certificate reuses the existing PR (`reused=True`).

**Stable machine-readable error codes:** `TOKEN_EXPIRED`, `TOKEN_MISSING`, `PATCH_CONFLICT`, `BRANCH_CONFLICT`, `RATE_LIMITED`, `INSUFFICIENT_PERMISSIONS`, `SSO_REQUIRED`, `NOT_FOUND`, `EMPTY_REPOSITORY`, `REPO_ARCHIVED`, `NO_CHANGES`, `PR_ALREADY_EXISTS`, `GITHUB_UNREACHABLE`.

---

## 📊 Current Capabilities — Honest Status Matrix

> Legend: ✅ implemented and tested · 🟡 implemented, not yet exercised live · ⛔ not implemented

| Capability | Status | Implementation Details |
|---|---|---|
| **Reproduce original failure** | ✅ | Pytest exit codes & JUnit XML parsed; stops if failure cannot be reproduced |
| **Targeted test execution** | ✅ | Validates and executes specific pytest file paths or node IDs (including class & parameterized tests) |
| **Patch scope validation** | ✅ | Rejects edits to tests, test configurations, dotfiles, and path traversal |
| **Regression verification** | ✅ | Re-runs full pytest test suite after patch application |
| **Model-authored adversarial tests** | ✅ / 🟡 | Tested with scripted doubles (✅); live generation requires valid Nebius key (🟡) |
| **Spec-grounded adversarial attacks** | ✅ | Quotes verified mechanically against repo text; ungrounded failures yield condition, not veto |
| **Contradictory attack detection** | ✅ | Detects conflicting attack tests across iterations; selects least-bad attempt |
| **Counterexample repair loop** | ✅ | Bounded retries, counterexample feedback to fixer, repeated-patch detection |
| **Deterministic verdict policy v1** | ✅ | Strict rule evaluation designed to prevent `VERIFIED` without passing checks; LLM cannot override |
| **Process sandbox (`local`)** | ✅ | Scrubbed environment, POSIX `rlimits` (Unix only), timeouts; **no filesystem isolation** |
| **Docker sandbox (`docker`)** | ✅ | `--network none`, read-only source mount, cap-drop; command generation unit-tested, unvalidated in live production |
| **Bubblewrap sandbox (`bwrap`)** | 🟡 | Linux user namespaces, read-only root, tmpfs workspace; command generation unit-tested, unvalidated in live production |
| **Deterministic Python/Pytest pipeline** | ✅ | Distinguishes targeted scans, collection pre-pass, and full execution; collection runs sandboxed |
| **JUnit XML streaming parser** | ✅ | Normalizes test outcomes, error messages, and test node IDs |
| **Differential SAST engine** | ✅ | Pure-Python AST rules B101–B203; reports net-new vulnerabilities; failures yield inconclusive result |
| **Real-time local file sync** | ✅ | `sync_worker.py` + `POST /project/sync` + `WebSocket /ws/sync` |
| **GitHub PR generation** | ✅ | Git Data API; branch creation, blob upload, commit, PR body generation |
| **Project sources** | ✅ | ZIP upload, GitHub URL clone, local directory (with path allowlist) |
| **Nebius / Nemotron client** | 🟡 | Client retries, JSON validation, usage tracking; validated via `check_nebius.py` |
| **Benchmark harness** | ✅ / ⛔ | Benchmark runner and evaluation cases implemented (✅); **no live model results published** (⛔) |
| **Property-based testing (Hypothesis)** | ⛔ | Stubbed in `property_tests.py`; not integrated into repair loop |
| **Mutation testing** | ⛔ | Stubbed in `mutation.py`; not implemented |
| **Nebius Serverless Jobs / Sandboxes** | ⛔ | Not implemented; uses local/Docker/bwrap runners |
| **Arbitrary untrusted repo execution** | ⛔ | LocalSandbox lacks filesystem isolation; untrusted repos cannot be safely executed without verified container isolation |

> [!NOTE]
> In local process sandbox mode, verdicts are capped at `VERIFIED_WITH_CONDITIONS` due to the lack of filesystem isolation.
> No benchmark performance metrics are published because the benchmark suite has not been run against a live model at scale.

---

## 🔒 Security Model & Sandbox Disclosures

FixProof enforces strict boundaries between untrusted code, the AI model, and the host system:

1. **Sandbox Guarantees & Isolation Differences:**
   - **Local Sandbox (`FIXPROOF_SANDBOX_MODE=local`):** Executes pytest processes on the host. It scrubs environment variables, enforces timeouts, and applies POSIX `rlimits` on supported Unix systems (resource limits are not supported on Windows). **LocalSandbox provides no filesystem isolation or root jail.** Any code executed by pytest can read or write host files accessible to the user process. **LocalSandbox is never safe for arbitrary untrusted repository execution.**
     > [!CAUTION]
     > Setting `FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true` is strictly intended for local development and testing with trusted code. **Never enable unsafe local execution in production or when handling untrusted repositories.**
   - **Docker Sandbox (`FIXPROOF_SANDBOX_MODE=docker`):** Configures containers with `--network none`, read-only source mounts, a non-root user, and dropped Linux capabilities. While command construction is verified by unit tests, **the Docker sandbox has not been validated through live production execution.** Unit tests of command construction do not prove secure runtime isolation.
   - **Bubblewrap Sandbox (`FIXPROOF_SANDBOX_MODE=bwrap`):** Configures unprivileged Linux user namespaces with a read-only root and private tmpfs workspace. Like the Docker adapter, command construction is unit-tested, but **it has not been validated through live production execution** and depends on host kernel support for user namespaces.

2. **Pytest Collection Security:**
   While `pytest --collect-only` does not invoke test functions, **collection is not a read-only operation.** During collection, pytest imports Python modules, runs top-level module code, executes `conftest.py` scripts, and invokes pytest plugin hooks. Because this executes repository-controlled code, **test collection must adhere to the exact same sandbox boundaries and resource limits as test execution.**

3. **Untrusted Code Execution:**
   Arbitrary untrusted repositories cannot be executed safely under `LocalSandbox`. True isolation requires validated container or namespace boundaries (`docker` or `bwrap`). In addition, repositories with missing system packages, native C extensions, or uninstalled dependencies will fail test collection or execution unless their runtime environment is pre-configured.

4. **Credential Isolation:**
   API keys (`NEBIUS_API_KEY`, `FIXPROOF_GITHUB_TOKEN`) are stored in backend memory and are **never** injected into the sandbox environment or exposed to the executing project. Tokens supplied via the `X-GitHub-Token` header are held only for the duration of the request and discarded.

5. **Static AST Analysis:**
   The SAST security scanner and dependency analyzer run in-process using Python's standard `ast` module. The target codebase is parsed statically and is **never executed** during security or dependency analysis. If the scanner encounters an error, incomplete scan, or analyzes zero files, the outcome is marked as an inconclusive check error (`CheckOutcome.ERROR`), never as zero vulnerabilities.

---

## 🚀 Quick Start & Installation

### Prerequisites

| Tool | Version | Required For |
|---|---|---|
| Python | 3.12+ | Backend, pytest runner, sync worker |
| Node.js | 20+ | Frontend (Vite + React) |
| Git | Recent | Patch application and Git Data API |
| Docker | Optional | Required only for `FIXPROOF_SANDBOX_MODE=docker` |

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

Edit `.env` to configure your environment:

```env
# ── AI Model Configuration ──────────────────────────────────────────────────
NEBIUS_API_KEY=<your-key>
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b

# ── Sandbox Configuration ───────────────────────────────────────────────────
# Options: "local" (development/testing), "docker" (containerized), "bwrap" (Linux)
FIXPROOF_SANDBOX_MODE=local

# Development setting only! Required when FIXPROOF_SANDBOX_MODE=local.
# WARNING: Local sandbox provides NO filesystem isolation. Never set to true in production.
FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true

# ── GitHub PR Integration (Optional) ─────────────────────────────────────────
FIXPROOF_GITHUB_TOKEN=<fine-grained-PAT>

# ── Project Storage ─────────────────────────────────────────────────────────
FIXPROOF_PROJECTS_DIR=./.fixproof_projects
FIXPROOF_MAX_PROJECT_MB=50
# FIXPROOF_LOCAL_PATH_ROOTS=/path/to/trusted/projects
```

> **Never commit `.env`** — it is listed in `.gitignore`.

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

FastAPI interactive documentation is available at **http://localhost:8000/docs**.

---

### 3 · Frontend (React + Vite)

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

---

### 4 · Verify Nebius / Nemotron Connection

```bash
python scripts/check_nebius.py
```

This verifies API connectivity, checks key validity, and confirms model availability.

---

### 5 · Launch the Live Local File Sync Worker

Open a third terminal in the root of the **Python project you want to repair**:

```bash
# Basic — monitors current directory and auto-syncs with the active FixProof project
python /path/to/fixproof/sync_worker.py

# Explicit — specify project directory and ID
python /path/to/fixproof/sync_worker.py \
  --dir /path/to/your/project \
  --project-id <id-from-the-ui> \
  --debounce 0.3
```

Saving a file in your editor triggers an immediate sandboxed pytest run and pushes real-time results to the React dashboard over WebSocket.

---

### 6 · Run Backend Unit Tests

```bash
cd backend
pytest -q
```

All 24 test modules run offline without external API keys, Docker, or network dependencies.

---

### 7 · Docker Compose (Full Stack)

```bash
docker compose up --build
```

---

## 🧪 Testing Traceability

The backend includes 24 offline test modules covering all pipeline stages:

| Test Module | Subsystem | Verification Scope |
|---|---|---|
| `test_scan.py` | Test Discovery & Scan | Workflow A (targeted scan) and Workflow B (global scan); pytest collection parsing; missing-dependency detection; reproduction target validation (path traversal, nonexistent functions, class & parameterized node IDs); monotonic timeout enforcement |
| `test_suite.py` | JUnit XML Parser | Pytest exit-code mapping (0–5); XML streaming outcome normalization; failure extraction |
| `test_security.py` | Differential SAST Engine | AST rules B101–B203 true-positive/true-negative detection; baseline vs post-patch delta analysis; fail-open error handling; fingerprint stability |
| `test_sync.py` | Live Local File Sync | `sync_worker.py` debounce coalescing; path-traversal rejection; `POST /project/sync` atomic writes; WebSocket event broadcasting |
| `test_github_pr.py` | Git Data API / PR Engine | Full PR lifecycle via in-memory PyGithub double; branch collision retry; PR reuse; error codes; PR markdown generation |
| `test_patching.py` | Patch Scope Validation | Rejection of edits to tests/configs; path-traversal prevention; hunk line-ending adaptation (`\n` vs `\r\n`) |
| `test_verdict.py` | Verdict Policy | Deterministic policy transitions; `VERIFIED` vs `VERIFIED_WITH_CONDITIONS`; certificate payload sealing |
| `test_pipeline.py` | Orchestration Pipeline | End-to-end repair loop with scripted models; counterexample feedback; repeated-patch detection |
| `test_api.py` / `test_api_projects.py` | FastAPI Endpoints | Project ingestion (ZIP, git clone, local); investigation lifecycle; re-verify endpoint; targeted scan endpoint |
| `test_sandbox_local.py` | Local Sandbox | Environment scrubbing; POSIX `rlimits`; execution timeout handling |
| `test_docker_sandbox.py` | Docker Sandbox | Docker CLI command construction (`--network none`, read-only mount, cap-drop) |
| `test_sandbox_bwrap.py` | Bubblewrap Sandbox | Namespace command construction; tmpfs workspace isolation |
| `test_codegraph.py` | Python AST & Call Graph | Static import resolution; call-graph construction; affected file identification |
| `test_grounding.py` | Spec Grounding | Exact quote extraction from README/docstrings; mechanical verification of adversarial tests |
| `test_contest.py` | Contradictory Test Detection | Detection of conflicting attack tests across iterations; least-bad attempt selection |
| `test_llm_client.py` | Nebius Client | Retry logic; JSON schema validation; token and call tracking |
| `test_parsing.py` | LLM Response Parsing | Markdown code-block extraction for diffs and adversarial tests |
| `test_explanation.py` | Explanation Engine | Structured root-cause analysis and repair narrative generation |
| `test_projects.py` | Project Store | Project workspace creation; git cloning; ZIP extraction; path allowlist enforcement |
| `test_eval_cases.py` | Benchmark Harness | Benchmark case loading; oracle validation |
| `test_infra_errors.py` | Error Handling | Sandbox unavailable; model timeout/errors; missing certificates |
| `test_edits.py` | Workspace Edits | Atomic file modifications; rollback on application error |
| `test_workflow.py` | Workflow Integration | End-to-end multi-step state verification with scripted doubles |

---

## 📐 Repository Structure

```text
fixproof/
├── backend/
│   ├── app/
│   │   ├── agents/          # Investigator, fixer, planner, reviewer (Nemotron prompts & models)
│   │   ├── api/             # FastAPI REST endpoints + WebSocket sync manager
│   │   ├── codegraph/       # Python AST analysis + dependency graph
│   │   ├── llm/             # Nebius Token Factory client (retries, usage tracking)
│   │   ├── orchestrator/    # Typed state machine + workflow graph
│   │   ├── pipeline/        # Repair pipeline runner + factory
│   │   ├── repair/          # Patch application, scope boundary validation, diff edits
│   │   ├── sandbox/         # Local, Docker, bubblewrap, and base sandbox adapters
│   │   ├── tools/           # Filesystem, git, and search utilities
│   │   ├── verification/    # Pytest runner, scan, suite parser, grounding, contest, verdict
│   │   ├── certificate.py   # Fix Certificate data model + SHA-256 seal
│   │   ├── config.py        # Pydantic-settings configuration
│   │   ├── evaluation.py    # Benchmark evaluation models
│   │   ├── explanation.py   # Root-cause and fix narrative generation
│   │   ├── github_pr.py     # GitHub Git Data API → Pull Request engine
│   │   ├── main.py          # FastAPI application entrypoint
│   │   ├── projects.py      # Project store (ZIP, git clone, local folder)
│   │   └── security.py      # Pure-Python AST SAST scanner (B101–B203)
│   ├── tests/               # 24 test modules, all offline
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── src/                 # React 19 + TypeScript + Vite + Tailwind CSS v4
│   └── Dockerfile
├── evals/                   # Benchmark harness + validated Python evaluation cases
├── examples/                # Bundled Python target applications for testing & demo
│   ├── buggy-python-app/
│   ├── dedupe-app/
│   ├── intervals-app/
│   ├── paginate-app/
│   ├── parse-bool-app/
│   ├── slugify-app/
│   └── truncate-app/
├── docs/
│   ├── architecture.md
│   ├── audit.md
│   ├── roadmap.md
│   └── verification-policy.md
├── scripts/
│   ├── check_nebius.py      # Validates Nebius endpoint + model ID
│   ├── setup.ps1
│   └── setup.sh
├── sync_worker.py           # Live Local File Sync CLI
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## 🧠 What the Model Does vs. What Tools Do

| Step | Responsible Component | Implementation |
|---|---|---|
| Root-cause hypotheses, patch proposal, adversarial attack tests | NVIDIA Nemotron via Nebius Token Factory | LLM prompted with sanitized code context & test tracebacks |
| Test discovery, failure reproduction, regression verification | Deterministic sandbox + pytest | Subprocess execution in isolated environment |
| Differential SAST security scanning (B101–B203) | Pure-Python AST engine | In-memory AST comparison (`security.py`) |
| Patch scope & path-traversal validation | Rules engine | Unified diff inspection (`patching.py`) |
| Pull request creation & commit authoring | GitHub Git Data API | PyGithub REST operations (`github_pr.py`) |
| Real-time file synchronization & debounce | Standalone CLI watcher | `watchdog` + `sync_worker.py` |
| Verdict policy & Fix Certificate sealing | Deterministic policy engine | SHA-256 cryptographic seal (`certificate.py`) |

The Fix Certificate records model usage metrics (model ID, call count, token usage) alongside all deterministic verification evidence.

---

## ⚙️ Environment Variables Reference

```env
# ── AI Model (Nebius Token Factory) ──────────────────────────────────────────
NEBIUS_API_KEY=                            # Required for live Nemotron calls
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b
FIXPROOF_LLM_TIMEOUT_SECONDS=120.0
FIXPROOF_LLM_MAX_RETRIES=2

# ── Sandbox Execution ────────────────────────────────────────────────────────
FIXPROOF_SANDBOX_MODE=local                # "local" | "docker" | "bwrap"
FIXPROOF_ALLOW_UNSAFE_LOCAL_EXECUTION=true  # Dev/testing only. No filesystem isolation!
FIXPROOF_SANDBOX_IMAGE=fixproof-sandbox:latest

# ── GitHub Integration ───────────────────────────────────────────────────────
FIXPROOF_GITHUB_TOKEN=                     # Optional server token; or send X-GitHub-Token header

# ── Project Management ───────────────────────────────────────────────────────
FIXPROOF_PROJECTS_DIR=./.fixproof_projects
FIXPROOF_MAX_PROJECT_MB=50
FIXPROOF_LOCAL_PATH_ROOTS=                 # Comma-separated allowlist for local directories
FIXPROOF_MAX_REPAIR_ITERATIONS=3           # Bounded repair loop limit (default: 3)
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| AI model | NVIDIA Nemotron via Nebius Token Factory |
| Backend | Python 3.12, FastAPI, Pydantic v2 / pydantic-settings |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Test runner | pytest (with JUnit XML streaming reporter) |
| Static analysis | Python `ast` (built-in), NetworkX |
| GitHub integration | PyGithub (Git Data API) |
| File watching | watchdog |
| Containerization | Docker, Docker Compose |

---

## 🤝 Hackathon Integrity Pledge

> *Add a feature to this README as "implemented" only when there is code and a test proving it.*

Every ✅ in this document is backed by at least one offline test in `backend/tests/`. Every ⛔ is an honest admission. The Fix Certificate enforces this discipline: the deterministic verdict policy is designed to prevent issuing a `VERIFIED` certificate unless all mandatory verification checks execute and pass. The LLM cannot directly assign or override the verdict.

---

## License

MIT — see [`LICENSE`](LICENSE).
