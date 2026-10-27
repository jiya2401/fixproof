import { useEffect, useRef, useState } from 'react'
import { getInvestigation, type InvestigationState, type TimelineEvent } from '../api'
import { Button, Card, Check, ErrorBanner, SectionTitle, Spinner } from '../ui'

const STEPS = [
  { label: 'Reproduce', desc: 'Run the failing test before touching anything' },
  { label: 'Investigate', desc: 'Nemotron proposes root-cause hypotheses' },
  { label: 'Repair', desc: 'Nemotron proposes a minimal patch' },
  { label: 'Verify', desc: 'Apply the patch, re-run the bug test and the full suite' },
  { label: 'Attack', desc: 'Spec-quoted adversarial tests run in the sandbox' },
  { label: 'Verdict', desc: 'The policy computes the verdict from executed evidence' },
]

export function stepIndex(e: TimelineEvent): number {
  switch (e.stage) {
    case 'snapshot':
    case 'reproducing': return 0
    case 'investigating': return 1
    case 'fixing':
    case 'repairing': return 2
    case 'verifying': return /adversarial/i.test(e.message) ? 4 : 3
    case 'reviewing':
    case 'reverifying': return 3
    case 'planning_verification': return 4
    default: return 5
  }
}

const tone = (m: string) =>
  /failed|rejected|error|repeated|planner failed/i.test(m) ? 'text-red-300'
  : /passed|verified|applied/i.test(m) ? 'text-emerald-300' : 'text-zinc-400'

export default function RunMonitor({
  investigationId, onDone, onBack,
}: {
  investigationId: string
  onDone: (state: InvestigationState) => void
  onBack: () => void
}) {
  const [state, setState] = useState<InvestigationState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const doneRef = useRef(false)

  useEffect(() => {
    const started = Date.now()
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    const poll = setInterval(async () => {
      if (doneRef.current) return
      try {
        const next = await getInvestigation(investigationId)
        setState(next)
        if (next.stage === 'completed' && next.certificate) {
          doneRef.current = true
          onDone(next)
        } else if (next.stage === 'failed') {
          doneRef.current = true
          setError(next.error ?? 'The investigation failed.')
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        doneRef.current = true
      }
    }, 1200)
    return () => { clearInterval(tick); clearInterval(poll) }
  }, [investigationId, onDone])

  const events = state?.events ?? []
  const current = events.length ? stepIndex(events[events.length - 1]) : 0
  const attempt = [...events].reverse().map((e) => /iteration (\d+)\/(\d+)/.exec(e.message)).find(Boolean)

  return (
    <div className="space-y-5 fade-up">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-white">Working on it…</h2>
            <p className="mt-1 text-sm text-zinc-500">
              {attempt ? `Repair attempt ${attempt[1]} of ${attempt[2]} · ` : ''}{elapsed}s elapsed
            </p>
          </div>
          {error && <Button variant="ghost" onClick={onBack}>Back</Button>}
        </div>

        <ol className="mt-6 grid gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="Pipeline progress">
          {STEPS.map((step, i) => {
            const done = i < current || (!error && state?.stage === 'completed')
            const active = i === current && !error
            return (
              <li key={step.label}
                className={`rounded-xl border p-3 transition ${
                  active ? 'border-[var(--accent)]/60 bg-[var(--accent)]/10'
                  : done ? 'border-emerald-400/20 bg-emerald-400/5' : 'border-white/8 bg-black/20'}`}>
                <div className="flex items-center gap-2">
                  <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                    active ? 'pulse-ring bg-[var(--accent)] text-black'
                    : done ? 'bg-emerald-400/20 text-emerald-300' : 'bg-white/10 text-zinc-500'}`}>
                    {done ? <Check className="h-3.5 w-3.5" /> : active ? <Spinner className="h-3.5 w-3.5" /> : i + 1}
                  </span>
                  <span className={`text-sm font-medium ${active || done ? 'text-white' : 'text-zinc-500'}`}>{step.label}</span>
                </div>
                <p className="mt-2 text-[11px] leading-snug text-zinc-500">{step.desc}</p>
              </li>
            )
          })}
        </ol>
      </Card>

      {error && <ErrorBanner message={error} />}

      <Card className="p-6">
        <SectionTitle hint="live from the backend">Event log</SectionTitle>
        {events.length === 0 ? (
          <div className="space-y-2" aria-hidden="true">
            <div className="shimmer h-4 w-2/3 rounded" /><div className="shimmer h-4 w-1/2 rounded" />
          </div>
        ) : (
          <ul className="mono max-h-80 space-y-1.5 overflow-y-auto text-xs" aria-live="polite">
            {[...events].reverse().map((e, i) => (
              <li key={`${e.at}-${i}`} className="flex gap-3">
                <span className="shrink-0 text-zinc-600">{new Date(e.at).toLocaleTimeString()}</span>
                <span className="shrink-0 text-zinc-500">{e.stage}</span>
                <span className={tone(e.message)}>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
