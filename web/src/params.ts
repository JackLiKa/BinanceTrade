import type { ResearchInput } from './api'

export type GridParams = Omit<ResearchInput, 'symbol' | 'start' | 'end'>

export const DEFAULT_PARAMS: GridParams = {
  capital: 10_000,
  spacing_bp: 120,
  levels: 30,
  leverage: 0.5,
  reanchor_bars: null,
  stop_dd: 0.1,
  maker_fee: 0.0002,
  taker_fee: 0.0005,
  slip_bp: 0.2,
  intrabar: false,
}

const KEY = 'gridtrade.params'

export function loadParams(): GridParams {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...DEFAULT_PARAMS }
    const parsed = JSON.parse(raw) as Partial<GridParams>
    return { ...DEFAULT_PARAMS, ...sanitize(parsed) }
  } catch {
    return { ...DEFAULT_PARAMS }
  }
}

export function saveParams(params: GridParams): void {
  localStorage.setItem(KEY, JSON.stringify(params))
}

function sanitize(parsed: Partial<GridParams>): Partial<GridParams> {
  const out: Partial<GridParams> = {}
  const numbers: Array<keyof GridParams> = [
    'capital',
    'spacing_bp',
    'levels',
    'leverage',
    'maker_fee',
    'taker_fee',
    'slip_bp',
  ]
  for (const key of numbers) {
    const value = parsed[key]
    if (typeof value === 'number' && Number.isFinite(value)) {
      ;(out as Record<string, unknown>)[key] = value
    }
  }
  if (parsed.reanchor_bars === null || typeof parsed.reanchor_bars === 'number') {
    out.reanchor_bars = parsed.reanchor_bars ?? null
  }
  if (parsed.stop_dd === null || typeof parsed.stop_dd === 'number') {
    out.stop_dd = parsed.stop_dd ?? null
  }
  if (typeof parsed.intrabar === 'boolean') out.intrabar = parsed.intrabar
  return out
}

export interface LadderLevel {
  price: number
  side: 'BUY' | 'SELL'
  distancePct: number
  qty: number
  notional: number
}

export interface Preview {
  price: number
  stepPct: number
  upper: number
  lower: number
  levels: LadderLevel[]
  qtyPerLevel: number
  notionalPerLevel: number
  grossNotional: number
  grossLeverage: number
  maxLossToStop: number
  stopPrice: number | null
  roundTripFees: number
  grossProfitPerGrid: number
  netProfitPerGrid: number
  gridYieldPct: number
}

export function buildPreview(price: number | null, params: GridParams): Preview | null {
  if (!price || price <= 0) return null
  const step = params.spacing_bp / 10_000
  const qty = (params.capital * params.leverage) / params.levels / price
  const levels: LadderLevel[] = []
  const buys = Math.ceil(params.levels / 2)
  const sells = params.levels - buys
  for (let i = 1; i <= buys; i += 1) {
    const levelPrice = price * (1 - i * step)
    levels.push({
      price: levelPrice,
      side: 'BUY',
      distancePct: (levelPrice / price - 1) * 100,
      qty,
      notional: qty * levelPrice,
    })
  }
  for (let i = 1; i <= sells; i += 1) {
    const levelPrice = price * (1 + i * step)
    levels.push({
      price: levelPrice,
      side: 'SELL',
      distancePct: (levelPrice / price - 1) * 100,
      qty,
      notional: qty * levelPrice,
    })
  }
  levels.sort((a, b) => b.price - a.price)
  const notionalPerLevel = qty * price
  const grossNotional = notionalPerLevel * params.levels
  const fees = (params.maker_fee + params.slip_bp / 10_000) * 2
  const gross = step
  const net = gross - fees
  return {
    price,
    stepPct: params.spacing_bp / 100,
    upper: price * (1 + sells * step),
    lower: price * (1 - buys * step),
    levels,
    qtyPerLevel: qty,
    notionalPerLevel,
    grossNotional,
    grossLeverage: grossNotional / params.capital,
    maxLossToStop: params.stop_dd === null ? 0 : params.capital * params.stop_dd,
    stopPrice: params.stop_dd === null ? null : price * (1 - params.stop_dd / params.leverage),
    roundTripFees: fees * 100,
    grossProfitPerGrid: gross * 100,
    netProfitPerGrid: net * 100,
    gridYieldPct: notionalPerLevel ? (net * notionalPerLevel * params.levels) / params.capital * 100 : 0,
  }
}
