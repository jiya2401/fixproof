import { useEffect, useState } from 'react'
import { getAbout, type AboutResponse } from './api'

const stages = [
  'Reproduce',
  'Investigate',
  'Minimal patch',
  'Plan attacks',
  'Execute evidence',
  'Fix Certificate',
]

export default function App() {
  const [about, setAbout] = useState<AboutResponse | null>(null)
  const [backendError, setBackendError] = useState(false)

  useEffect(() => {
    getAbout().then(setAbout).catch(() => setBackendError(true))
  }, [])

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-6xl px-6 py-12 md:py-20">
        <header className="border-b border-zinc-800 pb-10">
          <div className="mb-5 inline-flex rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs font-medium tracking-wide text-zinc-300">
            Nebius × NVIDIA Global AI Hackathon · Coding & Agentic Engineering
          </div>
          <h1 className="max-w-4xl text-5xl font-semibold tracking-tight md:text-7xl">
            FixProof
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-zinc-400 md:text-xl">
            AI proposes the fix. <span className="text-zinc-100">Evidence earns the merge.</span>
          </p>
        </header>

        <section className="grid gap-5 py-10 md:grid-cols-3">
          <article className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6 md:col-span-2">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Core thesis</p>
            <h2 className="mt-3 text-2xl font-medium">Do not ask an LLM to grade its own patch.</h2>
            <p className="mt-3 max-w-2xl leading-7 text-zinc-400">
              Nemotron designs the investigation, repair and adversarial verification strategy. Deterministic tools execute the checks and produce the evidence.
            </p>
          </article>

          <article className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Backend</p>
            <p className="mt-3 text-lg font-medium">
              {backendError ? 'Not connected' : about ? 'Connected' : 'Checking…'}
            </p>
            <p className="mt-2 text-sm text-zinc-500">
              {about?.nebius_configured
                ? 'Nebius API key configured'
                : 'Add NEBIUS_API_KEY when starting M1'}
            </p>
          </article>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 md:p-8">
          <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Pipeline</p>
              <h2 className="mt-2 text-2xl font-medium">Evidence-first repair loop</h2>
            </div>
            <p className="text-sm text-zinc-500">M0 scaffold ready · M1 next</p>
          </div>

          <div className="mt-8 grid gap-3 md:grid-cols-6">
            {stages.map((stage, index) => (
              <div key={stage} className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
                <div className="text-xs text-zinc-600">0{index + 1}</div>
                <div className="mt-4 text-sm font-medium">{stage}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-5 grid gap-5 md:grid-cols-2">
          <article className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">AI responsibility</p>
            <ul className="mt-5 space-y-3 text-sm text-zinc-300">
              <li>Root-cause hypotheses</li>
              <li>Minimal repair strategy</li>
              <li>Adversarial scenarios and invariants</li>
              <li>Impact-analysis guidance</li>
            </ul>
          </article>
          <article className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500">Evidence responsibility</p>
            <ul className="mt-5 space-y-3 text-sm text-zinc-300">
              <li>Red → green reproduction</li>
              <li>Existing and generated tests</li>
              <li>Property and mutation testing</li>
              <li>Evidence-backed verdict policy</li>
            </ul>
          </article>
        </section>

        <footer className="mt-12 border-t border-zinc-900 pt-6 text-sm text-zinc-600">
          Python + FastAPI · React + TypeScript · NVIDIA Nemotron · Nebius Token Factory
        </footer>
      </div>
    </main>
  )
}
