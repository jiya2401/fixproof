import { useState } from 'react'
import { reverifyInvestigation, type Certificate } from '../api'
import { Button, Card, ErrorBanner, Pill, SectionTitle, Spinner } from '../ui'

/** Human review: exclude attack tests you judge wrong and re-run every check. No model calls. */
export default function ReviewPanel({
  cert, investigationId, onStarted,
}: { cert: Certificate; investigationId: string; onStarted: (id: string) => void }) {
  const attemptNo = cert.selected_attempt ?? cert.iterations[cert.iterations.length - 1]?.index
  const attempt = cert.iterations.find((it) => it.index === attemptNo)
  const disputable = cert.adversarial_tests.filter(
    (t) => t.grounded && !t.disputed && t.key && attempt?.test_results[t.key] === 'failed',
  )
  const [picked, setPicked] = useState<string[]>([])
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!attempt || disputable.length === 0) return null

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      onStarted(await reverifyInvestigation(investigationId, attempt.index, picked, reason.trim()))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }
  const toggle = (key: string) =>
    setPicked((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]))

  return (
    <Card className="border-amber-400/30 p-6">
      <SectionTitle hint="no model calls · recorded in the certificate">Review the attack tests</SectionTitle>
      <p className="text-sm text-zinc-300">
        Attack tests are written by the model and can be wrong. Attempt {attempt.index} failed the
        test{disputable.length > 1 ? 's' : ''} below. If you judge one to be incorrect, exclude it and FixProof
        re-runs <b>every</b> check on that patch. Your exclusion and reason are written into the certificate and the
        verdict is capped at <i>verified with conditions</i>.
      </p>
      {cert.contested.length > 0 && (
        <p className="mt-2 text-xs text-amber-300">
          Contradictions were detected between attack tests across attempts ({cert.contested.join(', ')}); at least
          one of those is probably wrong.
        </p>
      )}
      <ul className="mt-4 space-y-2">
        {disputable.map((t) => (
          <li key={t.key} className={`rounded-xl border p-3 ${picked.includes(t.key) ? 'border-amber-400/50 bg-amber-400/5' : 'border-white/10'}`}>
            <label className="flex cursor-pointer gap-3">
              <input type="checkbox" checked={picked.includes(t.key)} onChange={() => toggle(t.key)}
                className="mt-1 accent-amber-400" />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="mono text-sm text-zinc-100">{t.name}</span>
                  {cert.contested.includes(t.key) && <Pill tone="amber">contradicts other tests</Pill>}
                </span>
                <span className="mt-1 block text-xs text-sky-200">Spec quoted: “{t.spec_quote}”</span>
              </span>
            </label>
            <details className="mt-2 pl-7">
              <summary className="cursor-pointer text-xs text-zinc-400 hover:text-zinc-200">Read the test and decide</summary>
              <pre className="mono mt-2 max-h-48 overflow-auto rounded-lg bg-black/40 p-3 text-xs text-zinc-300">{t.code}</pre>
            </details>
          </li>
        ))}
      </ul>
      <label className="mt-4 block text-sm text-zinc-300">
        Why is the test wrong? <span className="text-zinc-500">(required, shown in the certificate)</span>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
          placeholder="e.g. page 3 of 5 items at 2 per page holds item 5, so [] is incorrect"
          className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-amber-400 focus:outline-none" />
      </label>
      {error && <div className="mt-3"><ErrorBanner message={error} /></div>}
      <div className="mt-4">
        <Button disabled={busy || picked.length === 0 || reason.trim().length < 10} onClick={submit}>
          {busy ? <><Spinner /> Starting…</> : `Re-verify attempt ${attempt.index} without ${picked.length || 'the'} selected test${picked.length === 1 ? '' : 's'}`}
        </Button>
      </div>
    </Card>
  )
}
