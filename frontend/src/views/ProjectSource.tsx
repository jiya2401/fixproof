import { useRef, useState } from 'react'
import {
  projectFromGit, projectFromLocal, uploadProject, type AboutResponse,
} from '../api'
import type { Source } from '../types'
import { Button, Card, ErrorBanner, Flask, Folder, Github, Pill, Spinner, Upload } from '../ui'

type Tab = 'samples' | 'zip' | 'git' | 'local'

const TABS: { id: Tab; label: string; icon: typeof Upload }[] = [
  { id: 'zip', label: 'Upload your project', icon: Upload },
  { id: 'git', label: 'GitHub URL', icon: Github },
  { id: 'local', label: 'Local folder', icon: Folder },
  { id: 'samples', label: 'Sample bugs', icon: Flask },
]

export default function ProjectSource({
  about, onSelect,
}: { about: AboutResponse | null; onSelect: (source: Source) => void }) {
  const [tab, setTab] = useState<Tab>('zip')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const [gitUrl, setGitUrl] = useState('')
  const [gitRef, setGitRef] = useState('')
  const [localPath, setLocalPath] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  async function guarded(task: () => Promise<Source>) {
    setBusy(true)
    setError(null)
    try {
      onSelect(await task())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const upload = (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) return setError('Please choose a .zip file.')
    guarded(async () => ({ kind: 'project', info: await uploadProject(file) }))
  }

  return (
    <Card className="p-6 fade-up">
      <div role="tablist" aria-label="Project source" className="mb-6 flex flex-wrap gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} role="tab" aria-selected={tab === id}
            onClick={() => { setTab(id); setError(null) }}
            className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-sm transition ${
              tab === id
                ? 'border-[var(--accent)]/50 bg-[var(--accent)]/10 text-white'
                : 'border-white/10 text-zinc-400 hover:bg-white/5 hover:text-zinc-200'}`}>
            <Icon className="h-4 w-4" /> {label}
          </button>
        ))}
      </div>

      {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

      {tab === 'zip' && (
        <div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]) }}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-14 text-center transition ${
              drag ? 'border-[var(--accent)] bg-[var(--accent)]/5' : 'border-white/15'}`}>
            {busy ? <Spinner className="h-8 w-8 text-[var(--accent)]" /> : <Upload className="h-8 w-8 text-zinc-400" />}
            <p className="mt-4 text-base font-medium text-zinc-100">
              {busy ? 'Unpacking safely…' : 'Drop a .zip of your project here'}
            </p>
            <p className="mt-1 text-sm text-zinc-500">
              Up to {about?.max_project_mb ?? 50} MB. Zip the project folder (the one containing your tests).
            </p>
            <input ref={fileInput} type="file" accept=".zip,application/zip" className="hidden"
              onChange={(e) => upload(e.target.files?.[0])} />
            <Button className="mt-5" variant="ghost" disabled={busy} onClick={() => fileInput.current?.click()}>
              Choose file
            </Button>
          </div>
          <Limits />
        </div>
      )}

      {tab === 'git' && (
        <form className="space-y-4" onSubmit={(e) => {
          e.preventDefault()
          guarded(async () => ({ kind: 'project', info: await projectFromGit(gitUrl.trim(), gitRef.trim()) }))
        }}>
          <label className="block text-sm text-zinc-300">
            Repository URL
            <input value={gitUrl} onChange={(e) => setGitUrl(e.target.value)}
              placeholder="https://github.com/owner/repo"
              className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none" />
          </label>
          <label className="block text-sm text-zinc-300">
            Branch or tag <span className="text-zinc-500">(optional)</span>
            <input value={gitRef} onChange={(e) => setGitRef(e.target.value)} placeholder="main"
              className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none" />
          </label>
          <Button type="submit" disabled={busy || !gitUrl.trim()}>
            {busy ? <><Spinner /> Cloning…</> : 'Fetch repository'}
          </Button>
          <p className="text-xs text-zinc-500">
            Public https URLs on github.com, gitlab.com or bitbucket.org. Shallow clone, no submodules,
            no git hooks, no credentials. The code only ever runs inside the offline sandbox.
          </p>
          <Limits />
        </form>
      )}

      {tab === 'local' && (
        about?.project_sources.local ? (
          <form className="space-y-4" onSubmit={(e) => {
            e.preventDefault()
            guarded(async () => ({ kind: 'project', info: await projectFromLocal(localPath.trim()) }))
          }}>
            <label className="block text-sm text-zinc-300">
              Folder on the machine running the FixProof backend
              <input value={localPath} onChange={(e) => setLocalPath(e.target.value)}
                placeholder="E:\projects\my-app"
                className="mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none" />
            </label>
            <Button type="submit" disabled={busy || !localPath.trim()}>
              {busy ? <><Spinner /> Copying…</> : 'Use this folder'}
            </Button>
            <p className="text-xs text-zinc-500">Your folder is copied; the original is never modified.</p>
            <Limits />
          </form>
        ) : (
          <div className="rounded-xl border border-white/10 bg-black/20 p-5 text-sm text-zinc-400">
            <p className="font-medium text-zinc-200">Local folders are switched off.</p>
            <p className="mt-2">
              To allow them, set the folders FixProof may read in your <code className="mono text-zinc-200">.env</code> and
              restart the backend:
            </p>
            <pre className="mono mt-3 overflow-x-auto rounded-lg bg-black/40 p-3 text-xs text-zinc-300">FIXPROOF_LOCAL_PATH_ROOTS=E:\projects</pre>
          </div>
        )
      )}

      {tab === 'samples' && (
        <div className="grid gap-3 sm:grid-cols-2">
          {(about?.example_cases ?? []).map((name) => (
            <button key={name} disabled={busy}
              onClick={() => onSelect({ kind: 'example', name, issue: about?.example_issues[name] ?? '' })}
              className="rounded-xl border border-white/10 bg-black/20 p-4 text-left transition hover:border-[var(--accent)]/50 hover:bg-white/5">
              <div className="flex items-center justify-between">
                <span className="mono text-sm font-medium text-zinc-100">{name}</span>
                <Pill tone="gray">sample</Pill>
              </div>
              <p className="mt-2 line-clamp-2 text-xs text-zinc-500">{about?.example_issues[name]}</p>
            </button>
          ))}
          {!about && <p className="text-sm text-zinc-500">Connect the backend to load samples.</p>}
        </div>
      )}
    </Card>
  )
}

function Limits() {
  return (
    <p className="mt-4 text-xs leading-relaxed text-zinc-500">
      <span className="text-zinc-400">What works today:</span> Python (pytest), Go (go&amp;nbsp;test),
      and JavaScript/TypeScript (Vitest) projects. The sandbox is offline — dependencies must be
      pre-installed in the sandbox image. Missing packages are detected and reported with the exact fix.
    </p>
  )
}
