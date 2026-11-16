import { useEffect, useMemo, useState } from 'react'
import { ListOrdered, RefreshCw, Search } from 'lucide-react'
import { api, type ReplayArtifact, type Run } from '../api'
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Skeleton, Stat } from '../components/ui'
import { cx, fmtDateTimeLocal, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, timeAgo } from '../format'
import { statusTone, useArtifact, useFetch } from '../hooks'
import { navigate } from '../router'
import { useApp } from '../store'

type Side = 'ALL' | 'BUY' | 'SELL'
type Liquidity = 'ALL' | 'MAKER' | 'TAKER'

const SIDES: Side[] = ['ALL', 'BUY', 'SELL']
const LIQUIDITY: Liquidity[] = ['ALL', 'MAKER', 'TAKER']

const LABELS: Record<string, string> = {
  ALL: '全部',
  BUY: '买入',
  SELL: '卖出',
  MAKER: 'Maker',
  TAKER: 'Taker',
  QUEUED: '排队中',
  RUNNING: '运行中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELED: '已取消',
}

const ORDER_LABELS: Record<string, string> = {
  NEW: '挂单中',
  OPEN: '挂单中',
  PARTIALLY_FILLED: '部分成交',
  FILLED: '已成交',
  CANCELED: '已撤销',
  CANCELLED: '已撤销',
  REJECTED: '已拒绝',
  EXPIRED: '已过期',
  UNKNOWN: '未知',
}

const REASON_LABELS: Record<string, string> = {
  missing_tag: '缺少标签',
  duplicate_tag: '标签重复',
  bad_price: '价格无效',
  min_notional: '低于最小名义价值',
  qty_nonpositive: '数量无效',
  price_deviation: '价格偏离超限',
  reduce_only_flat: '无持仓可减',
  reduce_only_flip: '减仓将反向',
  max_position: '超出最大持仓',
  max_order_notional: '超出单笔上限',
  max_gross_notional: '超出总敞口上限',
  max_open_orders: '挂单数超限',
  order_rate: '提交频率超限',
  exchange_reject: '交易所拒单',
  post_only_would_take: 'Post-Only 会立即成交',
  reduce_only_invalid: '只减仓标记无效',
  reconcile: '对账',
}

const labelOf = (value: string) => LABELS[value.toUpperCase()] ?? value
const orderLabel = (value: string) => ORDER_LABELS[value.toUpperCase()] ?? value
const reasonLabel = (reason: string) => REASON_LABELS[reason] ?? reason

