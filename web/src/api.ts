export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
export type RunKind = 'replay' | 'walkforward' | 'sweep'

export interface Run {
  id: string
  kind: RunKind
  symbol: string
  status: RunStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  params: Record<string, unknown>
  summary: Record<string, number | boolean | null> | null
  error: string | null
  progress: number
  message: string | null
  cancel_requested: boolean
}

export interface MarketSnapshot {
  symbol?: string
  source: 'binance' | 'dataset'
  mark_price: number | null
  index_price?: number | null
  last_price?: number | null
  change_24h_pct: number | null
  high_24h?: number | null
  low_24h?: number | null
  volume_24h?: number | null
  quote_volume_24h?: number | null
  last_funding_rate: number | null
  next_funding_time?: string | null
  as_of?: string | null
  bar_age_minutes?: number | null
  fetched_at?: string
}

export interface DatasetContract {
  tick_size: number
  step_size: number
  min_notional: number
  max_orders: number
}

export interface TradingSession {
  market: string
  start: string
  end: string
  type: string
}

export interface DatasetQuality {
  symbol: string
  bars: number
  start: string
  end: string
  expected_bars: number
  missing_bars: number
  duplicate_timestamps: number
  out_of_order: boolean
  max_gap_minutes: number
  median_gap_minutes: number | null
  gap_count: number
  coverage_pct: number | null
  zero_volume_pct: number
  bad_ohlc: number
  price_min: number
  price_max: number
  last_close: number
  bytes: number
  funding_settlements: number
  funding_median_interval_hours: number | null
  funding_max_interval_hours: number | null
  last_funding: string | null
  filters: DatasetContract
  contract: {
    contract_type: string | null
    underlying_type: string | null
    onboard: string | null
    funding_interval_hours: number | null
  }
  schedule: {
    sessions: number
    no_trading_recent: TradingSession[]
    markets: string[]
  }
}

export interface CandleResponse {
  symbol: string
  interval: string
  count: number
  from: number | null
  to: number | null
  candles: [number, number, number, number, number, number][]
}

export interface FundingPoint {
  time: number
  rate: number
  mark_price: number | null
}

export interface FundingResponse {
  symbol: string
  points: FundingPoint[]
  summary: {
    count: number
    mean_rate: number
    median_rate: number
    positive_pct: number
    annualized_pct: number
    interval_hours: number
    last: string | null
  }
}

export interface EquityPoint {
  t: number
  v: number
}

export type PaperStatus = 'running' | 'stopped' | 'halted'

export interface PaperFill {
  id: number
  ts: string
  symbol: string
  side: 'BUY' | 'SELL'
  price: number
  qty: number
  fee: number
  realized: number
  slip: number
  action?: string
  reason: string
}

export interface PaperFunding {
  id: number
  ts: string
  symbol: string
  rate: number
  payment: number
  position: number
  mark: number
}

export interface PaperConfigView {
  enabled: boolean
  autostart: boolean
  source: string
  symbols: string[]
  capital: number
  leverage: number
  spacing_bp: number
  levels: number
  stop_dd_pct: number
  maker_fee_bp: number
  taker_fee_bp: number
  poll_seconds: number
}

export interface PaperSymbolView {
  symbol: string
  mark_price: number
  index_price: number
  change_24h_pct: number | null
  funding_rate: number
  next_funding_time: string | null
  position: number
  avg_entry: number
  unrealized: number
  notional: number
  anchor: number
  step: number
  unit: number
  level: number
  buy_price: number
  sell_price: number
  max_position: number
  maker_fee_bp: number
  taker_fee_bp: number
  fee_source: 'exchange' | 'config'
  liquidation_price?: number | null
  liquidation_fee_bp?: number
}

export interface PaperState {
  enabled: boolean
  status: PaperStatus
  symbols: string[]
  source: string
  last_tick_at: string | null
  last_error: string | null
  config: PaperConfigView
  account: {
    capital: number
    cash: number
    equity: number
    unrealized: number
    realized: number
    fees: number
    funding: number
    funding_income?: number
    slippage: number
    gross_notional: number
    margin_used: number
    wallet_balance?: number
    maintenance_margin?: number
    margin_ratio?: number | null
    liquidation_fee_bp?: number
    insurance_fund_balance?: number
    leverage: number
    peak_equity: number
    drawdown_pct: number
    return_pct: number
  }
  portfolio: PaperSymbolView[]
  liquidation?: {
    ts: string
    reason: string
    equity_before: number
    maintenance_margin: number
    cash_after: number
    bad_debt: number
    insurance_covered?: number
    uncovered_bad_debt?: number
    liquidation_fee: number
    positions: Array<{ symbol: string; qty: number; mark: number; avg_entry: number }>
  } | null
  fills: PaperFill[]
  funding: PaperFunding[]
  equity: Array<[string, number]>
  cost?: BinanceCostReport
}

