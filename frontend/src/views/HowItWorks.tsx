import type { AboutResponse } from '../api'
import { Card, Pill, SectionTitle } from '../ui'

const FLOW = [
  ['Reproduce', 'Your failing test must fail before any patch. If it does not, FixProof stops: no model call, no verdict.', 'tool'],
  ['Hypothesize', 'Nemotron proposes root causes (recorded as untested).', 'model'],
  ['Patch', 'Nemotron proposes exact SEARCH/REPLACE edits. Code verifies them and writes the diff. Edits to tests are rejected.', 'model'],
  ['Verify', 'Apply the patch, re-run the bug test and your full suite on a fresh sandbox copy.', 'tool'],
  ['Attack', 'Nemotron writes adversarial tests that must quote your issue or docstrings. The sandbox executes them.', 'model'],
  ['Iterate', 'Any executed counterexample goes back to the fixer. Bounded attempts; repeats are detected.', 'tool'],
  ['Certify', 'A policy turns executed results into a verdict and seals a hashed certificate.', 'tool'],
] as const

const VERDICTS = [
  ['Verified', 'green', 'All mandatory checks executed, none found a counterexample, isolation verified.'],
  ['Verified with conditions', 'amber', 'All mandatory checks passed, but something limits trust (e.g. weaker sandbox, a failed optional check).'],
  ['Not verified', 'red', 'An executed check failed: a counterexample, a regression, or the bug still reproduces.'],
  ['Insufficient evidence', 'gray', 'A required check did not run properly: skipped, errored, zero tests, or the bug never reproduced.'],
] as const

export default function HowItWorks({ about }: { about: AboutResponse | null }) {
  return (
    <div className="space-y-6 fade-up">
      <Card className="p-6">
        <SectionTitle>The loop</SectionTitle>
        <ol className="space-y-3">
          {FLOW.map(([name, text, who], i) => (
            <li key={name} className="flex gap-4">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-semibold text-zinc-300">{i + 1}</span>
              <div>
                <p className="flex items-center gap-2 text-sm font-medium text-white">
                  {name} <Pill tone={who === 'model' ? 'blue' : 'green'}>{who === 'model' ? 'Nemotron' : 'deterministic'}</Pill>
                </p>
                <p className="mt-0.5 text-sm text-zinc-400">{text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-5 rounded-xl border border-white/10 bg-black/20 p-4 text-sm text-zinc-300">
          The model never grades its own work. It proposes; sandboxed tools execute; a policy decides.
        </p>
      </Card>

      <Card className="p-6">
        <SectionTitle>Verdicts</SectionTitle>
        <dl className="grid gap-3 md:grid-cols-2">
          {VERDICTS.map(([name, tone, text]) => (
            <div key={name} className="rounded-xl border border-white/10 bg-black/20 p-4">
              <dt><Pill tone={tone}>{name}</Pill></dt>
              <dd className="mt-2 text-sm text-zinc-400">{text}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-xs text-zinc-500">A verdict is never a proof of correctness. It says no counterexample was found by the checks that actually ran.</p>
      </Card>

      {about && (
        <div className="grid gap-6 md:grid-cols-2">
          <Card className="p-6">
            <SectionTitle>Working today</SectionTitle>
            <ul className="space-y-1.5 text-sm text-zinc-300">{about.implemented_now.map((i) => <li key={i}>✓ {i}</li>)}</ul>
          </Card>
          <Card className="p-6">
            <SectionTitle>Not built yet</SectionTitle>
            <ul className="space-y-1.5 text-sm text-zinc-500">{about.not_implemented.map((i) => <li key={i}>– {i}</li>)}</ul>
          </Card>
        </div>
      )}
    </div>
  )
}
