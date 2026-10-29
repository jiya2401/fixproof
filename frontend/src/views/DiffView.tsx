export default function DiffView({ diff }: { diff: string }) {
  const lines = diff.replace(/\n$/, '').split('\n')
  return (
    <div className="overflow-x-auto rounded-xl border border-white/10 bg-black/40">
      <pre className="mono min-w-full py-2 text-[12.5px] leading-6">
        {lines.map((line, i) => {
          const kind =
            line.startsWith('+++') || line.startsWith('---') ? 'meta'
            : line.startsWith('@@') ? 'hunk'
            : line.startsWith('+') ? 'add'
            : line.startsWith('-') ? 'del' : 'ctx'
          const style = {
            meta: 'text-zinc-500',
            hunk: 'bg-sky-400/10 text-sky-300',
            add: 'bg-emerald-400/10 text-emerald-200',
            del: 'bg-red-400/10 text-red-200',
            ctx: 'text-zinc-400',
          }[kind]
          return (
            <div key={i} className={`flex px-4 ${style}`}>
              <span className="w-5 shrink-0 select-none text-zinc-600">{kind === 'add' ? '+' : kind === 'del' ? '−' : ' '}</span>
              <span className="whitespace-pre">{kind === 'add' || kind === 'del' ? line.slice(1) : line}</span>
            </div>
          )
        })}
      </pre>
    </div>
  )
}
