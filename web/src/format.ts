export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

export function fmtPrice(value: number | null | undefined, digits?: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const d = digits ?? (abs >= 1000 ? 2 : abs >= 10 ? 2 : abs >= 1 ? 3 : 5)
  return value.toLocaleString('en-US', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

export function fmtMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value)
}

export function fmtPct(value: number | null | undefined, digits = 2, sign = true): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const text = `${Math.abs(value).toFixed(digits)}%`
  if (!sign) return text
  if (value > 0) return `+${text}`
  if (value < 0) return `−${text}`
  return text
}

export function fmtRate(rate: number | null | undefined, digits = 4): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—'
  return fmtPct(rate * 100, digits)
}

export function fmtQty(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', { maximumFractionDigits: digits })
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  if (seconds < 90) return `${Math.round(seconds)} 秒`
  if (seconds < 5400) return `${Math.round(seconds / 60)} 分`
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} 小时`
  return `${(seconds / 86400).toFixed(1)} 天`
}

function parseTime(value: string | number | null | undefined): Date | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') {
    return new Date(value < 1e12 ? value * 1000 : value)
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function fmtTime(value: string | number | null | undefined): string {
  const date = parseTime(value)
  if (!date) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}`
}

export function fmtDate(value: string | number | null | undefined): string {
  const date = parseTime(value)
  if (!date) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function fmtMonth(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month] = value.split('-')
  const date = new Date(Number(year), Number(month) - 1, 1)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}年${date.getMonth() + 1}月`
}

export function fmtDateTimeLocal(value: string | number | null | undefined): string {
  const date = parseTime(value)
  if (!date) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

export function timeAgo(value: string | number | null | undefined): string {
  const date = parseTime(value)
  if (!date) return '—'
  const seconds = (Date.now() - date.getTime()) / 1000
  if (seconds < 45) return '刚刚'
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} 分钟前`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时前`
  return `${Math.round(seconds / 86400)} 天前`
}

export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0)
    return 'text-muted'
  return value > 0 ? 'text-up' : 'text-down'
}

export function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function signed(value: number | null | undefined): number {
  return value ?? 0
}
