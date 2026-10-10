import { useEffect, useState } from 'react'
import CertificateView from './CertificateView'
import {
  getAbout,
  getInvestigation,
  startExampleRun,
  type AboutResponse,
  type Certificate,
} from './api'

const ISSUES: Record<string, string> = {
  'buggy-python-app': 'validate_refresh_token() accepts access tokens and rejects refresh tokens.',
  'paginate-app': 'paginate() returns the wrong slice: page 2 of [1..7] with per_page=3 returns [7].',
}

export default function App() {
  const [about, setAbout] = useState<AboutResponse | null>(null)
  const [backendError, setBackendError] = useState(false)
  const [exampleCase, setExampleCase] = useState('paginate-app')
  const [stage, setStage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cert, setCert] = useState<Certificate | null>(null)

  useEffect(() => {
    getAbout().then(setAbout).catch(() => setBackendError(true))
  }, [])

  async function run() {
    setError(null)
    setCert(null)
    try {
      setStage('starting')
      const id = await startExampleRun(exampleCase, ISSUES[exampleCase])
      for (;;) {
        const state = await getInvestigation(id)
        setStage(state.stage)
        if (state.stage === 'completed') return setCert(state.certificate)
        if (state.stage === 'failed') throw new Error(state.error ?? 'Investigation failed')
        await new Promise((r) => setTimeout(r, 1500))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStage(null)
    }
  }

  const busy = stage !== null && stage !== 'completed'

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-5xl px-6 py-12">
        <header className="border-b border-zinc-800 pb-8">
          <p className="text-xs tracking-wide text-zinc-500">
            Nebius × NVIDIA Global AI Hackathon · Coding &amp; Agentic Engineering
          </p>
          <h1 className="mt-3 text-5xl font-semibold tracking-tight">FixProof</h1>
          <p className="mt-3 text-lg text-zinc-400">
            AI proposes the fix. <span className="text-zinc-100">Evidence earns the merge.</span>
          </p>
          <p className="mt-4 text-sm text-zinc-500">
            Backend: {backendError ? 'not connected' : about ? 'connected' : 'checking…'}
            {about && (
              <>
                {' '}· model {about.nebius_model} · key {about.nebius_configured ? 'configured' : 'missing'} ·
                sandbox {about.sandbox_mode}
              </>
            )}
          </p>
        </header>

        <section className="my-8 flex flex-wrap items-end gap-4 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-5">
          <label className="text-sm text-zinc-400">
            Bundled bug case
            <select
              className="mt-1 block rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
              value={exampleCase}
              onChange={(e) => setExampleCase(e.target.value)}
            >
              {(about?.example_cases ?? Object.keys(ISSUES)).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <button
            onClick={run}
            disabled={busy || backendError}
            className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-40"
          >
            {busy ? `Running · ${stage}` : 'Run repair + verification'}
          </button>
          <p className="basis-full text-xs text-zinc-500">
            Runs the real pipeline: Nemotron proposes; sandboxed tools execute; the verdict policy decides.
            Needs NEBIUS_API_KEY and a sandbox on the server. No result is shown unless it actually ran.
          </p>
        </section>

        {error && (
          <div className="mb-6 rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">{error}</div>
        )}
        {cert && <CertificateView cert={cert} />}
        {about && !cert && (
          <section className="grid gap-4 text-sm md:grid-cols-2">
            <ul className="rounded-2xl border border-zinc-800 p-5 text-zinc-400">
              <li className="mb-2 text-xs uppercase tracking-widest text-zinc-500">Implemented</li>
              {about.implemented_now.map((i) => (
                <li key={i}>✓ {i}</li>
              ))}
            </ul>
            <ul className="rounded-2xl border border-zinc-800 p-5 text-zinc-500">
              <li className="mb-2 text-xs uppercase tracking-widest">Not implemented</li>
              {about.not_implemented.map((i) => (
                <li key={i}>– {i}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </main>
  )
}