function FilterRow<T extends string>({
  label,
  options,
  value,
  onChange,
  format,
}: {
  label: string
  options: T[]
  value: T
  onChange: (next: T) => void
  format?: (option: T) => string
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="label">{label}</span>
      <div className="flex overflow-hidden rounded-md border border-line">
        {options.map((option) => (
          <button
            key={option}
            onClick={() => onChange(option)}
            className={cx(
              'px-2 py-1 font-mono text-[10px] uppercase tracking-wide transition-colors',
              option === value ? 'bg-elevated text-accent' : 'text-faint hover:text-ink',
            )}
          >
            {format ? format(option) : option}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Orders() {
  const history = useFetch(() => api.runs('replay', 20), [], { pollMs: 15_000 })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [side, setSide] = useState<Side>('ALL')
  const [liquidity, setLiquidity] = useState<Liquidity>('ALL')
  const [query, setQuery] = useState('')
  const [visible, setVisible] = useState(120)

  useEffect(() => {
    if (selectedId || !history.data) return
    const first = history.data.runs.find((run) => run.status === 'succeeded')
    if (first) setSelectedId(first.id)
  }, [history.data, selectedId])

  const selected: Run | null =
    history.data?.runs.find((run) => run.id === selectedId) ?? null
  const artifact = useArtifact(selectedId, selected)
  const replay = artifact.data?.kind === 'replay' ? (artifact.data as ReplayArtifact) : null

  const fills = useMemo(() => {
    if (!replay) return []
    const needle = query.trim().toLowerCase()
    return [...replay.fills]
      .reverse()
      .filter((fill) => side === 'ALL' || fill.side === side)
      .filter((fill) => liquidity === 'ALL' || fill.liquidity === liquidity)
      .filter(
        (fill) =>
          !needle ||
          fill.tag.toLowerCase().includes(needle) ||
          fill.client_id.toLowerCase().includes(needle),
      )
  }, [replay, side, liquidity, query])

  const totals = useMemo(() => {
    if (!replay) return { notional: 0, fees: 0, maker: 0 }
    return replay.fills.reduce(
      (acc, fill) => ({
        notional: acc.notional + fill.qty * fill.price,
        fees: acc.fees + fill.fee,
        maker: acc.maker + (fill.liquidity === 'MAKER' ? 1 : 0),
      }),
      { notional: 0, fees: 0, maker: 0 },
    )
  }, [replay])

  const statuses = replay ? Object.entries(replay.orders.counts) : []
  const openOrders = replay?.orders.open ?? []

  return (
    <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
      <div className="space-y-4">
        <Card pad={false}>
          <div className="flex items-center justify-between px-4 pt-4">
            <div>
              <h2 className="text-[13px] font-semibold text-ink">回放任务</h2>
              <p className="mt-0.5 text-[10.5px] text-muted">成交按回放任务分别记录。</p>
            </div>
            <button
              onClick={history.reload}
              className="text-faint transition-colors hover:text-ink"
              aria-label="刷新回放任务"
            >
              <RefreshCw size={12} />
            </button>
          </div>
          <div className="mt-3 max-h-[520px] overflow-y-auto border-t border-line-soft">
            {history.loading && !history.data ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-11 w-full" />
                ))}
              </div>
            ) : history.data?.runs.length ? (
              history.data.runs.map((run) => {
                const active = run.id === selectedId
                return (
                  <button
                    key={run.id}
                    onClick={() => {
                      setSelectedId(run.id)
                      setVisible(120)
                    }}
                    className={cx(
                      'flex w-full flex-col gap-1 border-b border-line-soft/60 px-4 py-2.5 text-left transition-colors last:border-0',
                      active ? 'bg-accent/6' : 'hover:bg-elevated/50',
                    )}
                  >
                    <div className="flex w-full items-center justify-between gap-2">
                      <span className="min-w-0 truncate font-mono text-[10px] text-muted">{run.id}</span>
                      <Badge tone={statusTone(run.status)}>{labelOf(run.status)}</Badge>
                    </div>
                    <div className="flex w-full items-center justify-between gap-3 font-mono text-[10.5px]">
                      <span className="min-w-0 truncate text-faint">
                        {run.symbol} · {timeAgo(run.created_at)}
                      </span>
                      <span className="shrink-0 text-ink">
                        {typeof run.summary?.total_return === 'number'
                          ? fmtPct(run.summary.total_return)
                          : '—'}
                      </span>
                    </div>
                  </button>
                )
              })
            ) : (
              <p className="px-4 py-8 text-center text-[11.5px] text-muted">暂无回放任务。</p>
            )}
          </div>
        </Card>
        <Card>
          <CardHead title="成交模型" hint="模拟成交的判定规则。" />
          <ul className="space-y-2 text-[11px] leading-relaxed text-muted">
            <li>限价挂单仅在 K 线区间穿越其价格时成交。</li>
            <li>市价单在下一根 K 线开盘时按滑点成交。</li>
            <li>手续费区分 Maker / Taker；资金费每 8 小时结算。</li>
          </ul>
        </Card>
      </div>

      <div className="space-y-4">
        {history.error ? <ErrorNote>{history.error}</ErrorNote> : null}

        {!selected ? (
          <Card>
            <Empty
              title="暂无可查看的成交"
              body="在回测实验室运行一次回放。每一笔模拟成交、撤单与拒单都会写入产物文件。"
              action={
                <Button variant="primary" onClick={() => navigate('backtest')}>
                  <ListOrdered size={13} /> 打开回测实验室
                </Button>
              }
            />
          </Card>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Card>
                <Stat
                  label="成交"
                  value={replay ? replay.fills.length.toLocaleString() : '—'}
                  sub={replay ? `${totals.maker} Maker · ${replay.fills.length - totals.maker} Taker` : '—'}
                  large
                />
              </Card>
              <Card>
                <Stat
                  label="成交名义价值"
                  value={replay ? `$${fmtMoney(totals.notional, 0)}` : '—'}
                  sub={replay ? `换手 ${fmtMoney(replay.summary.turnover_x ?? 0)}x` : '—'}
                  large
                />
              </Card>
              <Card>
                <Stat
                  label="手续费"
                  value={replay ? `$${fmtMoney(totals.fees)}` : '—'}
                  sub={replay ? `占资金 ${fmtPct((totals.fees / (replay.capital || 1)) * 100)}` : '—'}
                  large
                />
              </Card>
              <Card>
                <Stat
                  label="拒单"
                  value={
                    replay
                      ? replay.orders.rejection_reasons.reduce((acc, item) => acc + item.count, 0)
                      : '—'
                  }
                  sub={replay ? `结束时挂单 ${openOrders.length}` : '—'}
                  large
                />
              </Card>
            </div>

            <Card pad={false}>
              <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
                <div>
                  <h2 className="text-[13px] font-semibold text-ink">成交</h2>
                  <p className="mt-1 text-[11px] text-muted">
                    {selected.id} · {selected.symbol} ·{' '}
                    {replay ? `${fmtDateTimeLocal(replay.meta.start)} → ${fmtDateTimeLocal(replay.meta.end)}` : labelOf(selected.status)}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <FilterRow
                    label="方向"
                    options={SIDES}
                    value={side}
                    onChange={setSide}
                    format={labelOf}
                  />
                  <FilterRow
                    label="流动性"
                    options={LIQUIDITY}
                    value={liquidity}
                    onChange={setLiquidity}
                    format={labelOf}
                  />
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2 border-t border-line-soft px-5 pt-3">
                <div className="relative flex-1 sm:max-w-xs">
                  <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
                  <input
                    className="input h-8 pl-8 font-mono text-[11px]"
                    placeholder="按标签或客户端 ID 筛选"
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value)
                      setVisible(120)
                    }}
                  />
                </div>
                <span className="ml-auto font-mono text-[10.5px] text-faint">
                  匹配 {fills.length.toLocaleString()} 条
                </span>
              </div>
              {artifact.error ? (
                <div className="px-5 pb-4 pt-3">
                  <ErrorNote>{artifact.error}</ErrorNote>
                </div>
              ) : artifact.loading && selected.status === 'succeeded' ? (
                <div className="p-5">
                  <Skeleton className="h-[320px] w-full" />
                </div>
              ) : fills.length ? (
                <>
                  <div className="mt-3 max-h-[520px] overflow-auto">
                    <table className="w-full text-[11px]">
                      <thead className="sticky top-0 bg-panel">
                        <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                          <th className="px-5 py-2 font-medium">时间</th>
                          <th className="py-2 font-medium">方向</th>
                          <th className="py-2 text-right font-medium">价格</th>
                          <th className="py-2 text-right font-medium">数量</th>
                          <th className="py-2 text-right font-medium">名义价值</th>
                          <th className="py-2 text-right font-medium">手续费</th>
                          <th className="py-2 font-medium">流动性</th>
                          <th className="px-5 py-2 font-medium">标签</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fills.slice(0, visible).map((fill, index) => (
                          <tr key={`${fill.client_id}-${index}`} className="row-hover border-t border-line-soft/70">
                            <td className="whitespace-nowrap px-5 py-1.5 font-mono text-muted">
                              {fmtTime(fill.ts)}
                            </td>
                            <td className={cx('py-1.5 font-mono', fill.side === 'BUY' ? 'text-up' : 'text-down')}>
                              {labelOf(fill.side)}
                            </td>
                            <td className="py-1.5 text-right font-mono text-ink">{fmtPrice(fill.price)}</td>
                            <td className="py-1.5 text-right font-mono text-muted">{fmtQty(fill.qty, 4)}</td>
                            <td className="py-1.5 text-right font-mono text-muted">
                              {fmtMoney(fill.qty * fill.price, 2)}
                            </td>
                            <td className="py-1.5 text-right font-mono text-muted">{fmtMoney(fill.fee, 3)}</td>
                            <td className="py-1.5">
                              <Badge tone={fill.liquidity === 'MAKER' ? 'info' : 'neutral'}>
                                {labelOf(fill.liquidity)}
                              </Badge>
                            </td>
                            <td className="px-5 py-1.5 font-mono text-faint">{fill.tag}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {fills.length > visible ? (
                    <div className="border-t border-line-soft px-5 py-3 text-center">
                      <Button variant="ghost" size="sm" onClick={() => setVisible((value) => value + 200)}>
                        再显示 200 条
                      </Button>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="px-5 py-12 text-center text-[12px] text-muted">
                  {selected.status === 'succeeded'
                    ? '没有符合筛选条件的成交。'
                    : `任务状态：${labelOf(selected.status)}，完成后显示成交。`}
                </p>
              )}
            </Card>

            <div className="grid gap-4 xl:grid-cols-2">
              <Card>
                <CardHead
                  title="订单生命周期"
                  hint="模拟交易所记录的订单数量。"
                />
                {statuses.length ? (
                  <div className="grid grid-cols-2 gap-4">
                    {statuses.map(([status, count]) => (
                      <Stat key={status} label={orderLabel(status)} value={count} />
                    ))}
                  </div>
                ) : (
                  <Skeleton className="h-20 w-full" />
                )}
                {replay?.orders.rejection_reasons.length ? (
                  <div className="mt-4 space-y-1.5 border-t border-line-soft pt-3">
                    <div className="label">拒单原因</div>
                    {replay.orders.rejection_reasons.map((item) => (
                      <div key={item.reason} className="flex items-center justify-between gap-3 text-[11px]">
                        <span className="min-w-0 truncate font-mono text-muted">{reasonLabel(item.reason)}</span>
                        <span className="font-mono text-ink">{item.count}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </Card>

              <Card pad={false}>
                <div className="px-5 pt-5">
                  <h2 className="text-[13px] font-semibold text-ink">结束时挂单</h2>
                  <p className="mt-1 text-[11px] text-muted">
                    回放停止时仍未成交的挂单，最新的在前。
                  </p>
                </div>
                <div className="mt-3 max-h-[320px] overflow-auto border-t border-line-soft">
                  {openOrders.length ? (
                    <table className="w-full text-[11px]">
                      <thead className="sticky top-0 bg-panel">
                        <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                          <th className="px-5 py-2 font-medium">方向</th>
                          <th className="py-2 text-right font-medium">价格</th>
                          <th className="py-2 text-right font-medium">数量</th>
                          <th className="py-2 text-right font-medium">成交量</th>
                          <th className="px-5 py-2 font-medium">标签</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openOrders.map((order) => (
                          <tr key={order.client_id} className="row-hover border-t border-line-soft/70">
                            <td className={cx('px-5 py-1.5 font-mono', order.side === 'BUY' ? 'text-up' : 'text-down')}>
                              {labelOf(order.side)}
                            </td>
                            <td className="py-1.5 text-right font-mono text-ink">{fmtPrice(order.price)}</td>
                            <td className="py-1.5 text-right font-mono text-muted">{fmtQty(order.qty, 4)}</td>
                            <td className="py-1.5 text-right font-mono text-muted">{fmtQty(order.filled_qty, 4)}</td>
                            <td className="px-5 py-1.5 font-mono text-faint">{order.tag}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="px-5 py-10 text-center text-[12px] text-muted">
                      无挂单；网格已平仓或已停止。
                    </p>
                  )}
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
