import { useState } from 'react'
import type { Certificate, Check, Iteration, Outcome, Verdict } from '../api'
import {
  Alert, Button, Card, Check as CheckIcon, Copy, Cross, Download, Pill, SectionTitle, Shield, Stat,
  type Tone,
} from '../ui'
import DiffView from './DiffView'
import ReviewPanel from './ReviewPanel'

const VERDICTS: Record<Verdict, { label: string; line: string; tone: string; icon: 'ok' | 'warn' | 'bad' | 'none' }> = {
  verified: {
    label: 'Verified',
    line: 'Every mandatory check was executed and none found a counterexample.',
    tone: 'border-emerald-400/40 from-emerald-400/15', icon: 'ok',
  },
  verified_with_conditions: {
    label: 'Verified with conditions',
    line: 'All mandatory checks passed, but the conditions below limit how far this can be trusted.',
    tone: 'border-amber-400/40 from-amber-400/15', icon: 'warn',
  },
  not_verified: {
    label: 'Not verified',
    line: 'An executed check produced a concrete failure. Do not merge this patch as-is.',
    tone: 'border-red-400/40 from-red-400/15', icon: 'bad',
  },
  insufficient_evidence: {
    label: 'Insufficient evidence',
    line: 'FixProof could not establish the evidence its policy requires. This is not a pass.',
    tone: 'border-zinc-400/30 from-zinc-400/10', icon: 'none',
  },
}

const LABELS: Record<string, string> = {
  reproduction_red: 'Bug reproduced before the patch',
  patch_applies_in_scope: 'Patch applies, touches no tests',
  reproduction_green: 'Original failing test now passes',
  regression: 'Full existing test suite',
  adversarial: 'Spec-quoted attack tests',
  adversarial_ungrounded: 'Unvalidated attack tests (review only)',
  self_review: 'Model self-review',
}
const label = (name: string) => LABELS[name] ?? name
const MANDATORY = ['patch_applies_in_scope', 'reproduction_green', 'regression', 'adversarial']

const OUTCOME_TONE: Record<Outcome, Tone> = {
  passed: 'green', failed: 'red', error: 'amber', skipped: 'gray', not_run: 'gray',
}

function parseCounterexample(text: string): { message: string; spec?: string } {
  const match = /^([\s\S]*?)\s*\[SPEC: "([\s\S]*)"\]$/.exec(text)
  return match ? { message: match[1], spec: match[2] } : { message: text }
}

function iterationStatus(it: Iteration): 'accepted' | 'rejected' | 'incomplete' {
  const mandatory = it.checks.filter((c) => MANDATORY.includes(c.name))
  if (mandatory.some((c) => c.outcome === 'failed')) return 'rejected'
  if (mandatory.length >= MANDATORY.length && mandatory.every((c) => c.outcome === 'passed')) return 'accepted'
  return 'incomplete'
}

