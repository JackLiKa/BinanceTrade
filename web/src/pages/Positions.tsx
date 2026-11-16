import { useEffect, useState } from 'react'
import { ArrowRightLeft, Wallet } from 'lucide-react'
import { api, type ReplayArtifact, type Run } from '../api'
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Skeleton, Stat } from '../components/ui'
import { cx, fmtDateTimeLocal, fmtMoney, fmtPct, fmtPrice, fmtQty, timeAgo } from '../format'
import { statusTone, useArtifact, useFetch } from '../hooks'
import { navigate } from '../router'
import { loadParams } from '../params'
import { useApp } from '../store'

const LABELS: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '运行中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELED: '已取消',
  LONG: '多头',
  SHORT: '空头',
  FLAT: '空仓',
}

const labelOf = (value: string) => LABELS[value.toUpperCase()] ?? value

const STATE_LABELS: Record<string, string> = {
  anchor: '锚定价',
  step: '步长',
  level: '层级',
  size: '单层数量',
  grid_inventory: '网格库存',
  reanchor_pending: '待重新锚定',
}

function stateValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return fmtQty(value, 4)
  return String(value)
}

export function Positions() {
  const { symbol, snapshot } = useApp()
  const params = loadParams()
  const history = useFetch(() => api.runs('replay', 15), [], { pollMs: 20_000 })
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (selectedId || !history.data) return
    const first = history.data.runs.find((run) => run.status === 'succeeded')
    if (first) setSelectedId(first.id)
  }, [history.data, selectedId])

  const selected: Run | null = history.data?.runs.find((run) => run.id === selectedId) ?? null
  const artifact = useArtifact(selectedId, selected)
  const replay = artifact.data?.kind === 'replay' ? (artifact.data as ReplayArtifact) : null
  const risk = useFetch(
    () =>
      api.risk({
        symbol,
        capital: params.capital,
        spacing_bp: params.spacing_bp,
        levels: params.levels,
        leverage: params.leverage,
      }),
    [symbol, params.capital, params.spacing_bp, params.levels, params.leverage],
    { pollMs: 30_000 },
  )

  const position = replay?.summary.final_position ?? null
  const mark = snapshot?.mark_price ?? null
  const notional = position !== null && mark !== null ? Math.abs(position) * mark : null
  const grossLimit = risk.data?.limits.max_gross_notional ?? null
  const utilization = notional !== null && grossLimit ? (notional / grossLimit) * 100 : null
  const state = replay?.summary.strategy_state ?? null

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <Stat
            label="模拟持仓"
            value={position === null ? '—' : `${labelOf(position > 0 ? 'LONG' : position < 0 ? 'SHORT' : 'FLAT')} ${fmtQty(Math.abs(position), 4)}`}
            tone={position === null ? undefined : position}
            sub={selected ? `${selected.symbol} · ${selected.id}` : '未选择回放任务'}
            large
          />
        </Card>
        <Card>
          <Stat
            label="标记名义价值"
            value={notional === null ? '—' : `$${fmtMoney(notional, 0)}`}
            sub={
              notional === null
                ? '等待标记价格'
                : `${fmtPrice(mark)} 标记价 · ${symbol.replace('USDT', '')} 合约`
            }
            large
          />
        </Card>
        <Card>
          <Stat
            label="总敞口占用"
            value={utilization === null ? '—' : `${utilization.toFixed(1)}%`}
            tone={utilization !== null && utilization > 80 ? -1 : undefined}
            sub={grossLimit ? `上限 $${fmtMoney(grossLimit, 0)}` : '风险配置加载中'}
            large
          />
        </Card>
        <Card>
          <Stat
            label="平均库存"
            value={
              typeof replay?.summary.avg_inventory_pct === 'number'
                ? `${replay.summary.avg_inventory_pct.toFixed(1)}%`
                : '—'
            }
            sub="占用资金比例"
            large
          />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Card pad={false}>
          <div className="px-5 pt-5">
            <h2 className="text-[13px] font-semibold text-ink">回放结束状态</h2>
            <p className="mt-1 text-[11px] text-muted">
              两次回放之间账本为空，仅最近一次回放保留库存。
            </p>
          </div>
          {artifact.error ? (
            <div className="p-5">
              <ErrorNote>{artifact.error}</ErrorNote>
            </div>
          ) : replay ? (
            <div className="mt-4 border-t border-line-soft p-5">
              <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
                <Stat label="期末权益" value={`$${fmtMoney(replay.summary.final_equity, 0)}`} />
                <Stat label="基础资金" value={`$${fmtMoney(replay.capital, 0)}`} />
                <Stat label="收益率" value={fmtPct(replay.summary.total_return)} tone={replay.summary.total_return} />
                <Stat label="成交" value={replay.summary.trades} />
                <Stat label="资金费" value={`${replay.summary.funding <= 0 ? '+' : '−'}$${fmtMoney(Math.abs(replay.summary.funding))}`} tone={replay.summary.funding <= 0 ? 1 : -1} />
                <Stat
                  label="利润保护"
                  value={replay.summary.halted ? '已停止' : '正常'}
                  tone={replay.summary.halted ? -1 : 1}
                />
              </div>
              {state && Object.keys(state).length ? (
                <div className="mt-5 border-t border-line-soft pt-4">
                  <div className="label mb-2">策略状态</div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                    {Object.entries(state).map(([key, value]) => (
                      <div key={key} className="flex min-w-0 items-baseline justify-between gap-2 text-[11px]">
                        <span className="min-w-0 truncate text-faint" title={key}>
                          {STATE_LABELS[key] ?? key}
                        </span>
                        <span className="num shrink-0 text-muted">{stateValue(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <p className="mt-4 text-[10.5px] leading-relaxed text-faint">
                区间 {fmtDateTimeLocal(replay.meta.start)} → {fmtDateTimeLocal(replay.meta.end)} ·{' '}
                {replay.meta.bars.toLocaleString()} 根 K 线 · 生成于 {timeAgo(replay.meta.generated_at)}
              </p>
            </div>
          ) : selected?.status === 'succeeded' ? (
            <div className="p-5">
              <Skeleton className="h-[180px] w-full" />
            </div>
          ) : (
            <div className="p-5">
              <Empty
                title="暂无持仓账本"
                body="持仓来自已完成的回放。运行一次即可查看期末库存、权益与利润保护状态。"
                action={
                  <Button variant="primary" onClick={() => navigate('backtest')}>
                    <Wallet size={13} /> 运行回放
                  </Button>
                }
              />
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHead
              title="风险包络"
              hint="根据已保存的网格参数实时重算的限制。"
              right={
                risk.data ? (
                  <Badge tone={risk.data.kill_switch ? 'down' : 'up'}>
                    {risk.data.kill_switch ? '已停止' : '已启用'}
                  </Badge>
                ) : null
              }
            />
            {risk.error ? (
              <ErrorNote>{risk.error}</ErrorNote>
            ) : risk.data ? (
              <div className="space-y-2.5">
                {[
                  ['最大持仓', `${fmtQty(risk.data.limits.max_position_qty, 4)} 数量`],
                  ['单笔上限', `$${fmtMoney(risk.data.limits.max_order_notional, 0)}`],
                  ['总敞口上限', `$${fmtMoney(risk.data.limits.max_gross_notional, 0)}`],
                  ['挂单数', String(risk.data.limits.max_open_orders)],
                  ['每分钟提交', String(risk.data.limits.max_submits_per_minute)],
                  ['价格偏离', `${fmtMoney(risk.data.limits.max_price_deviation_bp, 0)} bp`],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 border-b border-line-soft pb-2 text-[11.5px] last:border-0 last:pb-0">
                    <span className="min-w-0 truncate text-muted">{label}</span>
                    <span className="num shrink-0 text-ink">{value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
          </Card>

          <Card>
            <CardHead title="利润保护" hint="相对当前标记价的止损距离估计。" />
            <div className="grid grid-cols-2 gap-4">
              <Stat
                label="止损回撤"
                value={params.stop_dd === null ? '未设置' : fmtPct(params.stop_dd * 100, 1, false)}
              />
              <Stat
                label="逆向波动"
                value={
                  params.stop_dd === null
                    ? '—'
                    : fmtPct((params.stop_dd / params.leverage) * 100, 1, false)
                }
                sub={`${params.leverage}x 杠杆`}
              />
              <Stat
                label="止损价"
                value={
                  params.stop_dd === null || mark === null
                    ? '—'
                    : fmtPrice(mark * (1 - params.stop_dd / params.leverage))
                }
                sub="若在此价位重新入场"
              />
              <Stat
                label="风险资金"
                value={
                  params.stop_dd === null ? '—' : `$${fmtMoney(params.capital * params.stop_dd, 0)}`
                }
              />
            </div>
          </Card>
        </div>
      </div>

      <Card pad={false}>
        <div className="flex items-center justify-between px-5 pt-5">
          <div>
            <h2 className="text-[13px] font-semibold text-ink">最近账本</h2>
            <p className="mt-1 text-[11px] text-muted">最近几次回放的期末持仓。</p>
          </div>
          <Button variant="ghost" size="sm" onClick={history.reload}>
            <ArrowRightLeft size={12} /> 刷新
          </Button>
        </div>
        <div className="mt-3 overflow-x-auto border-t border-line-soft">
          {history.error ? (
            <div className="p-5">
              <ErrorNote>{history.error}</ErrorNote>
            </div>
          ) : history.data?.runs.length ? (
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">任务</th>
                  <th className="py-2 font-medium">状态</th>
                  <th className="py-2 text-right font-medium">期末持仓</th>
                  <th className="py-2 text-right font-medium">收益率</th>
                  <th className="py-2 text-right font-medium">最大回撤</th>
                  <th className="py-2 text-right font-medium">资金费</th>
                  <th className="px-5 py-2 text-right font-medium">完成时间</th>
                </tr>
              </thead>
              <tbody>
                {history.data.runs.map((run) => {
                  const active = run.id === selectedId
                  return (
                    <tr
                      key={run.id}
                      onClick={() => setSelectedId(run.id)}
                      className={cx(
                        'cursor-pointer border-t border-line-soft/70',
                        active ? 'bg-accent/6' : 'row-hover',
                      )}
                    >
                      <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{run.id}</td>
                      <td className="py-2">
                        <Badge tone={statusTone(run.status)}>{labelOf(run.status)}</Badge>
                      </td>
                      <td className="py-2 text-right font-mono text-ink">
                        {typeof run.summary?.final_position === 'number'
                          ? fmtQty(run.summary.final_position, 4)
                          : '—'}
                      </td>
                      <td className="py-2 text-right font-mono text-muted">
                        {typeof run.summary?.total_return === 'number'
                          ? fmtPct(run.summary.total_return)
                          : '—'}
                      </td>
                      <td className="py-2 text-right font-mono text-muted">
                        {typeof run.summary?.max_dd === 'number'
                          ? fmtPct(-Math.abs(run.summary.max_dd))
                          : '—'}
                      </td>
                      <td className="py-2 text-right font-mono text-muted">
                        {typeof run.summary?.funding === 'number'
                          ? `${run.summary.funding <= 0 ? '+' : '−'}$${fmtMoney(Math.abs(run.summary.funding))}`
                          : '—'}
                      </td>
                      <td className="px-5 py-2 text-right text-faint">
                        {run.finished_at ? timeAgo(run.finished_at) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <p className="px-5 py-10 text-center text-[12px] text-muted">暂无回放任务。</p>
          )}
        </div>
      </Card>
    </div>
  )
}