export interface PaperRun {
  id: number
  started_at: string | null
  ended_at: string
  reason: string
  status: string
  capital: number
  equity: number
  return_pct: number
  max_dd_pct: number
  fees: number
  funding: number
  slippage: number
  fills: number
  config: Record<string, unknown>
}

export interface PaperConfigInput {
  symbols?: string[]
  capital?: number
  leverage?: number
  spacing_bp?: number
  levels?: number
  stop_dd_pct?: number
  maker_fee_bp?: number
  taker_fee_bp?: number
  poll_seconds?: number
}

export interface LiveConfigView {
  enabled: boolean
  trading_enabled: boolean
  exchange: string
  configured: boolean
  api_key_hint: string
  has_secret: boolean
  subaccount: string
  max_notional: number
  max_order_notional: number
  max_position_notional: number
  max_open_orders: number
  poll_seconds: number
}

export interface LivePosition {
  contract: string
  size: number
  entry_price: number | null
  mark_price: number
  liq_price: number | null
  leverage: number | null
  margin: number | null
  unrealized: number | null
  realized: number | null
  notional: number
  quanto_multiplier: number
}

export interface LiveAnalysis {
  equity: number
  available: number
  unrealized: number
  realized: number
  fees_paid: number
  funding_paid: number
  gross_notional: number
  net_notional: number
  position_margin: number
  order_margin: number
  maintenance_margin: number
  margin_ratio: number | null
  open_orders: number
  open_orders_notional: number
  trade_count: number
  limits: {
    max_notional: number
    max_order_notional: number
    max_position_notional: number
    max_open_orders: number
  }
  warnings: string[]
}

export interface LiveSnapshot {
  configured: boolean
  enabled: boolean
  trading_enabled: boolean
  exchange: string
  config: LiveConfigView
  error: string | null
  account: {
    currency: string | null
    total: number
    available: number
    unrealized: number
    position_margin: number
    order_margin: number
    maintenance_margin: number
    in_dual_mode: boolean
  } | null
  positions: LivePosition[]
  orders: Array<Record<string, unknown>>
  trades: Array<Record<string, unknown>>
  ledger: Array<Record<string, unknown>>
  fees: Array<Record<string, unknown>>
  analysis: LiveAnalysis | null
  synced_at: number | null
}

export interface LiveConfigInput {
  api_key?: string
  api_secret?: string
  enabled?: boolean
  trading_enabled?: boolean
  confirm_trading?: boolean
  subaccount?: string
  max_notional?: number
  max_order_notional?: number
  max_position_notional?: number
  max_open_orders?: number
  clear_credentials?: boolean
}

export interface LiveOrderInput {
  contract: string
  size: number
  price?: string
  tif?: string
  reduce_only?: boolean
}

// -- Binance execution node (Tokyo, tunnel-only, read-only from the panel) ----

export interface BinanceCostReport {
  maker_fee_bp?: number
  taker_fee_bp?: number
  slippage_bp?: number
  funding_rate_8h?: number
  funding_bp_per_8h?: number
  round_trip_maker_bp?: number
  round_trip_taker_bp?: number
  round_trip_taker_8h_bp?: number
  breakeven_spacing_bp?: number
  assumed?: { maker_fee_bp?: number; taker_fee_bp?: number; slippage_bp?: number }
  spacing_bp?: number
  round_trip_bp?: number
  net_edge_bp?: number
  is_profitable?: boolean
}

export interface BinanceNodeHealth {
  ok: boolean
  configured: boolean
  trading_enabled: boolean
  base_url: string
  kill_switch: boolean
  server_offset_ms: number
  position_mode?: string
  dual_side_position?: boolean | null
  cost?: BinanceCostReport
  reachable: boolean
  server_time?: { serverTime: number }
  error?: string
}

