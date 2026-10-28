export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type Verdict =
  | 'verified'
  | 'verified_with_conditions'
  | 'not_verified'
  | 'insufficient_evidence'

export type Outcome = 'passed' | 'failed' | 'error' | 'skipped' | 'not_run'

export type Check = {
  name: string
  role: string
  required: boolean
  outcome: Outcome
  summary: string
  command: string | null
  exit_code: number | null
  duration_seconds: number | null
  tests_executed: number
  counterexamples: string[]
  stdout_sha256: string | null
  output_excerpt: string
}

export type Iteration = {
  index: number
  patch_sha256: string | null
  summary: string
  rationale: string
  diff: string
  changed_files: string[]
  checks: Check[]
  counterexamples: string[]
  feedback_to_fixer: string | null
  note: string
  test_results: Record<string, string>
  score: number | null
}

export type AdversarialTest = {
  name: string
  rationale: string
  spec_quote: string
  grounded: boolean
  grounding_note: string
  key: string
  disputed: boolean
  dispute_reason: string
  code: string
}

export type Certificate = {
  certificate_id: string
  policy_version: string
  created_at: string
  source_label: string
  snapshot_sha256: string
  issue: string
  model: {
    provider: string
    model: string
    calls: number
    prompt_tokens: number
    completion_tokens: number
    latency_seconds: number
  }
  sandbox: {
    kind: string
    isolation: string
    network_blocked: boolean
    isolation_self_tested: boolean
    notes: string[]
  }
  tool_attribution: Record<string, string>
  hypotheses: { title: string; rationale: string; status: string }[]
  selected_root_cause: string
  confidence_notes: string
  final_patch: string | null
  final_patch_sha256: string | null
  changed_files: string[]
  patch_summary: string
  checks: Check[]
  unexecuted_checks: string[]
  iterations: Iteration[]
  adversarial_tests: AdversarialTest[]
  max_iterations: number
  selected_attempt: number | null
  contested: string[]
  derived_from: string | null
  reverified_attempt: number | null
  limitations: string[]
  disclaimers: string[]
  verdict: Verdict
  verdict_reasons: string[]
  timeline: { at: string; stage: string; message: string }[]
  certificate_sha256: string
}

export type TimelineEvent = { at: string; stage: string; message: string }

export type InvestigationState = {
  id: string
  stage: string
  error: string | null
  issue: string
  project_name: string | null
  example_case: string | null
  parent_id: string | null
  events: TimelineEvent[]
  certificate: Certificate | null
}

export type ProjectInfo = {
  id: string
  name: string
  origin: 'zip' | 'git' | 'local'
  origin_detail: string
  files: number
  bytes: number
  python_files: number
  test_files: number
}

export type FailingTest = { node_id: string; message: string }

export type ScanResult = {
  exit_code: number | null
  timed_out: boolean
  duration_seconds: number
  tests: number
  failed: number
  errors: number
  skipped: number
  failing_tests: FailingTest[]
  collection_errors: FailingTest[]
  missing_modules: string[]
  hint: string
  output_excerpt: string
}

export type AboutResponse = {
  name: string
  status: string
  nebius_model: string
  nebius_configured: boolean
  github_configured: boolean
  sandbox_mode: string
  example_cases: string[]
  example_issues: Record<string, string>
  project_sources: { zip: boolean; git: boolean; local: boolean }
  max_project_mb: number
  implemented_now: string[]
  not_implemented: string[]
}

export type BenchmarkTrial = {
  case: string
  mode: string
  trial: number
  accepted: boolean
  oracle_passed: boolean | null
  resolved: boolean
  false_accept: boolean
  false_reject: boolean
  iterations: number
  runtime_seconds: number
  prompt_tokens: number
  completion_tokens: number
  verdict: string
  error: string | null
}

export type ModeSummary = {
  trials: number
  resolved_rate: number
  false_acceptance_rate_of_accepted: number | null
  false_rejection_rate: number
  mean_iterations: number
  mean_runtime_seconds: number
  total_tokens: number
  errors: number
}

export type BenchmarkResponse =
  | { available: false }
  | {
      available: true
      file: string
      report: {
        environment: Record<string, unknown>
        trials: BenchmarkTrial[]
        notes: string[]
        summary: Record<string, ModeSummary>
      }
    }

/** An API failure. `code` is the backend's stable error code when it sent one. */
export class ApiError extends Error {
  code?: string
  constructor(message: string, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new Error('Cannot reach the FixProof backend. Is it running on ' + API_BASE + '?')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail
    const text = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join('; ')
      : (detail ?? `Request failed (${response.status})`)
    throw new ApiError(String(text), typeof body.code === 'string' ? body.code : undefined)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getAbout = () => call<AboutResponse>('/api/v1/about')
export const getBenchmark = () => call<BenchmarkResponse>('/api/v1/benchmark')
export const getInvestigation = (id: string) =>
  call<InvestigationState>(`/api/v1/investigations/${id}`)

export const uploadProject = (file: File) =>
  call<ProjectInfo>('/api/v1/projects/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip', 'X-Filename': file.name },
    body: file,
  })
export const projectFromGit = (url: string, ref?: string) =>
  call<ProjectInfo>('/api/v1/projects/git', json({ url, ref: ref || null }))
export const projectFromLocal = (path: string) =>
  call<ProjectInfo>('/api/v1/projects/local', json({ path }))
export const scanProject = (id: string) =>
  call<ScanResult>(`/api/v1/projects/${id}/scan`, { method: 'POST' })

export async function startInvestigation(args: {
  issue: string
  exampleCase?: string
  projectId?: string
  reproTargets?: string[]
}): Promise<string> {
  const created = await call<InvestigationState>(
    '/api/v1/investigations',
    json({
      issue: args.issue,
      example_case: args.exampleCase ?? null,
      project_id: args.projectId ?? null,
      repro_targets: args.reproTargets ?? [],
    }),
  )
  await call(`/api/v1/investigations/${created.id}/run`, { method: 'POST' })
  return created.id
}

export async function reverifyInvestigation(
  id: string, attempt: number, disputed: string[], reason: string,
): Promise<string> {
  const reply = await call<{ investigation_id: string }>(
    `/api/v1/investigations/${id}/reverify`, json({ attempt, disputed, reason }),
  )
  return reply.investigation_id
}

export type PullRequestResult = {
  number: number
  url: string
  branch: string
  base: string
  patch_id: string
  commit_sha: string | null
  files_changed: { path: string; change: string }[]
  mergeable: boolean | null // null: GitHub is still computing it
  warning: string | null
  reused: boolean // an open PR for this certificate already existed
}

/** Opens a GitHub PR for a verified patch. The token travels in a header and is never stored. */
export const createPullRequest = (
  id: string,
  args: { repository?: string; baseBranch?: string; token?: string },
) =>
  call<PullRequestResult>(`/api/v1/investigations/${id}/pull-request`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(args.token ? { 'X-GitHub-Token': args.token } : {}),
    },
    body: JSON.stringify({
      repository: args.repository || null,
      base_branch: args.baseBranch || null,
    }),
  })
