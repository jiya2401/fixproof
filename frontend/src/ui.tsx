import type { ReactNode } from 'react'

type IconProps = { className?: string }
const base = (d: ReactNode, className = 'h-4 w-4') => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" className={className} aria-hidden="true">{d}</svg>
)
export const Check = ({ className }: IconProps) => base(<path d="M20 6 9 17l-5-5" />, className)
export const Cross = ({ className }: IconProps) => base(<path d="M18 6 6 18M6 6l12 12" />, className)
export const Alert = ({ className }: IconProps) =>
  base(<><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></>, className)
export const Shield = ({ className }: IconProps) =>
  base(<><path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" /></>, className)
export const Upload = ({ className }: IconProps) =>
  base(<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></>, className)
export const Github = ({ className }: IconProps) =>
  base(<path d="M9 19c-4 1.4-4-2-6-2m12 4v-3.5a3 3 0 0 0-.8-2.3c2.700-.3 5.500-1.300 5.500-6a4.700 4.700 0 0 0-1.300-3.300 4.300 4.300 0 0 0-.1-3.200s-1-.3-3.400 1.300a11.700 11.700 0 0 0-6.200 0C6.300 2.400 5.300 2.700 5.300 2.700a4.300 4.300 0 0 0-.1 3.200A4.700 4.700 0 0 0 3.900 9.200c0 4.700 2.800 5.700 5.500 6A3 3 0 0 0 8.600 17.500V21" />, className)
export const Folder = ({ className }: IconProps) =>
  base(<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />, className)
export const Flask = ({ className }: IconProps) =>
  base(<><path d="M9 3h6M10 3v6L4.500 18.500A2 2 0 0 0 6.300 21h11.400a2 2 0 0 0 1.800-2.500L14 9V3" /><path d="M7.500 15h9" /></>, className)
export const Copy = ({ className }: IconProps) =>
  base(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>, className)
export const Download = ({ className }: IconProps) =>
  base(<><path d="M12 4v12M7 11l5 5 5-5" /><path d="M4 20h16" /></>, className)
export const Bolt = ({ className }: IconProps) => base(<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" />, className)
export const Spinner = ({ className = 'h-4 w-4' }: IconProps) => (
  <svg viewBox="0 0 24 24" className={`${className} animate-spin`} fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
)

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`glass rounded-2xl ${className}`}>{children}</section>
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-400">{children}</h3>
      {hint && <span className="text-xs text-zinc-500">{hint}</span>}
    </div>
  )
}

const TONES = {
  green: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300',
  red: 'border-red-400/30 bg-red-400/10 text-red-300',
  amber: 'border-amber-400/30 bg-amber-400/10 text-amber-300',
  gray: 'border-white/10 bg-white/5 text-zinc-300',
  blue: 'border-sky-400/30 bg-sky-400/10 text-sky-300',
} as const
export type Tone = keyof typeof TONES

export function Pill({ children, tone = 'gray' }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export function Button({
  children, onClick, disabled, variant = 'primary', type = 'button', className = '',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'ghost'
  type?: 'button' | 'submit'
  className?: string
}) {
  const styles =
    variant === 'primary'
      ? 'bg-[var(--accent)] text-black hover:brightness-110 disabled:opacity-40'
      : 'border border-white/15 bg-white/5 text-zinc-200 hover:bg-white/10 disabled:opacity-40'
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${styles} ${className}`}>
      {children}
    </button>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/20 p-4">
      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-50">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-200">
      <Alert className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  )
}

export const formatBytes = (n: number) =>
  n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`
