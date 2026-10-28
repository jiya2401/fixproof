import { useState } from 'react'
import {
  ApiError, createPullRequest, type Certificate, type ProjectInfo, type PullRequestResult,
} from '../api'
import { Button, Card, ErrorBanner, Github, Pill, SectionTitle, Spinner } from '../ui'

/** Repository (and branch, if one was cloned) of a project loaded from a github.com URL. */
export function githubTarget(project?: ProjectInfo | null): { repository: string; branch: string } {
  if (project?.origin !== 'git') return { repository: '', branch: '' }
  const [url, ref = ''] = project.origin_detail.split('@')
  const match = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+?)(?:\.git)?\/?$/.exec(url)
  return match ? { repository: match[1], branch: ref } : { repository: '', branch: '' }
}

const INPUT =
  'mt-1.5 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-2.5 text-sm text-white placeholder:text-zinc-600 focus:border-[var(--accent)] focus:outline-none'

/** Opens a pull request for a verified patch: branch, commit, and a PR with the evidence. */
export default function PullRequestPanel({
  cert, investigationId, githubConfigured, project,
}: {
  cert: Certificate
  investigationId: string
  githubConfigured: boolean
  project?: ProjectInfo | null
}) {
  const target = githubTarget(project)
  const [repository, setRepository] = useState(target.repository)
  const [branch, setBranch] = useState(target.branch)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; code?: string } | null>(null)
  const [pr, setPr] = useState<PullRequestResult | null>(null)

  const eligible =
    (cert.verdict === 'verified' || cert.verdict === 'verified_with_conditions') && !!cert.final_patch
  if (!eligible) return null

  // The server may hold a token; ask for one only when it has none or it was rejected.
  const tokenRejected = error?.code === 'TOKEN_EXPIRED' || error?.code === 'TOKEN_INVALID'
  const showToken = !githubConfigured || tokenRejected
  const canSubmit = !busy && repository.trim() !== '' && (!showToken || token.trim() !== '')

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      setPr(await createPullRequest(investigationId, {
        repository: repository.trim(), baseBranch: branch.trim(), token: token.trim(),
      }))
      setToken('') // do not keep the secret around once it has been used
    } catch (e) {
      setError({
        message: e instanceof Error ? e.message : String(e),
        code: e instanceof ApiError ? e.code : undefined,
      })
    } finally {
      setBusy(false)
    }
  }

  if (pr) {
    const href = pr.url.startsWith('https://') ? pr.url : undefined
    return (
      <Card className="border-emerald-400/30 p-6">
        <SectionTitle hint="opened on GitHub">Pull request</SectionTitle>
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone="green">{pr.reused ? 'already open' : 'created'}</Pill>
          <a href={href} target="_blank" rel="noreferrer"
            className="text-sm font-medium text-white underline decoration-white/30 hover:decoration-white">
            #{pr.number} · {pr.branch} → {pr.base}
          </a>
          {pr.mergeable === true && <Pill tone="green">no merge conflicts</Pill>}
        </div>
        {pr.files_changed.length > 0 && (
          <ul className="mono mt-3 space-y-0.5 text-xs text-zinc-400">
            {pr.files_changed.map((f) => <li key={f.path}>{f.change} · {f.path}</li>)}
          </ul>
        )}
        {pr.warning && <p className="mt-3 text-sm text-amber-300">{pr.warning}</p>}
        <p className="mt-3 text-xs text-zinc-500">
          Review it on GitHub before merging: the description lists the root cause, the fix and the
          attack tests that passed.
        </p>
      </Card>
    )
  }

  return (
    <Card className="p-6">
      <SectionTitle hint="branch fixproof/patch-… · root cause, fix and passing attack tests in the description">
        Open a pull request
      </SectionTitle>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm text-zinc-300">
          Repository
          <input value={repository} onChange={(e) => setRepository(e.target.value)}
            placeholder="owner/repo" autoComplete="off" spellCheck={false} className={INPUT} />
        </label>
        <label className="block text-sm text-zinc-300">
          Base branch <span className="text-zinc-500">(optional)</span>
          <input value={branch} onChange={(e) => setBranch(e.target.value)}
            placeholder="default branch" autoComplete="off" spellCheck={false} className={INPUT} />
        </label>
      </div>
      {showToken && (
        <label className="mt-4 block text-sm text-zinc-300">
          GitHub token <span className="text-zinc-500">(Contents + Pull requests: write · used for this request only, never stored)</span>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="github_pat_… or ghp_…" autoComplete="off" spellCheck={false} className={INPUT} />
        </label>
      )}
      {error && <div className="mt-4"><ErrorBanner message={error.message} /></div>}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button disabled={!canSubmit} onClick={submit}>
          {busy ? <><Spinner /> Creating pull request…</> : <><Github /> Create Pull Request</>}
        </Button>
        {!githubConfigured && (
          <span className="text-xs text-zinc-500">Or set FIXPROOF_GITHUB_TOKEN on the backend.</span>
        )}
      </div>
    </Card>
  )
}
