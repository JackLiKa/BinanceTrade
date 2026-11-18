import { useEffect, useState } from 'react'
import { Play, RotateCcw, Square } from 'lucide-react'
import { api, type PaperConfigInput, type PaperRun, type PaperState } from '../api'
import { EquityChart } from '../components/charts'
import { NumberInput } from '../components/inputs'
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Field, Skeleton, Stat } from '../components/ui'
import { cx, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, timeAgo } from '../format'
import { errorText, useFetch } from '../hooks'
import { useApp } from '../store'

const STATUS: Record<PaperState['status'], { label: string; tone: 'up' | 'down' | 'neutral' }> = {
  running: { label: '运行中', tone: 'up' },
  halted: { label: '已止损', tone: 'down' },
  stopped: { label: '已停止', tone: 'neutral' },
}

interface Form {
  capital: number
  leverage: number
  spacing_bp: number
  levels: number
  stop_dd_pct: number
  maker_fee_bp: number
  taker_fee_bp: number
  poll_seconds: number
}

const DEFAULTS: Form = {
  capital: 10_000,
  leverage: 2,
  spacing_bp: 10,
  levels: 20,
  stop_dd_pct: 10,
  maker_fee_bp: 2,
  taker_fee_bp: 5,
  poll_seconds: 3,
}

function equityPoints(data: PaperState) {
  return data.equity.map(([ts, value]) => ({ t: Math.floor(Date.parse(ts) / 1000), v: value }))
}