function Chip({ check }: { check: Check }) {
  const ok = check.outcome === 'passed'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs ${
      ok ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200'
      : check.outcome === 'failed' ? 'border-red-400/30 bg-red-400/10 text-red-200'
      : 'border-white/10 bg-white/5 text-zinc-400'}`}>
      {ok ? <CheckIcon className="h-3 w-3" /> : check.outcome === 'failed' ? <Cross className="h-3 w-3" /> : <Alert className="h-3 w-3" />}
      {label(check.name)}
    </span>
  )
}

export default function CertificateView({
  cert, onReset, investigationId, onReverify,
}: {
  cert: Certificate
  onReset: () => void
  investigationId?: string
  onReverify?: (newId: string) => void
}) {
  const [copied, setCopied] = useState<string | null>(null)
  const v = VERDICTS[cert.verdict]
  const copy = async (what: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(what); setTimeout(() => setCopied(null), 1500) } catch { /* clipboard blocked */ }
  }
  const download = () => {
    const blob = new Blob([JSON.stringify(cert, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `fix-certificate-${cert.certificate_id.slice(0, 8)}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const times = cert.timeline.map((t) => new Date(t.at).getTime())
  const runtime = times.length > 1 ? Math.round((Math.max(...times) - Math.min(...times)) / 1000) : 0
  const testsExecuted = cert.checks.reduce((n, c) => n + c.tests_executed, 0)
  const counterexamples = cert.iterations.reduce((n, it) => n + it.counterexamples.length, 0)
  const tokens = cert.model.prompt_tokens + cert.model.completion_tokens
  const rejected = cert.iterations.filter((it) => iterationStatus(it) === 'rejected').length
  const recovered = rejected > 0 && cert.verdict !== 'not_verified' && cert.verdict !== 'insufficient_evidence'

  return (
    <div className="space-y-6 fade-up">
      <section className={`rounded-3xl border bg-gradient-to-br to-transparent p-7 ${v.tone}`} aria-labelledby="verdict">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="flex items-start gap-4">
            <div className="rounded-2xl bg-black/30 p-3"><Shield className="h-8 w-8 text-white" /></div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-zinc-400">Fix Certificate · policy v{cert.policy_version}</p>
              <h2 id="verdict" className="mt-1 text-4xl font-semibold tracking-tight text-white">{v.label}</h2>
              <p className="mt-2 max-w-xl text-sm text-zinc-300">{v.line}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={download}><Download /> Certificate JSON</Button>
            {cert.final_patch && (
              <Button variant="ghost" onClick={() => copy('patch', cert.final_patch ?? '')}>
                <Copy /> {copied === 'patch' ? 'Copied' : 'Copy patch'}
              </Button>
            )}
            <Button variant="ghost" onClick={onReset}>New run</Button>
          </div>
        </div>
        <ul className="mt-5 space-y-1.5 text-sm text-zinc-200">
          {cert.verdict_reasons.map((r) => (
            <li key={r} className="flex gap-2"><span className="text-zinc-500">›</span>{r}</li>
          ))}
        </ul>
      </section>

      {cert.derived_from && (
        <div className="flex gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">
          <Alert className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <b>Human-reviewed re-verification.</b> Attempt {cert.reverified_attempt} was re-checked after a
            reviewer excluded {cert.adversarial_tests.filter((t) => t.disputed).length} attack test(s). No model
            calls were made; the exclusion and reason are listed under limitations.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Attempts" value={`${cert.iterations.length}/${cert.max_iterations}`} sub={rejected ? `${rejected} rejected by evidence` : 'first patch held'} />
        <Stat label="Tests executed" value={testsExecuted} sub="across final checks" />
        <Stat label="Counterexamples" value={counterexamples} sub="found by execution" />
        <Stat label="Model usage" value={tokens.toLocaleString()} sub={`${cert.model.calls} calls · tokens`} />
        <Stat label="Wall time" value={`${runtime}s`} sub={cert.model.model.split('/').pop()} />
      </div>

      {recovered && (
        <div className="flex gap-3 rounded-2xl border border-[var(--accent)]/30 bg-[var(--accent)]/10 p-4 text-sm text-zinc-100">
          <Bolt2 />
          <p>
            <b>The evidence changed the outcome.</b> {rejected} earlier patch{rejected > 1 ? 'es' : ''} passed
            the visible tests but {rejected > 1 ? 'were' : 'was'} rejected by an executed counterexample;
            the repaired patch survived the same attack.
          </p>
        </div>
      )}

      <Card className="p-6">
        <SectionTitle hint="every attempt re-runs every mandatory check">Repair journey</SectionTitle>
        <ol className="space-y-4">
          {cert.iterations.map((it) => {
            const status = iterationStatus(it)
            return (
              <li key={it.index} className={`rounded-xl border p-4 ${
                status === 'accepted' ? 'border-emerald-400/30 bg-emerald-400/5'
                : status === 'rejected' ? 'border-red-400/25 bg-red-400/5' : 'border-white/10 bg-black/20'}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-white">Attempt {it.index}{cert.selected_attempt === it.index ? ' (reported)' : ''} <span className="font-normal text-zinc-400">· {it.summary || it.note || 'no patch'}</span></p>
                  <Pill tone={status === 'accepted' ? 'green' : status === 'rejected' ? 'red' : 'gray'}>
                    {status === 'accepted' ? 'survived every check' : status === 'rejected' ? 'rejected by evidence' : 'incomplete'}
                  </Pill>
                </div>
                {it.checks.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">{it.checks.map((c) => <Chip key={c.name} check={c} />)}</div>
                )}
                {it.counterexamples.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {it.counterexamples.map((c) => {
                      const { message, spec } = parseCounterexample(c)
                      return (
                        <li key={c} className="rounded-lg border border-red-400/20 bg-black/30 p-3">
                          <p className="mono break-words text-xs text-red-200">{message}</p>
                          {cert.contested.some((k) => message.includes(`test_adv_${k}`)) && (
                            <p className="mt-2"><Pill tone="amber">contradicts other attack tests</Pill></p>
                          )}
                          {spec && <p className="mt-2 border-l-2 border-sky-400/50 pl-3 text-xs text-sky-200"><span className="text-sky-400">Spec quoted:</span> “{spec}”</p>}
                        </li>
                      )
                    })}
                  </ul>
                )}
                {it.note && <p className="mt-3 text-xs text-amber-300">{it.note}</p>}
                {it.diff && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs text-zinc-400 hover:text-zinc-200">View this patch</summary>
                    <div className="mt-2"><DiffView diff={it.diff} /></div>
                  </details>
                )}
              </li>
            )
          })}
          {cert.iterations.length === 0 && <li className="text-sm text-zinc-500">No patch was attempted: {cert.limitations[0] ?? 'see the limitations below'}.</li>}
        </ol>
      </Card>

      {investigationId && onReverify && (
        <ReviewPanel cert={cert} investigationId={investigationId} onStarted={onReverify} />
      )}

      {cert.final_patch && (
        <Card className="p-6">
          <SectionTitle hint={`${cert.changed_files.join(', ')}`}>Final patch</SectionTitle>
          <DiffView diff={cert.final_patch} />
        </Card>
      )}

      <Card className="p-6">
        <SectionTitle hint="final attempt">Evidence ledger</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-zinc-500">
              <tr><th className="pb-2 pr-4 font-medium">Check</th><th className="pb-2 pr-4 font-medium">Result</th><th className="pb-2 pr-4 font-medium">Tests</th><th className="pb-2 font-medium">Detail</th></tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {cert.checks.map((c) => (
                <tr key={c.name} className="align-top">
                  <td className="py-2.5 pr-4 text-zinc-200">{label(c.name)}</td>
                  <td className="py-2.5 pr-4"><Pill tone={OUTCOME_TONE[c.outcome]}>{c.outcome}</Pill></td>
                  <td className="py-2.5 pr-4 tabular-nums text-zinc-400">{c.tests_executed}</td>
                  <td className="py-2.5 text-xs text-zinc-500">
                    {c.summary}
                    {c.output_excerpt && (
                      <details className="mt-1"><summary className="cursor-pointer text-zinc-400">output</summary>
                        <pre className="mono mt-1 max-h-48 overflow-auto rounded bg-black/40 p-2 text-[11px]">{c.output_excerpt}</pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {cert.adversarial_tests.length > 0 && (
        <Card className="p-6">
          <SectionTitle hint="written by the model, executed by tools">Attack tests ({cert.adversarial_tests.length})</SectionTitle>
          <div className="space-y-2">
            {cert.adversarial_tests.map((t) => (
              <details key={t.name} className="rounded-xl border border-white/10 bg-black/20 p-3">
                <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                  <Pill tone={t.disputed ? 'gray' : t.grounded ? 'green' : 'amber'}>{t.disputed ? 'excluded by reviewer' : t.grounded ? 'spec-grounded' : 'unvalidated'}</Pill>
                  <span className="mono text-zinc-200">{t.name}</span>
                  <span className="text-xs text-zinc-500">{t.rationale}</span>
                </summary>
                <p className="mt-3 border-l-2 border-sky-400/50 pl-3 text-xs text-sky-200">“{t.spec_quote || 'no quote given'}” <span className="text-zinc-500">— {t.grounding_note}</span></p>
                <pre className="mono mt-3 max-h-64 overflow-auto rounded-lg bg-black/40 p-3 text-xs text-zinc-300">{t.code}</pre>
              </details>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <SectionTitle>Who did what</SectionTitle>
          <ul className="space-y-2 text-sm">
            {Object.entries(cert.tool_attribution).map(([step, who]) => (
              <li key={step} className="flex items-center justify-between gap-3">
                <span className="text-zinc-300">{step.replaceAll('_', ' ')}</span>
                <Pill tone={who.startsWith('nemotron') ? 'blue' : 'green'}>{who.startsWith('nemotron') ? 'Nemotron' : 'deterministic tool'}</Pill>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-zinc-500">
            {cert.model.provider} · {cert.model.model} · {cert.model.calls} calls · {tokens.toLocaleString()} tokens
          </p>
        </Card>
        <Card className="p-6">
          <SectionTitle>Sandbox · as actually provided</SectionTitle>
          <div className="flex flex-wrap gap-2">
            <Pill tone={cert.sandbox.isolation === 'container' ? 'green' : 'amber'}>isolation: {cert.sandbox.isolation}</Pill>
            <Pill tone={cert.sandbox.network_blocked ? 'green' : 'amber'}>network {cert.sandbox.network_blocked ? 'blocked' : 'open'}</Pill>
            <Pill tone={cert.sandbox.isolation_self_tested ? 'green' : 'amber'}>self-test {cert.sandbox.isolation_self_tested ? 'passed' : 'not passed'}</Pill>
          </div>
          <ul className="mt-3 space-y-1 text-xs text-zinc-500">{cert.sandbox.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Card>
      </div>

      <Card className="p-6">
        <SectionTitle>Limitations &amp; what this does not prove</SectionTitle>
        <ul className="list-inside list-disc space-y-1.5 text-sm text-zinc-400">
          {[...cert.limitations, ...cert.disclaimers].map((l) => <li key={l}>{l}</li>)}
        </ul>
        {cert.selected_root_cause && (
          <p className="mt-4 text-xs text-zinc-500"><span className="text-zinc-300">Root cause (model-proposed, untested):</span> {cert.selected_root_cause}</p>
        )}
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/8 bg-black/20 px-4 py-3 text-xs text-zinc-500">
        <span className="mono break-all">snapshot {cert.snapshot_sha256.slice(0, 16)}… · certificate {cert.certificate_sha256.slice(0, 16)}…</span>
        <button className="text-zinc-300 hover:text-white" onClick={() => copy('hash', cert.certificate_sha256)}>
          {copied === 'hash' ? 'Copied' : 'Copy full hash'}
        </button>
      </div>
    </div>
  )
}

function Bolt2() {
  return <span className="mt-0.5 text-[var(--accent)]" aria-hidden="true">⚡</span>
}
