const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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
  max_iterations: number
  limitations: string[]
  disclaimers: string[]
  verdict: Verdict
  verdict_reasons: string[]
  timeline: { at: string; stage: string; message: string }[]
  certificate_sha256: string
}

export type InvestigationState = {
  id: string
  stage: string
  error: string | null
  certificate: Certificate | null
}

export type AboutResponse = {
  name: string
  status: string
  nebius_model: string
  nebius_configured: boolean
  sandbox_mode: string
  example_cases: string[]
  implemented_now: string[]
  not_implemented: string[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail ?? `Request failed (${response.status})`)
  }
  return response.json()
}

export const getAbout = () => call<AboutResponse>('/api/v1/about')
export const getInvestigation = (id: string) => call<InvestigationState>(`/api/v1/investigations/${id}`)

export async function startExampleRun(exampleCase: string, issue: string): Promise<string> {
  const created = await call<InvestigationState>('/api/v1/investigations', {
    method: 'POST',
    body: JSON.stringify({
      repo_url: 'https://github.com/jiya2401/fixproof',
      issue,
      example_case: exampleCase,
    }),
  })
  await call(`/api/v1/investigations/${created.id}/run`, { method: 'POST' })
  return created.id
}
