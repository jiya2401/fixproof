import { useEffect, useState } from 'react'
import { scanProject, type ScanResult } from '../api'
import type { Source } from '../types'
import { Alert, Button, Card, ErrorBanner, Pill, SectionTitle, Spinner, Stat } from '../ui'

export default function ScanStep({
  source, onBack, onRun,
}: {
  source: Source
  onBack: () => void
  onRun: (issue: string, targets: string[]) => void
}) {
  const isProject = source.kind === 'project'
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [manual, setManual] = useState('')
  const [issue, setIssue] = useState(source.kind === 'example' ? source.issue : '')
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (source.kind !== 'project') return
    let cancelled = false
    scanProject(source.info.id)
      .then((result) => {
        if (cancelled) return
        setScan(result)
        const first = result.failing_tests[0]
        if (first) {
          setSelected([first.node_id])
          setIssue((cur) => cur || `${first.node_id} fails: ${first.message}`.slice(0, 400))
        }
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => { cancelled = true }
  }, [source])

  const targets = [...selected, ...(manual.trim() ? [manual.trim()] : [])]
  const ready = issue.trim().length >= 10 && (!isProject || targets.length > 0)
  const toggle = (id: string) =>
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))

  return (
    <div className="space-y-5 fade-up">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-zinc-500">Project</p>
            <h2 className="mt-1 text-xl font-semibold text-white">
              {source.kind === 'project' ? source.info.name : source.name}
            </h2>
            {source.kind === 'project' && (
              <p className="mt-1 text-xs text-zinc-500">
                {source.info.python_files} Python files · {source.info.test_files} test files · from {source.info.origin}
              </p>
            )}
          </div>
          <Button variant="ghost" onClick={onBack}>Change project</Button>
        </div>
      </Card>

      {isProject && (
        <Card className="p-6">
          <SectionTitle hint={scan ? `${scan.duration_seconds}s in the sandbox` : undefined}>
            1 · Find the failing test
          </SectionTitle>
          {!scan && !error && (
            <div className="flex items-center gap-3 text-sm text-zinc-400">
              <Spinner className="h-5 w-5 text-[var(--accent)]" /> Running your test suite in the sandbox…
            </div>
          )}
          {error && <ErrorBanner message={error} />}
          {scan && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Tests" value={scan.tests} />
                <Stat label="Failing" value={scan.failed} />
                <Stat label="Errors" value={scan.errors} />
                <Stat label="Skipped" value={scan.skipped} />
              </div>
              {scan.hint && (
                <div className="flex gap-3 rounded-xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">
                  <Alert className="mt-0.5 h-4 w-4 shrink-0" /> <span>{scan.hint}</span>
                </div>
              )}
              {scan.failing_tests.length > 0 && (
                <ul className="space-y-2" aria-label="Failing tests">
                  {scan.failing_tests.map((t) => (
                    <li key={t.node_id}>
                      <label className={`flex cursor-pointer gap-3 rounded-xl border p-3 transition ${
                        selected.includes(t.node_id) ? 'border-[var(--accent)]/50 bg-[var(--accent)]/5' : 'border-white/10 hover:bg-white/5'}`}>
                        <input type="checkbox" checked={selected.includes(t.node_id)}
                          onChange={() => toggle(t.node_id)} className="mt-1 accent-[var(--accent)]" />
                        <span className="min-w-0">
                          <span className="mono block truncate text-sm text-zinc-100">{t.node_id}</span>
                          <span className="mt-0.5 block truncate text-xs text-zinc-500">{t.message}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {scan.collection_errors.length > 0 && (
                <details className="rounded-xl border border-white/10 p-3 text-xs text-zinc-400">
                  <summary className="cursor-pointer">{scan.collection_errors.length} collection / setup error(s)</summary>
                  <ul className="mono mt-2 space-y-1">
                    {scan.collection_errors.map((e) => <li key={e.node_id}>{e.node_id} {e.message}</li>)}
                  </ul>
                </details>
              )}
              <label className="block text-sm text-zinc-300">
                Or enter a test id yourself
                <input value={manual} onChange={(e) => setManual(e.target.value)}
                  placeholder="tests/test_orders.py::test_total_with_discount"
                  className="mono mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none" />
              </label>
            </div>
          )}
        </Card>
      )}

      {(!isProject || scan) && (
        <Card className="p-6">
          <SectionTitle>{isProject ? '2 · Describe the expected behavior' : 'Issue'}</SectionTitle>
          <textarea value={issue} onChange={(e) => { setIssue(e.target.value); setTouched(true) }} rows={4}
            placeholder="What should happen? e.g. “Discounts above 100% must be rejected with ValueError.”"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-3 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none" />
          <p className="mt-2 text-xs leading-relaxed text-zinc-500">
            FixProof's attack tests must <span className="text-zinc-300">quote a sentence</span> from this text, your
            docstrings or your README to count as evidence. The clearer the expected behavior, the stronger the verification.
          </p>
          {touched && issue.trim().length < 10 && (
            <p className="mt-2 text-xs text-amber-300">Write at least 10 characters.</p>
          )}
          <div className="mt-5 flex items-center gap-3">
            <Button disabled={!ready} onClick={() => onRun(issue.trim(), targets)}>Run repair + verification</Button>
            <span className="text-xs text-zinc-500">
              Uses Nemotron on Nebius; typically 1–3 minutes and a few thousand tokens.
            </span>
          </div>
        </Card>
      )}
    </div>
  )
}
