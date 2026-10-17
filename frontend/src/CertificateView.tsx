import type { Certificate, Check, Outcome, Verdict } from './api'

const VERDICT_STYLE: Record<Verdict, { label: string; cls: string; blurb: string }> = {
  verified: {
    label: 'VERIFIED',
    cls: 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300',
    blurb: 'All mandatory checks executed and no counterexample was found.',
  },
  verified_with_conditions: {
    label: 'VERIFIED WITH CONDITIONS',
    cls: 'border-amber-500/60 bg-amber-500/10 text-amber-300',
    blurb: 'Mandatory checks passed, but conditions below limit the claim.',
  },
  not_verified: {
    label: 'NOT VERIFIED',
    cls: 'border-red-500/60 bg-red-500/10 text-red-300',
    blurb: 'An executed check produced a concrete failure or counterexample.',
  },
  insufficient_evidence: {
    label: 'INSUFFICIENT EVIDENCE',
    cls: 'border-zinc-500/60 bg-zinc-500/10 text-zinc-300',
    blurb: 'Required evidence could not be established. This is not a pass.',
  },
}

const OUTCOME_STYLE: Record<Outcome, string> = {
  passed: 'text-emerald-400',
  failed: 'text-red-400',
  error: 'text-orange-400',
  skipped: 'text-zinc-400',
  not_run: 'text-zinc-500',
}

function CheckRow({ check }: { check: Check }) {
  return (
    <details className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className={`w-16 font-mono text-xs uppercase ${OUTCOME_STYLE[check.outcome]}`}>
          {check.outcome}
        </span>
        <span className="font-medium">{check.name}</span>
        <span className="text-zinc-500">{check.summary}</span>
        <span className="ml-auto text-xs text-zinc-600">{check.tests_executed} tests executed</span>
      </summary>
      <div className="mt-3 space-y-2 text-xs text-zinc-400">
        {check.command && <p className="font-mono">$ {check.command} (exit {check.exit_code})</p>}
        {check.counterexamples.length > 0 && (
          <ul className="list-inside list-disc text-red-300">
            {check.counterexamples.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        )}
        {check.output_excerpt && (
          <pre className="max-h-64 overflow-auto rounded bg-black/50 p-3 text-zinc-400">{check.output_excerpt}</pre>
        )}
        {check.stdout_sha256 && <p className="font-mono text-zinc-600">stdout sha256 {check.stdout_sha256}</p>}
      </div>
    </details>
  )
}

export default function CertificateView({ cert }: { cert: Certificate }) {
  const verdict = VERDICT_STYLE[cert.verdict]
  return (
    <section className="space-y-6">
      <div className={`rounded-2xl border p-6 ${verdict.cls}`}>
        <p className="text-xs uppercase tracking-[0.2em] opacity-70">Fix Certificate · policy v{cert.policy_version}</p>
        <h2 className="mt-2 text-3xl font-semibold">{verdict.label}</h2>
        <p className="mt-2 text-sm opacity-80">{verdict.blurb}</p>
        <ul className="mt-4 list-inside list-disc space-y-1 text-sm">
          {cert.verdict_reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        {cert.unexecuted_checks.length > 0 && (
          <p className="mt-3 text-sm">Not executed / errored: {cert.unexecuted_checks.join(', ')}</p>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-3 text-sm">
        <Card title="Who did what">
          <ul className="space-y-1 text-zinc-400">
            {Object.entries(cert.tool_attribution).map(([step, who]) => (
              <li key={step}>
                <span className="text-zinc-200">{step.replaceAll('_', ' ')}</span>: {who}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Model (live usage)">
          <p className="text-zinc-400">
            {cert.model.provider}
            <br />
            {cert.model.model || 'n/a'}
            <br />
            {cert.model.calls} calls · {cert.model.prompt_tokens + cert.model.completion_tokens} tokens
          </p>
        </Card>
        <Card title="Sandbox (as actually provided)">
          <p className="text-zinc-400">
            {cert.sandbox.kind} · isolation: <b className="text-zinc-200">{cert.sandbox.isolation}</b>
            <br />
            network blocked: {String(cert.sandbox.network_blocked)} · self-tested:{' '}
            {String(cert.sandbox.isolation_self_tested)}
          </p>
        </Card>
      </div>

      <Card title="Mandatory checks (final attempt)">
        <div className="space-y-2">
          {cert.checks.map((c) => (
            <CheckRow key={c.name} check={c} />
          ))}
        </div>
      </Card>

      <Card title={`Repair iterations (${cert.iterations.length}/${cert.max_iterations})`}>
        <div className="space-y-3">
          {cert.iterations.map((it) => (
            <details key={it.index} className="rounded-lg border border-zinc-800 p-3" open={it.counterexamples.length > 0}>
              <summary className="cursor-pointer text-sm">
                Attempt {it.index}: {it.summary || it.note}
                {it.counterexamples.length > 0 && (
                  <span className="ml-2 text-red-400">{it.counterexamples.length} counterexample(s)</span>
                )}
              </summary>
              <div className="mt-3 space-y-2">
                {it.diff && <pre className="max-h-64 overflow-auto rounded bg-black/50 p-3 text-xs">{it.diff}</pre>}
                {it.checks.map((c) => (
                  <CheckRow key={c.name} check={c} />
                ))}
                {it.feedback_to_fixer && (
                  <p className="text-xs text-zinc-500">Feedback this attempt received: {it.feedback_to_fixer.slice(0, 400)}</p>
                )}
              </div>
            </details>
          ))}
        </div>
      </Card>

      {cert.adversarial_tests.length > 0 && (
        <Card title={`Adversarial tests executed (${cert.adversarial_tests.length}, model-authored)`}>
          <div className="space-y-2">
            {cert.adversarial_tests.map((t) => (
              <details key={t.name} className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
                <summary className="cursor-pointer text-sm">
                  <span className={t.grounded ? 'text-emerald-400' : 'text-amber-400'}>
                    {t.grounded ? 'spec-grounded' : 'ungrounded'}
                  </span>{' '}
                  {t.name} <span className="text-zinc-500">{t.rationale}</span>
                </summary>
                <p className="mt-2 text-xs text-zinc-400">
                  SPEC: “{t.spec_quote || 'none given'}” — {t.grounding_note}
                </p>
                <pre className="mt-2 max-h-64 overflow-auto rounded bg-black/50 p-3 text-xs">{t.code}</pre>
              </details>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Root cause (model-proposed, untested)">
          <p className="text-sm text-zinc-300">{cert.selected_root_cause || 'none recorded'}</p>
          <ul className="mt-2 space-y-1 text-xs text-zinc-500">
            {cert.hypotheses.map((h) => (
              <li key={h.title}>
                {h.title} — {h.status}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Limitations & disclaimers">
          <ul className="list-inside list-disc space-y-1 text-xs text-zinc-400">
            {[...cert.limitations, ...cert.disclaimers].map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Timeline">
        <ol className="space-y-1 font-mono text-xs text-zinc-500">
          {cert.timeline.map((t, i) => (
            <li key={i}>
              {new Date(t.at).toLocaleTimeString()} · {t.stage} · {t.message}
            </li>
          ))}
        </ol>
      </Card>

      <p className="break-all font-mono text-xs text-zinc-600">
        snapshot {cert.snapshot_sha256} · certificate {cert.certificate_sha256}
      </p>
    </section>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5">
      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">{title}</p>
      {children}
    </article>
  )
}
