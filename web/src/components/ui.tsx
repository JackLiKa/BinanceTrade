import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cx, signClass } from '../format'

export function Card({
  children,
  className,
  pad = true,
}: {
  children: ReactNode
  className?: string
  pad?: boolean
}) {
  return <section className={cx('card', pad && 'p-5', className)}>{children}</section>
}

export function CardHead({
  title,
  hint,
  right,
  className,
}: {
  title: string
  hint?: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <div className={cx('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0 flex-1 basis-48">
        <h2 className="text-[13px] font-semibold tracking-[0.01em] text-ink">{title}</h2>
        {hint ? <p className="mt-1 text-[11px] leading-relaxed text-muted">{hint}</p> : null}
      </div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  )
}

export function Stat({
  label,
  value,
  sub,
  tone,
  mono = true,
  large = false,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: number | null
  mono?: boolean
  large?: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div
        className={cx(
          'mt-1.5 truncate font-semibold tracking-tight',
          mono && 'num',
          large ? 'text-[26px]' : 'text-[17px]',
          tone === undefined ? 'text-ink' : signClass(tone),
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-1 truncate text-[11px] text-muted">{sub}</div> : null}
    </div>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'outline' | 'danger'
  size?: 'sm' | 'md'
  loading?: boolean
}

export function Button({
  variant = 'outline',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const variants = {
    primary:
      'bg-accent text-[#0b0e11] hover:bg-accent-dim border border-transparent font-semibold',
    ghost: 'bg-transparent text-muted hover:text-ink hover:bg-elevated border border-transparent',
    outline: 'bg-elevated text-ink border border-line hover:border-[#3d444d] hover:bg-[#22262e]',
    danger: 'bg-[#2a1216] text-down border border-[#5c2029] hover:bg-[#34151a]',
  }
  return (
    <button
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        size === 'sm' ? 'h-8 px-3 text-[12px]' : 'h-10 px-4 text-[13px]',
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent opacity-70" />
      ) : null}
      {children}
    </button>
  )
}

export function Field({
  label,
  hint,
  children,
  className,
  htmlFor,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
  className?: string
  htmlFor?: string
}) {
  return (
    <label className={cx('block', className)} htmlFor={htmlFor}>
      <span className="label">{label}</span>
      <div className="mt-1.5">{children}</div>
      {hint ? <p className="mt-1.5 text-[11px] leading-snug text-faint">{hint}</p> : null}
    </label>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label?: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        'flex items-center gap-2.5 text-[12px] text-muted transition-opacity disabled:opacity-40',
      )}
    >
      <span
        className={cx(
          'relative h-[20px] w-[34px] rounded-full border transition-colors',
          checked ? 'border-accent/40 bg-accent/25' : 'border-line bg-elevated',
        )}
      >
        <span
          className={cx(
            'absolute top-[2px] h-[14px] w-[14px] rounded-full transition-all',
            checked ? 'left-[17px] bg-accent' : 'left-[2px] bg-[#5e6673]',
          )}
        />
      </span>
      {label}
    </button>
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: 'neutral' | 'up' | 'down' | 'accent' | 'info' | 'warn'
  className?: string
}) {
  const tones = {
    neutral: 'border-line bg-elevated text-muted',
    up: 'border-up/25 bg-up/10 text-up',
    down: 'border-down/25 bg-down/10 text-down',
    accent: 'border-accent/30 bg-accent/10 text-accent',
    info: 'border-info/25 bg-info/10 text-info',
    warn: 'border-[#f0b90b]/30 bg-[#f0b90b]/10 text-[#f0b90b]',
  }
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-md border px-1.5 py-[2px] font-mono text-[10px] uppercase tracking-wide',
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('skeleton', className)} />
}

export function Empty({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line px-6 py-12 text-center">
      <p className="text-[13px] font-medium text-ink">{title}</p>
      <p className="max-w-sm text-[12px] leading-relaxed text-muted">{body}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-down/30 bg-down/8 px-3 py-2 text-[12px] leading-relaxed text-down">
      {children}
    </div>
  )
}

export function Progress({ value, message }: { value: number; message?: string | null }) {
  return (
    <div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-elevated">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-faint">
        <span>{message || '计算中'}</span>
        <span>{Math.round(value * 100)}%</span>
      </div>
    </div>
  )
}

export function useNow(interval = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), interval)
    return () => window.clearInterval(id)
  }, [interval])
  return now
}

export function Delta({
  value,
  suffix = '%',
  digits = 2,
}: {
  value: number | null | undefined
  suffix?: string
  digits?: number
}) {
  if (value === null || value === undefined || !Number.isFinite(value)) return <span className="text-muted">—</span>
  const text = `${Math.abs(value).toFixed(digits)}${suffix}`
  return (
    <span className={signClass(value)}>
      {value > 0 ? '+' : value < 0 ? '−' : ''}
      {text}
    </span>
  )
}
