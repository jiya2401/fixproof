import { useCallback, useEffect, useState } from 'react'
import {
  getAbout, startInvestigation, type AboutResponse, type Certificate, type InvestigationState,
} from './api'
import type { Source } from './types'
import { Button, ErrorBanner, Pill, Shield, Spinner } from './ui'
import BenchmarkView from './views/BenchmarkView'
import CertificateView from './views/CertificateView'
import HowItWorks from './views/HowItWorks'
import ProjectSource from './views/ProjectSource'
import RunMonitor from './views/RunMonitor'
import ScanStep from './views/ScanStep'

type Tab = 'repair' | 'benchmark' | 'how'
type Step = 'source' | 'scan' | 'run' | 'result'
const STEP_LABELS = ['Project', 'Pick the bug', 'Run', 'Certificate']
const STEP_ORDER: Step[] = ['source', 'scan', 'run', 'result']

export default function App() {
  const [about, setAbout] = useState<AboutResponse | null>(null)
  const [backendDown, setBackendDown] = useState(false)
  const [tab, setTab] = useState<Tab>('repair')
  const [step, setStep] = useState<Step>('source')
  const [source, setSource] = useState<Source | null>(null)
  const [investigationId, setInvestigationId] = useState<string | null>(null)
  const [cert, setCert] = useState<Certificate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    getAbout().then(setAbout).catch(() => setBackendDown(true))
  }, [])

  const reset = () => {
    setStep('source'); setSource(null); setInvestigationId(null); setCert(null); setError(null)
  }

  async function run(issue: string, targets: string[]) {
    if (!source) return
    setStarting(true)
    setError(null)
    try {
      const id = await startInvestigation(
        source.kind === 'example'
          ? { issue, exampleCase: source.name }
          : { issue, projectId: source.info.id, reproTargets: targets },
      )
      setInvestigationId(id)
      setStep('run')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  const onDone = useCallback((state: InvestigationState) => {
    setCert(state.certificate)
    setStep('result')
  }, [])

  const stepIndex = STEP_ORDER.indexOf(step)

  return (
    <div className="min-h-screen text-zinc-100">
      <header className="sticky top-0 z-20 border-b border-white/8 bg-[#06080c]/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-3">
          <button onClick={() => { setTab('repair'); reset() }} className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--accent)] text-black"><Shield className="h-5 w-5" /></span>
            <span className="text-lg font-semibold tracking-tight">FixProof</span>
          </button>
          <nav className="flex gap-1 text-sm" aria-label="Sections">
            {([['repair', 'Repair'], ['benchmark', 'Benchmark'], ['how', 'How it works']] as const).map(([id, name]) => (
              <button key={id} onClick={() => setTab(id)} aria-current={tab === id ? 'page' : undefined}
                className={`rounded-lg px-3 py-1.5 transition ${tab === id ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}>
                {name}
              </button>
            ))}
          </nav>
          <div className="flex flex-wrap gap-2">
            {backendDown ? <Pill tone="red">backend offline</Pill> : about ? (
              <>
                <Pill tone="green">backend ok</Pill>
                <Pill tone={about.nebius_configured ? 'green' : 'amber'}>{about.nebius_configured ? 'Nebius key set' : 'no Nebius key'}</Pill>
                <Pill tone="blue">{about.nebius_model.split('/').pop()}</Pill>
                <Pill tone="gray">sandbox: {about.sandbox_mode}</Pill>
              </>
            ) : <Spinner className="h-4 w-4 text-zinc-500" />}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-20 pt-10">
        {backendDown && (
          <div className="mb-6">
            <ErrorBanner message="Cannot reach the backend. Start it with: cd backend && uvicorn app.main:app --port 8000" />
          </div>
        )}

        {tab === 'repair' && (
          <>
            {step === 'source' && (
              <section className="mb-10 max-w-3xl fade-up">
                <p className="text-xs uppercase tracking-[0.22em] text-zinc-500">Nebius Token Factory × NVIDIA Nemotron</p>
                <h1 className="mt-3 text-5xl font-semibold leading-[1.05] tracking-tight text-white sm:text-6xl">
                  AI proposes the fix.<br /><span className="text-[var(--accent)]">Evidence earns the merge.</span>
                </h1>
                <p className="mt-5 max-w-2xl text-lg text-zinc-400">
                  Point FixProof at a Python project with a failing test. It reproduces the bug, lets Nemotron
                  propose a patch, then tries to <i>break</i> that patch with executed tests that quote your own
                  spec. You get a verdict backed by evidence, not a model's opinion.
                </p>
                <ul className="mt-6 flex flex-wrap gap-2 text-sm">
                  {['Reproduced before it is patched', 'Attacked by spec-quoted tests', 'Verdict computed, never claimed'].map((t) => (
                    <li key={t} className="rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 text-zinc-300">{t}</li>
                  ))}
                </ul>
              </section>
            )}

            <ol className="mb-6 flex flex-wrap items-center gap-2 text-sm" aria-label="Progress">
              {STEP_LABELS.map((name, i) => (
                <li key={name} className="flex items-center gap-2">
                  <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                    i < stepIndex ? 'bg-emerald-400/20 text-emerald-300'
                    : i === stepIndex ? 'bg-[var(--accent)] text-black' : 'bg-white/10 text-zinc-500'}`}>{i + 1}</span>
                  <span className={i === stepIndex ? 'text-white' : 'text-zinc-500'}>{name}</span>
                  {i < STEP_LABELS.length - 1 && <span className="mx-1 text-zinc-700">—</span>}
                </li>
              ))}
            </ol>

            {error && <div className="mb-5"><ErrorBanner message={error} /></div>}

            {step === 'source' && (
              <ProjectSource about={about} onSelect={(s) => { setSource(s); setStep('scan'); setError(null) }} />
            )}
            {step === 'scan' && source && (
              <>
                <ScanStep source={source} onBack={reset} onRun={run} />
                {starting && <p className="mt-4 flex items-center gap-2 text-sm text-zinc-400"><Spinner /> Starting…</p>}
              </>
            )}
            {step === 'run' && investigationId && (
              <RunMonitor investigationId={investigationId} onDone={onDone} onBack={() => setStep('scan')} />
            )}
            {step === 'result' && cert && (
              <CertificateView cert={cert} onReset={reset} investigationId={investigationId ?? undefined}
                githubConfigured={about?.github_configured ?? false}
                project={source?.kind === 'project' ? source.info : null}
                onReverify={(newId) => { setCert(null); setInvestigationId(newId); setStep('run') }} />
            )}
          </>
        )}

        {tab === 'benchmark' && <BenchmarkView />}
        {tab === 'how' && <HowItWorks about={about} />}
      </main>

      <footer className="border-t border-white/8 py-6 text-center text-xs text-zinc-600">
        FixProof · Nebius × NVIDIA Global AI Hackathon 2026 · Coding &amp; Agentic Engineering ·{' '}
        <Button variant="ghost" className="!px-2 !py-0.5 !text-xs" onClick={() => setTab('how')}>how it works</Button>
      </footer>
    </div>
  )
}
