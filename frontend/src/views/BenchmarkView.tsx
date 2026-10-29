import { useEffect, useState } from 'react'
import { getBenchmark, type BenchmarkResponse, type BenchmarkTrial, type ModeSummary } from '../api'
import { Card, ErrorBanner, SectionTitle, Spinner } from '../ui'

const MODES: Record<string, { name: string; blurb: string }> = {
  baseline: { name: 'Tests only', blurb: 'Nemotron patch, accepted if the visible tests pass' },
  review: { name: 'Model self-review', blurb: 'Same model reads its own patch; nothing is executed' },
  fixproof: { name: 'FixProof', blurb: 'Executed, spec-quoted attack tests + bounded repair' },
}
const pct = (n: number | null) => (n === null ? 'n/a' : `${Math.round(n * 100)}%`)

function Bar({ value, tone }: { value: number; tone: string }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/10" role="img" aria-label={`${Math.round(value * 100)}%`}>
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  )
}

export default function BenchmarkView() {
  const [data, setData] = useState<BenchmarkResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getBenchmark().then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!data) return <div className="flex items-center gap-3 text-zinc-400"><Spinner /> Loading…</div>
  if (!data.available) {
    return (
      <Card className="p-8 fade-up">
        <h2 className="text-xl font-semibold text-white">No benchmark results recorded yet</h2>
        <p className="mt-2 max-w-2xl text-sm text-zinc-400">
          This page only ever shows numbers measured by a real run. Nothing is illustrative. Run the
          benchmark against your own Nebius key and the results appear here.
        </p>
        <pre className="mono mt-4 overflow-x-auto rounded-xl bg-black/40 p-4 text-xs text-zinc-300">
python evals/benchmark.py --trials 3 --out evals/results/run1.json
        </pre>
      </Card>
    )
  }

  const { report } = data
  const summary = report.summary as Record<string, ModeSummary>
  const modes = Object.keys(summary)
  const cases = [...new Set(report.trials.map((t) => t.case))]
  const cell = (c: string, m: string) => {
    const rows = report.trials.filter((t: BenchmarkTrial) => t.case === c && t.mode === m)
    const good = rows.filter((t) => t.resolved).length
    const bad = rows.filter((t) => t.false_accept).length
    return { rows: rows.length, good, bad }
  }

  return (
    <div className="space-y-6 fade-up">
      <div>
        <h2 className="text-2xl font-semibold text-white">Measured results</h2>
        <p className="mt-1 text-sm text-zinc-500">
          {data.file} · model {String(report.environment.model ?? '?')} · sandbox{' '}
          {String((report.environment.sandbox as { kind?: string } | undefined)?.kind ?? '?')}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {modes.map((m) => {
          const s = summary[m]
          const mine = m === 'fixproof'
          return (
            <Card key={m} className={`p-5 ${mine ? 'border-[var(--accent)]/40' : ''}`}>
              <p className="text-sm font-semibold text-white">{MODES[m]?.name ?? m}</p>
              <p className="mt-0.5 text-xs text-zinc-500">{MODES[m]?.blurb}</p>
              <div className="mt-4 space-y-3 text-xs">
                <div><div className="mb-1 flex justify-between text-zinc-400"><span>Resolved correctly</span><span>{pct(s.resolved_rate)}</span></div>
                  <Bar value={s.resolved_rate} tone="bg-emerald-400" /></div>
                <div><div className="mb-1 flex justify-between text-zinc-400"><span>Wrong patches accepted</span><span>{pct(s.false_acceptance_rate_of_accepted)}</span></div>
                  <Bar value={s.false_acceptance_rate_of_accepted ?? 0} tone="bg-red-400" /></div>
                <div><div className="mb-1 flex justify-between text-zinc-400"><span>Good patches rejected</span><span>{pct(s.false_rejection_rate)}</span></div>
                  <Bar value={s.false_rejection_rate} tone="bg-amber-400" /></div>
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-white/10 pt-3 text-center text-xs text-zinc-500">
                <div><dt>trials</dt><dd className="text-sm text-zinc-200">{s.trials}</dd></div>
                <div><dt>tokens</dt><dd className="text-sm text-zinc-200">{s.total_tokens.toLocaleString()}</dd></div>
                <div><dt>avg time</dt><dd className="text-sm text-zinc-200">{Math.round(s.mean_runtime_seconds)}s</dd></div>
              </dl>
            </Card>
          )
        })}
      </div>

      <Card className="p-6">
        <SectionTitle hint="✓ resolved · ✗ accepted but wrong (out of trials)">Per case</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-zinc-500">
              <tr><th className="pb-2 pr-4 font-medium">Case</th>{modes.map((m) => <th key={m} className="pb-2 pr-4 font-medium">{MODES[m]?.name ?? m}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {cases.map((c) => (
                <tr key={c}>
                  <td className="mono py-2.5 pr-4 text-zinc-300">{c}</td>
                  {modes.map((m) => {
                    const x = cell(c, m)
                    return (
                      <td key={m} className="py-2.5 pr-4 tabular-nums">
                        <span className="text-emerald-300">✓ {x.good}</span>{' '}
                        <span className={x.bad ? 'text-red-300' : 'text-zinc-600'}>✗ {x.bad}</span>
                        <span className="text-zinc-600"> / {x.rows}</span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-5 text-sm text-zinc-400">
        <p className="font-medium text-zinc-200">Read these numbers carefully</p>
        <ul className="mt-2 list-inside list-disc space-y-1 text-xs">
          <li>Small samples are noisy, and LLM output varies run to run even at temperature 0.</li>
          <li>Token budgets are <b>not</b> matched: FixProof spends more tokens and time than the baselines.</li>
          <li>Ground truth is a hidden oracle written by the authors of each case.</li>
          {report.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </Card>
    </div>
  )
}