export interface BinanceAccountView {
  feeTier?: number
  canTrade?: boolean
  canDeposit?: boolean
  canWithdraw?: boolean
  multiAssetsMargin?: boolean
  totalWalletBalance?: string
  availableBalance?: string
  totalUnrealizedProfit?: string
  totalPositionInitialMargin?: string
  totalOpenOrderInitialMargin?: string
}

export interface BinancePositionView {
  symbol: string
  positionAmt: string
  entryPrice: string
  markPrice?: string
  unRealizedProfit?: string
  positionSide?: string
  leverage?: string
  liquidationPrice?: string
}

export interface BinanceOrderView {
  orderId: number
  clientOrderId?: string
  symbol: string
  side: string
  type: string
  price: string
  avgPrice?: string
  origQty: string
  executedQty?: string
  status: string
  positionSide?: string
  action?: string
  actionLabel?: string
  notional?: number
  cumQuote?: string
  time?: number
  reduceOnly?: boolean
}

export interface BinanceFillView {
  id?: number
  orderId?: number
  symbol: string
  side: string
  positionSide?: string
  action?: string
  actionLabel?: string
  price: string
  qty: string
  quoteQty?: string
  notional?: number
  commission?: string
  commissionAsset?: string
  feeBp?: number
  realizedPnl?: string
  maker?: boolean
  time?: number
}

export interface BinanceAlert {
  ts: number
  level: 'info' | 'warn' | 'critical'
  kind: string
  message: string
  details?: Record<string, unknown>
}

export interface BinanceState {
  node_url: string
  health?: BinanceNodeHealth
  account?: { ok: boolean; account: BinanceAccountView }
  positions?: { ok: boolean; positions: BinancePositionView[] }
  orders?: { ok: boolean; orders: BinanceOrderView[] }
  fills?: { ok: boolean; fills: BinanceFillView[] }
  history?: { ok: boolean; orders: BinanceOrderView[] }
  alerts?: { ok: boolean; alerts: BinanceAlert[]; last_run_at?: number; last_error?: string | null }
  insurance?: { ok: boolean; assets: Array<{ asset: string; marginBalance: string; updateTime: number }>; symbols_count?: number }
  adl_risk?: { ok: boolean; data: { symbol: string; adlRisk: string; updateTime: number } | Array<{ symbol: string; adlRisk: string; updateTime: number }> }
  errors?: Record<string, string>
}

export interface Fill {
  ts: string
  side: string
  qty: number
  price: number
  fee: number
  tag: string
  liquidity: 'MAKER' | 'TAKER'
  client_id: string
}

export interface OpenOrder {
  client_id: string
  side: string
  type: string
  qty: number
  price: number | null
  filled_qty: number
  tag: string
  status: string
}

export interface MonthRow {
  month: string
  ret: number
  dd: number
  trades: number
  fees: number
  funding: number | null
  funding_income?: number
  halted: boolean
}

export interface ReplaySummary {
  total_return: number
  ann_return: number
  max_dd: number
  sharpe: number
  final_equity: number
  trades: number
  fees: number
  funding: number
  funding_pct_of_capital?: number
  turnover_x?: number
  avg_inventory_pct?: number
  halted: boolean
  liquidated?: boolean
  liquidation_price?: number | null
  liquidation_time?: string | null
  liquidation?: Record<string, string | number> | null
  final_position?: number
  bars?: number
  start?: string
  end?: string
  strategy_state?: Record<string, number | string>
  [key: string]: number | boolean | string | null | Record<string, number | string> | undefined
}

export interface RunMeta {
  symbol: string
  params: Record<string, unknown>
  generated_at: string
  duration_s: number
  bars: number
  start: string
  end: string
  min_days?: number
  axes?: { spacings: number[]; levels: number[]; leverages: number[] }
}

export interface ReplayArtifact {
  kind: 'replay'
  meta: RunMeta
  summary: ReplaySummary
  capital: number
  equity: { points: EquityPoint[]; sampled_from: number; first: number; last: number }
  drawdown: { points: EquityPoint[] }
  fills: Fill[]
  fills_truncated: boolean
  months: MonthRow[]
  orders: {
    counts: Record<string, number>
    rejection_reasons: Array<{ reason: string; count: number }>
    open: OpenOrder[]
  }
}

export interface WalkforwardRow {
  month: string
  ret: number
  ann_return: number
  max_dd: number
  sharpe: number
  trades: number
  fees: number
  funding: number
  halted: boolean
}

