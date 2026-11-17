import { useEffect, useState } from 'react'
import { Activity, Play, RotateCcw, Square, Wallet } from 'lucide-react'
import { api, type PaperConfigInput, type PaperState } from '../api'
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
  spacing_bp: 60,
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

  const data = state.data

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
  const reset = () =>
    run('reset', () => api.paperReset(configPayload()), '模拟盘账户已重置')

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
  const grid = data.grid
  const running = data.status === 'running'
  const points = equityPoints(data)

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[13px] font-semibold text-ink">实时模拟盘</h2>
              <Badge tone={STATUS[data.status].tone}>{STATUS[data.status].label}</Badge>
              <Badge tone="info">{data.symbol} · Gate 永续</Badge>
              {data.config.enabled ? null : <Badge tone="warn">未在 .env 启用</Badge>}
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed text-muted">
              网格纸面成交：maker {data.config.maker_fee_bp}bp / taker {data.config.taker_fee_bp}bp，
              资金费按合约结算周期扣缴，行情每 {data.config.poll_seconds}s 轮询。
            </p>
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
            <Button
              size="sm"
              variant="outline"
              loading={busy === 'stop'}
              disabled={!running}
              onClick={stop}
            >
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
            label="标记价格"
            value={fmtPrice(data.mark_price)}
            sub={`指数 ${fmtPrice(data.index_price)}`}
            tone={data.change_24h_pct ?? undefined}
          />
          <Stat
            label="资金费率"
            value={fmtPct(data.funding_rate * 100, 4)}
            sub={data.next_funding_time ? `下次结算 ${fmtTime(data.next_funding_time)}` : '—'}
          />
          <Stat
            label="账户权益"
            value={`$${fmtMoney(account.equity, 2)}`}
            sub={`现金 $${fmtMoney(account.cash, 2)}`}
            tone={account.return_pct}
          />
          <Stat
            label="持仓"
            value={fmtQty(account.position)}
            sub={account.position ? `均价 ${fmtPrice(account.avg_entry)}` : '空仓'}
            tone={account.position}
          />
        </div>
        {data.last_error ? <div className="mt-3"><ErrorNote>{data.last_error}</ErrorNote></div> : null}
        {error ? <div className="mt-3"><ErrorNote>{error}</ErrorNote></div> : null}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHead
            title="收益与成本"
            hint={`数据源 ${data.last_tick_at ? `更新于 ${timeAgo(data.last_tick_at)}` : '等待行情'}`}
            right={<Badge tone="neutral">{data.status === 'running' ? '实时' : '暂停'}</Badge>}
          />
          <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-3">
            <Stat label="未实现" value={`$${fmtMoney(account.unrealized, 2)}`} tone={account.unrealized} />
            <Stat label="已实现" value={`$${fmtMoney(account.realized, 2)}`} tone={account.realized} />
            <Stat label="累计收益" value={fmtPct(account.return_pct)} tone={account.return_pct} />
            <Stat label="手续费" value={`$${fmtMoney(account.fees, 3)}`} />
            <Stat label="资金费" value={`$${fmtMoney(account.funding, 3)}`} />
            <Stat label="最大回撤" value={`${fmtMoney(account.drawdown_pct, 2)}%`} tone={-account.drawdown_pct} />
          </div>
        </Card>

        <Card>
          <CardHead
            title="网格"
            hint="相邻格各挂一单；价格触达挂单价即按该价成交，收入计入手续费与已实现盈亏。"
            right={<Badge tone="accent">{grid.level} 层</Badge>}
          />
          <div className="grid grid-cols-2 gap-x-5 gap-y-4">
            <Stat label="锚点" value={fmtPrice(grid.anchor)} />
            <Stat label="单格步长" value={fmtPrice(grid.step)} />
            <Stat label="每格数量" value={fmtQty(grid.unit)} />
            <Stat label="最大持仓" value={fmtQty(grid.max_position)} />
            <Stat label="买入价" value={fmtPrice(grid.buy_price)} />
            <Stat label="卖出价" value={fmtPrice(grid.sell_price)} />
          </div>
        </Card>
      </div>

      <Card pad={false}>
        <div className="px-5 pt-5">
          <CardHead
            title="权益曲线"
            hint="每 15 秒采样一次；重启后从 SQLite 恢复。"
            right={<Badge tone="neutral">{points.length} 点</Badge>}
          />
        </div>
        {points.length >= 2 ? (
          <div className="px-2 pb-2">
            <EquityChart equity={points} height={260} />
          </div>
        ) : (
          <div className="px-5 pb-5">
            <Empty
              title="还没有权益样本"
              body="启动模拟盘后，行情轮询与成交会持续记录权益和持仓。"
            />
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="参数"
          hint="修改后点“重置账户”生效（会清空成交与权益历史，并从当前标记价重新锚定）。"
          right={<Badge tone="neutral">仅影响纸面账户</Badge>}
        />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field label="本金" hint="USDT">
            <NumberInput value={form.capital} onChange={patch('capital')} min={100} suffix="$" />
          </Field>
          <Field label="杠杆" hint="总名义 / 本金">
            <NumberInput value={form.leverage} onChange={patch('leverage')} min={0.1} step={0.1} suffix="x" />
          </Field>
          <Field label="网格间距" hint="bp">
            <NumberInput value={form.spacing_bp} onChange={patch('spacing_bp')} min={1} suffix="bp" />
          </Field>
          <Field label="层数" hint="单边最大格数">
            <NumberInput value={form.levels} onChange={patch('levels')} min={1} suffix="L" />
          </Field>
          <Field label="止损回撤" hint="% · 0 关闭">
            <NumberInput value={form.stop_dd_pct} onChange={patch('stop_dd_pct')} min={0} suffix="%" />
          </Field>
          <Field label="挂单费率" hint="maker bp">
            <NumberInput value={form.maker_fee_bp} onChange={patch('maker_fee_bp')} min={0} suffix="bp" />
          </Field>
          <Field label="吃单费率" hint="taker bp">
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
            <CardHead title="成交" hint="纸面成交，含手续费与已实现盈亏。" right={<Badge tone="neutral">{data.fills.length}</Badge>} />
          </div>
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full text-[11.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">时间</th>
                  <th className="py-2 font-medium">方向</th>
                  <th className="py-2 text-right font-medium">价格</th>
                  <th className="py-2 text-right font-medium">数量</th>
                  <th className="py-2 text-right font-medium">手续费</th>
                  <th className="py-2 pr-5 text-right font-medium">已实现</th>
                </tr>
              </thead>
              <tbody>
                {data.fills.length === 0 ? (
                  <tr><td colSpan={6} className="px-5 py-8 text-center text-[12px] text-muted">暂无成交</td></tr>
                ) : (
                  data.fills.map((fill) => (
                    <tr key={fill.id} className="border-t border-line-soft">
                      <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(fill.ts)}</td>
                      <td className={cx('py-2 font-mono', fill.side === 'BUY' ? 'text-up' : 'text-down')}>{fill.side}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(fill.price)}</td>
                      <td className="py-2 text-right font-mono tabular-nums">{fmtQty(fill.qty)}</td>
                      <td className="py-2 text-right font-mono tabular-nums text-muted">{fmtMoney(fill.fee, 3)}</td>
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
            <CardHead title="资金费" hint="按合约资金费结算；正数表示支出。" right={<Badge tone="neutral">{data.funding.length}</Badge>} />
          </div>
          <div className="max-h-[360px] overflow-auto">
            <table className="w-full text-[11.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">结算时间</th>
                  <th className="py-2 text-right font-medium">费率</th>
                  <th className="py-2 text-right font-medium">持仓</th>
                  <th className="py-2 pr-5 text-right font-medium">支付</th>
                </tr>
              </thead>
              <tbody>
                {data.funding.length === 0 ? (
                  <tr><td colSpan={4} className="px-5 py-8 text-center text-[12px] text-muted">暂无结算</td></tr>
                ) : (
                  data.funding.map((row) => (
                    <tr key={row.id} className="border-t border-line-soft">
                      <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(row.ts)}</td>
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
        模拟盘不连接任何交易所私有接口，不会下单；仅使用公开行情与资金费数据。收益、持仓、手续费与资金费均落库到
        <span className="font-mono"> var/paper.db</span>，服务重启后自动恢复。
      </p>
    </div>
  )
}