export function Paper() {
  const { toast } = useApp()
  const state = useFetch(() => api.paper(), [], { pollMs: 3_000 })
  const [form, setForm] = useState<Form>(DEFAULTS)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [runs, setRuns] = useState<PaperRun[]>([])

  const data = state.data

  const loadRuns = () => {
    api
      .paperRuns(30)
      .then((payload) => setRuns(payload.runs))
      .catch(() => setRuns([]))
  }

  useEffect(() => {
    loadRuns()
  }, [])

  useEffect(() => {
    if (!data || ready) return
    setForm({
      capital: data.config.capital,
      leverage: data.config.leverage,
      spacing_bp: data.config.spacing_bp,
      levels: data.config.levels,
      stop_dd_pct: data.config.stop_dd_pct,
      maker_fee_bp: data.config.maker_fee_bp,
      taker_fee_bp: data.config.taker_fee_bp,
      poll_seconds: data.config.poll_seconds,
    })
    setReady(true)
  }, [data, ready])

  const patch = (key: keyof Form) => (value: number | null) => {
    if (value === null) return
    setForm((current) => ({ ...current, [key]: value }))
  }

  const configPayload = (): PaperConfigInput => ({ ...form })

  const run = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusy(key)
    setError(null)
    try {
      await action()
      state.reload()
      toast(message, 'ok')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(null)
    }
  }

  const start = () =>
    run(
      'start',
      () => api.paperStart({ reset: data?.status === 'halted', config: configPayload() }),
      '模拟盘已启动',
    )
  const stop = () => run('stop', () => api.paperStop(), '模拟盘已停止')
  const reset = () => run('reset', () => api.paperReset(configPayload()), '模拟盘账户已重置')

  if (state.error && !data) {
    return (
      <div className="space-y-4">
        <ErrorNote>{state.error}</ErrorNote>
        <Button onClick={state.reload}>重试</Button>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  const account = data.account
  const running = data.status === 'running'
  const points = equityPoints(data)

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[13px] font-semibold text-ink">实时组合模拟盘</h2>
              <Badge tone={STATUS[data.status].tone}>{STATUS[data.status].label}</Badge>
              <Badge tone="info">{data.symbols.length} 标的 · {data.source === 'binance' ? 'Binance 永续' : '永续'}</Badge>
              {data.config.enabled ? null : <Badge tone="warn">未在 .env 启用</Badge>}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
              共享保证金组合：每个标的独立网格，合并计算权益、手续费与资金费。
              费率优先取自交易所合约公开字段，缺失时才回退到配置值；每 {data.config.poll_seconds}s 轮询。
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.symbols.map((symbol) => (
                <span
                  key={symbol}
                  className="rounded border border-line bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted"
                >
                  {symbol}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={busy === 'start'}
              disabled={running || !data.config.enabled}
              onClick={start}
            >
              <Play size={13} /> 启动
            </Button>
            <Button size="sm" variant="outline" loading={busy === 'stop'} disabled={!running} onClick={stop}>
              <Square size={13} /> 停止
            </Button>
            <Button
              size="sm"
              variant={confirmReset ? 'danger' : 'outline'}
              loading={busy === 'reset'}
              onClick={() => {
                if (!confirmReset) {
                  setConfirmReset(true)
                  window.setTimeout(() => setConfirmReset(false), 4_000)
                  return
                }
                setConfirmReset(false)
                void reset()
              }}
            >
              <RotateCcw size={13} /> {confirmReset ? '确认重置' : '重置账户'}
            </Button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 border-t border-line-soft pt-4 sm:grid-cols-4">
          <Stat
            label="账户权益"
            value={`$${fmtMoney(account.equity, 2)}`}
            sub={`现金 $${fmtMoney(account.cash, 2)}`}
            tone={account.return_pct}
          />
          <Stat
            label="组合收益"
            value={fmtPct(account.return_pct)}
            sub={`峰值 $${fmtMoney(account.peak_equity, 0)} · 回撤 ${fmtMoney(account.drawdown_pct, 2)}%`}
            tone={account.return_pct}
          />
          <Stat
            label="总名义 / 保证金"
            value={`$${fmtMoney(account.gross_notional, 0)}`}
            sub={`维持保证金 $${fmtMoney(account.maintenance_margin ?? 0, 2)} · ${fmtMoney((account.margin_ratio ?? 0) * 100, 2)}%`}
          />
          <Stat
            label="成本"
            value={`$${fmtMoney(account.fees + account.funding + (account.slippage ?? 0), 3)}`}
            sub={`手续费 ${fmtMoney(account.fees, 3)} · 资金费收益 ${fmtMoney(account.funding_income ?? -account.funding, 3)} · 滑点 ${fmtMoney(account.slippage ?? 0, 3)}`}
          />
        </div>
        {data.liquidation ? (
          <ErrorNote>
            已触发 Binance 式爆仓强平：权益 ${fmtMoney(data.liquidation.equity_before, 2)} ≤ 维持保证金 $
            {fmtMoney(data.liquidation.maintenance_margin, 2)}；强平费 ${fmtMoney(data.liquidation.liquidation_fee, 3)}，
            坏账 ${fmtMoney(data.liquidation.bad_debt, 2)}，保险覆盖 $
            {fmtMoney(data.liquidation.insurance_covered ?? 0, 2)}，未覆盖 $
            {fmtMoney(data.liquidation.uncovered_bad_debt ?? data.liquidation.bad_debt, 2)}
            {data.account.equity < 0 ? `；账户权益为负` : ''}。
          </ErrorNote>
        ) : null}
        {data.cost ? (
          <div className="mt-3 rounded-lg border border-line-soft bg-elevated/40 px-3 py-2 text-[11px] text-muted">
            成本模型：maker 往返 <span className="font-mono text-ink">{fmtMoney(data.cost.round_trip_maker_bp ?? 0, 2)} bp</span>
            {' · '}taker 往返 <span className="font-mono text-ink">{fmtMoney(data.cost.round_trip_taker_bp ?? 0, 2)} bp</span>
            {' · '}保本间距 <span className="font-mono text-ink">{fmtMoney(data.cost.breakeven_spacing_bp ?? 0, 2)} bp</span>
            {' · '}当前间距 <span className="font-mono text-ink">{fmtMoney(data.config.spacing_bp, 2)} bp</span>
            {data.cost.net_edge_bp != null ? (
              <>
                {' · '}净边际{' '}
                <span className={cx('font-mono', data.cost.net_edge_bp >= 0 ? 'text-up' : 'text-down')}>
                  {fmtMoney(data.cost.net_edge_bp, 2)} bp
                </span>
              </>
            ) : null}
            {' · '}滑点假设 {fmtMoney(data.cost.slippage_bp ?? 0, 2)} bp/边
          </div>
        ) : null}
        {data.last_error ? <div className="mt-3"><ErrorNote>{data.last_error}</ErrorNote></div> : null}
        {error ? <div className="mt-3"><ErrorNote>{error}</ErrorNote></div> : null}
      </Card>

      <Card>
        <CardHead
          title="历史运行"
          hint="每次 reset 或触发止损都会归档摘要，便于复盘对比参数。"
          right={<Button variant="ghost" onClick={loadRuns}>刷新</Button>}
        />
        {runs.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-muted">暂无归档运行</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[11.5px]">
              <thead className="text-[10px] uppercase tracking-wider text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">结束时间</th>
                  <th className="py-2 pr-3">原因</th>
                  <th className="py-2 pr-3">参数</th>
                  <th className="py-2 pr-3 text-right">收益</th>
                  <th className="py-2 pr-3 text-right">回撤</th>
                  <th className="py-2 pr-3 text-right">手续费</th>
                  <th className="py-2 pr-3 text-right">资金费</th>
                  <th className="py-2 pr-3 text-right">滑点</th>
                  <th className="py-2 pr-3 text-right">成交</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3 font-mono text-[10.5px] text-muted">{fmtTime(run.ended_at)}</td>
                    <td className="py-2 pr-3">{run.reason === 'stop' ? '止损' : run.reason === 'reset' ? '重置' : run.reason}</td>
                    <td className="py-2 pr-3 font-mono text-[10.5px] text-muted">
                      {Number(run.config?.leverage ?? 0)}x · {Number(run.config?.spacing_bp ?? 0)}bp · {Number(run.config?.levels ?? 0)}层 · 止损{Number(run.config?.stop_dd_pct ?? 0)}%
                    </td>
                    <td className={cx('py-2 pr-3 text-right font-mono', run.return_pct >= 0 ? 'text-up' : 'text-down')}>
                      {fmtPct(run.return_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-muted">{fmtPct(run.max_dd_pct)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-muted">{fmtMoney(run.fees, 3)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-muted">{fmtMoney(run.funding, 3)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-muted">{fmtMoney(run.slippage, 3)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-muted">{run.fills}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card pad={false}>
        <div className="px-5 pt-5">
          <CardHead
            title="组合持仓与网格"
            hint={`数据源 ${data.last_tick_at ? `更新于 ${timeAgo(data.last_tick_at)}` : '等待行情'}；每个标的按共享保证金上限约束开仓。`}
            right={
              <Badge tone="neutral">
                未实现 ${fmtMoney(account.unrealized, 2)} · 已实现 ${fmtMoney(account.realized, 2)}
              </Badge>
            }
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[11.5px]">
            <thead>
              <tr className="border-t border-line-soft text-left text-[10px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2 font-medium">标的</th>
                <th className="py-2 text-right font-medium">标记价</th>
                <th className="py-2 text-right font-medium">24h</th>
                <th className="py-2 text-right font-medium">资金费率</th>
                <th className="py-2 text-right font-medium">持仓</th>
                <th className="py-2 text-right font-medium">均价</th>
                <th className="py-2 text-right font-medium">未实现</th>
                <th className="py-2 text-right font-medium">强平价</th>
                <th className="py-2 text-right font-medium">买 / 卖</th>
                <th className="py-2 text-right font-medium">费率(m/t)</th>
                <th className="py-2 pr-5 text-right font-medium">名义</th>
              </tr>
            </thead>
            <tbody>
              {data.portfolio.length === 0 ? (
                <tr><td colSpan={11} className="px-5 py-8 text-center text-[12px] text-muted">暂无标的</td></tr>
              ) : (
                data.portfolio.map((row) => (
                  <tr key={row.symbol} className="border-t border-line-soft">
                    <td className="px-5 py-2 font-mono text-[11px] text-ink">{row.symbol}</td>
                    <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(row.mark_price)}</td>
                    <td className={cx('py-2 text-right font-mono tabular-nums', (row.change_24h_pct ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                      {fmtPct(row.change_24h_pct)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-muted">{fmtPct(row.funding_rate * 100, 4, false)}</td>
                    <td className={cx('py-2 text-right font-mono tabular-nums', row.position > 0 ? 'text-up' : row.position < 0 ? 'text-down' : 'text-muted')}>
                      {fmtQty(row.position)}
                      {row.position !== 0 ? (
                        <span className={cx('ml-1 text-[10px]', row.position > 0 ? 'text-up' : 'text-down')}>
                          {row.position > 0 ? '多' : '空'}
                        </span>
                      ) : null}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-muted">{row.position ? fmtPrice(row.avg_entry) : '—'}</td>
                    <td className={cx('py-2 text-right font-mono tabular-nums', row.unrealized >= 0 ? 'text-up' : 'text-down')}>
                      {fmtMoney(row.unrealized, 3)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-muted">
                      {row.liquidation_price != null ? fmtPrice(row.liquidation_price) : '—'}
                    </td>
                    <td className="py-2 text-right font-mono text-[10.5px] text-muted">
                      {fmtPrice(row.buy_price)} / {fmtPrice(row.sell_price)}
                    </td>
                    <td className="py-2 text-right font-mono text-[10.5px] text-muted">
                      {Number(row.maker_fee_bp.toFixed(4))}/{Number(row.taker_fee_bp.toFixed(4))}bp
                      <span className="ml-1 text-[9px] uppercase text-faint">{row.fee_source === 'exchange' ? '合约' : '配置'}</span>
                    </td>
                    <td className="py-2 pr-5 text-right font-mono tabular-nums">{fmtMoney(row.notional, 0)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card pad={false}>
        <div className="px-5 pt-5">
          <CardHead title="组合权益曲线" hint="每 15 秒采样；重启后从 SQLite 恢复。" right={<Badge tone="neutral">{points.length} 点</Badge>} />
        </div>
        {points.length >= 2 ? (
          <div className="px-2 pb-2">
            <EquityChart equity={points} height={260} />
          </div>
        ) : (
          <div className="px-5 pb-5">
            <Empty title="还没有权益样本" body="启动模拟盘后，行情轮询与成交会持续记录组合权益。" />
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="参数"
          hint="修改后点“重置账户”生效（清空成交与权益历史，按当前标记价重新锚定全部标的）。标的列表由服务器 .env 的 GRIDTRADE_PAPER_SYMBOLS 控制。"
          right={<Badge tone="neutral">共享保证金</Badge>}
        />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field label="组合本金" hint="USDT">
            <NumberInput value={form.capital} onChange={patch('capital')} min={100} suffix="$" />
          </Field>
          <Field label="组合杠杆" hint="总名义 / 权益">
            <NumberInput value={form.leverage} onChange={patch('leverage')} min={0.1} step={0.1} suffix="x" />
          </Field>
          <Field label="网格间距" hint="bp">
            <NumberInput value={form.spacing_bp} onChange={patch('spacing_bp')} min={1} suffix="bp" />
          </Field>
          <Field label="层数" hint="单标的单边最大格数">
            <NumberInput value={form.levels} onChange={patch('levels')} min={1} suffix="L" />
          </Field>
          <Field label="止损回撤" hint="% · 0 关闭">
            <NumberInput value={form.stop_dd_pct} onChange={patch('stop_dd_pct')} min={0} suffix="%" />
          </Field>
          <Field label="挂单费率" hint="maker bp · 回退值">
            <NumberInput value={form.maker_fee_bp} onChange={patch('maker_fee_bp')} min={0} suffix="bp" />
          </Field>
          <Field label="吃单费率" hint="taker bp · 回退值">
            <NumberInput value={form.taker_fee_bp} onChange={patch('taker_fee_bp')} min={0} suffix="bp" />
          </Field>
          <Field label="轮询间隔" hint="秒">
            <NumberInput value={form.poll_seconds} onChange={patch('poll_seconds')} min={1} suffix="s" />
          </Field>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card pad={false}>
          <div className="px-5 pt-5">
            <CardHead title="成交" hint="按标的记录纸面成交，含手续费与已实现盈亏。" right={<Badge tone="neutral">{data.fills.length}</Badge>} />
          </div>
          <div className="max-h-[380px] overflow-auto">
            <table className="w-full min-w-[520px] text-[11.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">时间</th>
                  <th className="py-2 font-medium">标的</th>
                  <th className="py-2 font-medium">动作</th>
                  <th className="py-2 font-medium">方向</th>
                  <th className="py-2 text-right font-medium">价格</th>
                  <th className="py-2 text-right font-medium">数量</th>
                  <th className="py-2 text-right font-medium">手续费</th>
                  <th className="py-2 text-right font-medium">滑点</th>
                  <th className="py-2 pr-5 text-right font-medium">已实现</th>
                </tr>
              </thead>
              <tbody>
                {data.fills.length === 0 ? (
                  <tr><td colSpan={9} className="px-5 py-8 text-center text-[12px] text-muted">暂无成交</td></tr>
                ) : (
                  data.fills.map((fill) => (
                    <tr key={fill.id} className="border-t border-line-soft">
                      <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(fill.ts)}</td>
                      <td className="py-2 font-mono text-[10.5px] text-muted">{fill.symbol}</td>
                      <td className="py-2">
                        <Badge tone={fill.action?.startsWith('OPEN') ? 'info' : 'warn'}>
                          {fill.action === 'OPEN_LONG' ? '开多'
                            : fill.action === 'OPEN_SHORT' ? '开空'
                            : fill.action === 'CLOSE_LONG' ? '平多'
                            : fill.action === 'CLOSE_SHORT' ? '平空'
                            : '—'}
                        </Badge>
                      </td>
                      <td className={cx('py-2 font-mono', fill.side === 'BUY' ? 'text-up' : 'text-down')}>{fill.side}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(fill.price)}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtQty(fill.qty)}</td>
                      <td className="py-2 text-right font-mono tabular-nums text-muted">{fmtMoney(fill.fee, 3)}</td>
                      <td className="py-2 text-right font-mono tabular-nums text-muted">{fmtMoney(fill.slip ?? 0, 4)}</td>
                      <td className={cx('py-2 pr-5 text-right font-mono tabular-nums', fill.realized >= 0 ? 'text-up' : 'text-down')}>
                        {fmtMoney(fill.realized, 3)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <Card pad={false}>
          <div className="px-5 pt-5">
            <CardHead title="资金费" hint="按标的结算；正数表示支出。" right={<Badge tone="neutral">{data.funding.length}</Badge>} />
          </div>
          <div className="max-h-[380px] overflow-auto">
            <table className="w-full min-w-[460px] text-[11.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">结算时间</th>
                  <th className="py-2 font-medium">标的</th>
                  <th className="py-2 text-right font-medium">费率</th>
                  <th className="py-2 text-right font-medium">持仓</th>
                  <th className="py-2 pr-5 text-right font-medium">支付</th>
                </tr>
              </thead>
              <tbody>
                {data.funding.length === 0 ? (
                  <tr><td colSpan={5} className="px-5 py-8 text-center text-[12px] text-muted">暂无结算</td></tr>
                ) : (
                  data.funding.map((row) => (
                    <tr key={row.id} className="border-t border-line-soft">
                      <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(row.ts)}</td>
                      <td className="py-2 font-mono text-[10.5px] text-muted">{row.symbol}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtPct(row.rate * 100, 4, false)}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtQty(row.position)}</td>
                      <td className={cx('py-2 pr-5 text-right font-mono tabular-nums', row.payment > 0 ? 'text-down' : 'text-up')}>
                        {fmtMoney(row.payment, 3)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <p className="px-1 text-[10.5px] leading-relaxed text-faint">
        组合模拟盘不连接任何交易所私有接口，不会下单；仅使用公开行情与资金费数据。共享一个保证金池，
        成交、手续费、资金费与组合权益落库到 <span className="font-mono">var/paper.db</span>，服务重启后自动恢复。
      </p>
    </div>
  )
}