export interface WalkforwardArtifact {
  kind: 'walkforward'
  meta: RunMeta
  rows: WalkforwardRow[]
  cumulative: EquityPoint[]
  summary: {
    months: number
    mean_ret: number
    median_ret: number
    worst_ret: number
    best_ret: number
    positive_months: number
    stops: number
    total_return: number
    [key: string]: number | string | null
  }
}

export interface SweepRow {
  spacing_bp: number
  levels: number
  leverage: number
  total_return: number
  ann_return: number
  max_dd: number
  sharpe: number
  trades: number
  fees: number
  funding: number
  halted: boolean
}

export interface SweepArtifact {
  kind: 'sweep'
  meta: RunMeta
  summary: {
    combos: number
    best: SweepRow | null
    worst: SweepRow | null
    positive: number
  }
  rows: SweepRow[]
}

export type Artifact = ReplayArtifact | WalkforwardArtifact | SweepArtifact

export interface RiskLimits {
  max_position_qty: number
  max_order_notional: number
  max_gross_notional: number
  max_open_orders: number
  max_submits_per_minute: number
  max_price_deviation_bp: number
}

export interface RiskProfile {
  symbol: string
  capital: number
  grid: { spacing_bp: number; levels: number; leverage: number }
  stop_dd: number
  kill_switch: boolean
  rejections: Array<{ reason: string; count: number }>
  latest_run: Run | null
  limits: RiskLimits
  exposure?: Record<string, number>
}

export interface ModeInfo {
  enabled: boolean
  locked?: boolean
  label: string
  detail: string
}

export interface Session {
  ok: boolean
  version: string
  actor?: string
  symbol: string
  symbols: string[]
  modes: Record<string, ModeInfo>
  kill_switch: boolean
}

export interface AuthProviders {
  google: {
    enabled: boolean
    configured: boolean
    device_flow: boolean
    web_enabled: boolean
    users: number
  }
}

export interface GoogleDeviceStart {
  flow_id: string
  user_code: string
  verification_url: string
  expires_in: number
  interval: number
}

export interface GooglePollResult {
  status: 'pending' | 'ok' | 'denied' | 'expired' | 'not_allowed' | 'error'
  email?: string
  name?: string
  picture?: string
  error?: string
  interval?: number
}

export interface SettingsView {
  version: string
  auth: { mode: string; token_hint: string; cookie: string }
  paths: { data: string; var: string; web: string; web_built: boolean }
  server: { host: string; port: number; cors_origins: string[]; uptime_s: number }
  symbol: string
  symbols: string[]
  intervals: string[]
  modes: Record<string, ModeInfo>
  kill_switch: boolean
}

export interface AuditEntry {
  id: number
  ts: string
  actor: string
  action: string
  detail: string | null
}

export interface Overview {
  symbol: string
  market: MarketSnapshot
  dataset: DatasetQuality
  runs: Run[]
  walkforward: {
    run: Run
    rows: WalkforwardRow[]
    cumulative: EquityPoint[]
    summary: WalkforwardArtifact['summary']
  } | null
  replay: { run: Run; summary: ReplaySummary | null } | null
  kill_switch: boolean
  modes: Record<string, ModeInfo>
}

export interface ResearchInput {
  symbol?: string
  start?: string | null
  end?: string | null
  capital: number
  spacing_bp: number
  levels: number
  leverage: number
  reanchor_bars: number | null
  stop_dd: number | null
  maker_fee: number
  taker_fee: number
  slip_bp: number
  intrabar: boolean
  auto?: boolean
  auto_interval?: number
  auto_atr_window?: number
  auto_target_vol?: number
}

const TOKEN_KEY = 'gridtrade.token'
const SERVER_KEY = 'gridtrade.server'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export function getServer(): string {
  const stored = localStorage.getItem(SERVER_KEY)
  if (stored) return stored.replace(/\/$/, '')
  return ''
}

export function setServer(value: string): void {
  const trimmed = value.trim().replace(/\/+$/, '')
  if (trimmed) localStorage.setItem(SERVER_KEY, trimmed)
  else localStorage.removeItem(SERVER_KEY)
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function setToken(value: string): void {
  if (value) localStorage.setItem(TOKEN_KEY, value)
  else localStorage.removeItem(TOKEN_KEY)
}

function url(path: string): string {
  return `${getServer()}${path}`
}

type RawPoint = [number, number]

function asPoints(raw: RawPoint[] | undefined): EquityPoint[] {
  return (raw ?? []).map(([t, v]) => ({ t, v }))
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(url(path), { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError(0, '无法连接服务端，请检查地址与网络。')
  }
  if (response.status === 401) {
    throw new ApiError(401, '未登录或会话已过期，请重新登录。')
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join('; ')
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function json(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body) }
}

export const api = {
  health: () => request<{ status: string; version: string; uptime_s: number }>('/api/health'),

  login: (token: string) =>
    request<{ ok: boolean; token_hint: string; expires_in: number }>(
      '/api/auth/login',
      json({ token }),
    ),

  authProviders: () => request<AuthProviders>('/api/auth/providers'),

  googleStart: () =>
    request<GoogleDeviceStart>('/api/auth/google/start', { method: 'POST' }),

  googlePoll: (flowId: string) =>
    request<GooglePollResult>('/api/auth/google/poll', json({ flow_id: flowId })),

  googleExchange: (code: string) =>
    request<{ ok: boolean; email: string }>('/api/auth/google/exchange', json({ code })),

  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),

  session: () => request<Session>('/api/session'),

  overview: async (symbol?: string) => {
    const raw = await request<Overview & { walkforward: { cumulative: unknown } | null }>(
      `/api/overview${symbol ? `?symbol=${symbol}` : ''}`,
    )
    if (raw.walkforward) {
      raw.walkforward.cumulative = asPoints(raw.walkforward.cumulative as unknown as RawPoint[])
    }
    return raw as Overview
  },

  symbols: () =>
    request<{ symbols: string[]; default: string }>('/api/dataset/symbols'),

  quality: (symbol?: string) =>
    request<DatasetQuality>(`/api/dataset/quality${symbol ? `?symbol=${symbol}` : ''}`),

  snapshot: (symbol?: string) =>
    request<MarketSnapshot>(`/api/market/snapshot${symbol ? `?symbol=${symbol}` : ''}`),

  candles: (params: { symbol?: string; interval: string; limit?: number }) => {
    const search = new URLSearchParams({ interval: params.interval })
    if (params.symbol) search.set('symbol', params.symbol)
    if (params.limit) search.set('limit', String(params.limit))
    return request<CandleResponse>(`/api/market/candles?${search}`)
  },

  funding: async (params: { symbol?: string; limit?: number } = {}) => {
    const search = new URLSearchParams()
    if (params.symbol) search.set('symbol', params.symbol)
    if (params.limit) search.set('limit', String(params.limit))
    const qs = search.toString()
    const raw = await request<{
      symbol: string
      summary?: FundingResponse['summary']
      funding: Array<[number, number, number | null]>
    }>(`/api/market/funding${qs ? `?${qs}` : ''}`)
    const points = raw.funding.map(([time, rate, mark]) => ({
      time,
      rate,
      mark_price: mark,
    }))
    // Older node builds omit summary; derive a safe one instead of crashing
    // the whole page on `data.summary.mean_rate`.
    const rates = points.map((point) => point.rate)
    const mean = rates.length ? rates.reduce((sum, rate) => sum + rate, 0) / rates.length : 0
    const ordered = [...rates].sort((a, b) => a - b)
    const median = ordered.length
      ? ordered.length % 2
        ? ordered[Math.floor(ordered.length / 2)]
        : (ordered[ordered.length / 2 - 1] + ordered[ordered.length / 2]) / 2
      : 0
    const summary = raw.summary ?? {
      count: rates.length,
      mean_rate: mean,
      median_rate: median,
      positive_pct: rates.length ? (rates.filter((rate) => rate > 0).length / rates.length) * 100 : 0,
      annualized_pct: mean * 3 * 365 * 100,
      interval_hours: 8,
      last: null,
    }
    return {
      symbol: raw.symbol,
      summary,
      points,
    } satisfies FundingResponse
  },

  submitReplay: (body: ResearchInput) => request<{ run: Run }>('/api/runs/replay', json(body)),
  submitWalkforward: (body: ResearchInput & { min_days: number }) =>
    request<{ run: Run }>('/api/runs/walkforward', json(body)),
  submitSweep: (
    body: ResearchInput & {
      axes: { spacings: number[]; levels: number[]; leverages: number[] }
    },
  ) => request<{ run: Run }>('/api/runs/sweep', json(body)),

  runs: (kind?: RunKind, limit = 30) => {
    const search = new URLSearchParams()
    if (kind) search.set('kind', kind)
    search.set('limit', String(limit))
    return request<{ runs: Run[] }>(`/api/runs?${search}`)
  },

  run: (id: string) => request<{ run: Run }>(`/api/runs/${id}`),

  artifact: async (id: string) => {
    const raw = await request<Record<string, unknown>>(`/api/runs/${id}/artifact`)
    const record = raw as {
      equity?: { points?: unknown }
      drawdown?: { points?: unknown }
      cumulative?: unknown
    }
    if (record.equity?.points) record.equity.points = asPoints(record.equity.points as RawPoint[])
    if (record.drawdown?.points) record.drawdown.points = asPoints(record.drawdown.points as RawPoint[])
    if (Array.isArray(record.cumulative)) record.cumulative = asPoints(record.cumulative as RawPoint[])
    return raw as unknown as Artifact
  },

  cancelRun: (id: string) => request<{ canceled: boolean; run: Run }>(`/api/runs/${id}/cancel`, { method: 'POST' }),

  risk: (params: { symbol?: string; capital?: number; spacing_bp?: number; levels?: number; leverage?: number } = {}) => {
    const search = new URLSearchParams()
    if (params.symbol) search.set('symbol', params.symbol)
    if (params.capital) search.set('capital', String(params.capital))
    if (params.spacing_bp) search.set('spacing_bp', String(params.spacing_bp))
    if (params.levels) search.set('levels', String(params.levels))
    if (params.leverage) search.set('leverage', String(params.leverage))
    const qs = search.toString()
    return request<RiskProfile>(`/api/risk${qs ? `?${qs}` : ''}`)
  },

  setKillSwitch: (engaged: boolean) =>
    request<{ kill_switch: boolean }>('/api/settings/kill-switch', json({ engaged })),

  settings: () => request<SettingsView>('/api/settings'),

  audit: (limit = 60) => request<{ entries: AuditEntry[] }>(`/api/audit?limit=${limit}`),

  paper: () => request<PaperState>('/api/paper'),

  paperStart: (body: { reset?: boolean; config?: PaperConfigInput }) =>
    request<PaperState>('/api/paper/start', json(body)),

  paperStop: () => request<PaperState>('/api/paper/stop', { method: 'POST' }),

  paperReset: (config?: PaperConfigInput) =>
    request<PaperState>('/api/paper/reset', json(config ?? {})),

  paperRuns: (limit = 30) => request<{ runs: PaperRun[] }>(`/api/paper/runs?limit=${limit}`),

  live: (refresh = false) => request<LiveSnapshot>(`/api/live${refresh ? '?refresh=1' : ''}`),

  liveConfig: () => request<{ config: LiveConfigView }>('/api/live/config'),

  saveLiveConfig: (body: LiveConfigInput) =>
    request<{ config: LiveConfigView }>('/api/live/config', json(body)),

  testLive: () => request<{ ok: boolean; total: number; currency: string | null }>('/api/live/test', { method: 'POST' }),

  liveSync: () => request<LiveSnapshot>('/api/live/sync', { method: 'POST' }),

  liveOrder: (body: LiveOrderInput) =>
    request<{ order: Record<string, unknown> }>('/api/live/orders', json(body)),

  cancelLiveOrder: (id: string) =>
    request<{ order: Record<string, unknown> }>(`/api/live/orders/${id}`, { method: 'DELETE' }),

  closeLivePosition: (contract: string) =>
    request<{ order: Record<string, unknown> }>(`/api/live/positions/${encodeURIComponent(contract)}/close`, {
      method: 'POST',
    }),

  binanceHealth: () =>
    request<{ ok: boolean; node_url: string; health: BinanceNodeHealth }>('/api/binance/health'),

  binanceGateway: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/binance/gateway', json(body)),

  binanceState: (symbol?: string) =>
    request<BinanceState>(`/api/binance/state${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),
}

export function streamUrl(symbol?: string): string {
  const base = getServer()
  const proto = base.startsWith('https://') ? 'wss://' : base.startsWith('http://') ? 'ws://' : location.protocol === 'https:' ? 'wss://' : 'ws://'
  const host = base ? new URL(base).host : location.host
  const search = new URLSearchParams({ token: getToken() })
  if (symbol) search.set('symbol', symbol)
  return `${proto}${host}/ws?${search}`
}
