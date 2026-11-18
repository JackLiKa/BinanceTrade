import { useEffect, useMemo, useState } from 'react'
import {
  Download,
  FlaskConical,
  Layers,
  ListFilter,
  Play,
  RefreshCw,
  Square,
  TrendingUp,
} from 'lucide-react'
import {
  api,
  type Artifact,
  type ReplayArtifact,
  type ResearchInput,
  type Run,
  type RunKind,
  type SweepArtifact,
  type SweepRow,
  type WalkforwardArtifact,
} from '../api'
import { CumulativeChart, EquityChart } from '../components/charts'
import { NumberInput, ParamsForm, Segmented } from '../components/inputs'
import {
  Badge,
  Button,
  Card,
  CardHead,
  Empty,
  ErrorNote,
  Progress,
  Skeleton,
  Stat,
} from '../components/ui'
import { cx, fmtDate, fmtDateTimeLocal, fmtDuration, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, timeAgo } from '../format'
import { errorText, statusTone, useArtifact, useFetch, useRunWatch } from '../hooks'
import { loadParams, saveParams, type GridParams } from '../params'
import { useApp } from '../store'

type Tab = RunKind

const KIND_LABELS: Record<Tab, string> = {
  replay: '回放',
  walkforward: '前向滚动',
  sweep: '参数扫描',
}

const STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
  cancelled: '已取消',
  new: '新建',
  partially_filled: '部分成交',
  filled: '已成交',
  expired: '已过期',
  rejected: '已拒绝',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status.toLowerCase()] ?? status.toLowerCase()
}

function sideLabel(side: string): string {
  return side === 'BUY' ? '买入' : side === 'SELL' ? '卖出' : side
}

function liquidityLabel(liquidity: string): string {
  return liquidity === 'MAKER' ? '挂单' : liquidity === 'TAKER' ? '吃单' : liquidity
}

const TABS: Array<{ value: Tab; label: string }> = [
  { value: 'replay', label: KIND_LABELS.replay },
  { value: 'walkforward', label: KIND_LABELS.walkforward },
  { value: 'sweep', label: KIND_LABELS.sweep },
]

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function rangePayload(start: string, end: string): { start: string | null; end: string | null } {
  return {
    start: start ? `${start}T00:00:00Z` : null,
    end: end ? `${new Date(new Date(`${end}T00:00:00Z`).getTime() + 86_400_000).toISOString()}` : null,
  }
}

function parseList(text: string, integer = false): number[] {
  return text
    .split(/[,\s]+/)
    .map((item) => Number(item))
    .filter((value) => Number.isFinite(value) && value > 0)
    .map((value) => (integer ? Math.round(value) : value))
}

function StatBlock({ artifact }: { artifact: ReplayArtifact }) {
  const summary = artifact.summary
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4">
      <Stat label="总收益" value={fmtPct(summary.total_return)} tone={summary.total_return} />
      <Stat label="年化收益" value={fmtPct(summary.ann_return)} tone={summary.ann_return} />
      <Stat label="最大回撤（账户权益）" value={fmtPct(-Math.abs(summary.max_dd))} tone={-1} />
      <Stat label="Sharpe" value={fmtMoney(summary.sharpe)} />
      <Stat label="期末权益" value={`$${fmtMoney(summary.final_equity, 0)}`} sub={`基准 $${fmtMoney(artifact.capital, 0)}`} />
      <Stat label="成交" value={fmtMoney(summary.trades, 0)} sub={`换手 ${fmtMoney(summary.turnover_x ?? 0)}x`} />
      <Stat label="手续费" value={`$${fmtMoney(summary.fees)}`} sub="挂单 + 吃单" />
      <Stat
        label="资金费收益"
        value={`${Number(summary.funding_income ?? -summary.funding) >= 0 ? '+' : '−'}$${fmtMoney(Math.abs(Number(summary.funding_income ?? -summary.funding)))}`}
        tone={Number(summary.funding_income ?? -summary.funding) >= 0 ? 1 : -1}
        sub="正数=赚 / 负数=亏"
      />
      {Number(summary.bad_debt ?? 0) > 0 ? (
        <>
          <Stat
            label="穿仓坏账"
            value={`$${fmtMoney(Number(summary.bad_debt), 2)}`}
            sub={`保险覆盖 $${fmtMoney(Number(summary.insurance_covered ?? 0), 2)}`}
            tone={-1}
          />
          <Stat
            label="未覆盖坏账"
            value={`$${fmtMoney(Number(summary.uncovered_bad_debt ?? 0), 2)}`}
            sub={`占本金 ${fmtMoney(Number(summary.bad_debt_pct ?? 0), 2)}%`}
            tone={-1}
          />
        </>
      ) : null}
      {summary.liquidation_price != null ? (
        <Stat
          label="强平价"
          value={`$${fmtMoney(Number(summary.liquidation_price), 4)}`}
          sub={summary.liquidation_time ? `强平于 ${fmtDateTimeLocal(String(summary.liquidation_time))}` : '已触发强平'}
          tone={-1}
        />
      ) : null}
    </div>
  )
}

function MonthlyTable({ rows }: { rows: ReplayArtifact['months'] }) {
  const totals = rows.reduce(
    (acc, row) => ({
      trades: acc.trades + row.trades,
      fees: acc.fees + row.fees,
      funding: acc.funding + (row.funding_income ?? -(row.funding ?? 0)),
    }),
    { trades: 0, fees: 0, funding: 0 },
  )
  if (!rows.length) return <p className="py-6 text-center text-[12px] text-muted">区间内无月度数据。</p>
  return (
    <div className="overflow-x-auto">
      <table className="monthly-table w-full text-[11.5px]">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
            <th className="pb-2 font-medium">月份</th>
            <th className="pb-2 text-right font-medium">收益</th>
            <th className="pb-2 text-right font-medium">最大回撤</th>
            <th className="pb-2 text-right font-medium">成交</th>
            <th className="pb-2 text-right font-medium">手续费</th>
            <th className="pb-2 text-right font-medium">资金费收益</th>
            <th className="pb-2 text-right font-medium">状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.month} className="row-hover border-t border-line-soft/70">
              <td className="py-1.5 font-mono text-muted">{row.month}</td>
              <td className={cx('py-1.5 text-right font-mono', row.ret >= 0 ? 'text-up' : 'text-down')}>
                {fmtPct(row.ret)}
              </td>
              <td className="py-1.5 text-right font-mono text-muted">{fmtPct(-Math.abs(row.dd))}</td>
              <td className="py-1.5 text-right font-mono text-muted">{row.trades}</td>
              <td className="py-1.5 text-right font-mono text-muted">${fmtMoney(row.fees)}</td>
              <td
                className={cx(
                  'py-1.5 text-right font-mono',
                  row.funding_income == null && row.funding == null ? 'text-faint' : (row.funding_income ?? -(row.funding ?? 0)) >= 0 ? 'text-up' : 'text-down',
                )}
              >
                {row.funding_income == null && row.funding == null
                  ? '—'
                  : `${(row.funding_income ?? -(row.funding ?? 0)) >= 0 ? '+' : '−'}$${fmtMoney(Math.abs(row.funding_income ?? -(row.funding ?? 0)))}`}
              </td>
              <td className="py-1.5 text-right">
                {row.halted ? <Badge tone="down">已停止</Badge> : <span className="text-faint">—</span>}
              </td>
            </tr>
          ))}
          <tr className="border-t border-line text-[11px]">
            <td className="py-2 font-medium text-ink">合计</td>
            <td className="py-2 text-right font-mono text-ink">
              {fmtPct(rows.reduce((acc, row) => acc + row.ret, 0))}
            </td>
            <td className="py-2 text-right font-mono text-faint">复利</td>
            <td className="py-2 text-right font-mono text-ink">{totals.trades}</td>
            <td className="py-2 text-right font-mono text-ink">${fmtMoney(totals.fees)}</td>
            <td className="py-2 text-right font-mono text-ink">
              {totals.funding >= 0 ? '+' : '−'}${fmtMoney(Math.abs(totals.funding))}
            </td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function ReplayView({ artifact }: { artifact: ReplayArtifact }) {
  const [fillSide, setFillSide] = useState<'ALL' | 'BUY' | 'SELL'>('ALL')
  const fills = useMemo(
    () =>
      [...artifact.fills]
        .reverse()
        .filter((fill) => fillSide === 'ALL' || fill.side === fillSide)
        .slice(0, 200),
    [artifact.fills, fillSide],
  )
  const counts = artifact.orders.counts
  const maker = artifact.fills.filter((fill) => fill.liquidity === 'MAKER').length
  return (
    <div className="space-y-4">
      <Card>
        <CardHead
          title="业绩表现"
          hint={`${fmtDate(artifact.meta.start)} → ${fmtDate(artifact.meta.end)} · ${artifact.meta.bars.toLocaleString()} 根 K 线 · ${fmtDuration(artifact.meta.duration_s)}`}
          right={
            <div className="flex items-center gap-2">
              {artifact.summary.liquidated ? (
                <Badge tone="down">已爆仓强平</Badge>
              ) : artifact.summary.halted ? (
                <Badge tone="down">已停止</Badge>
              ) : (
                <Badge tone="up">已完成</Badge>
              )}
              <Badge tone={(artifact.summary.final_position ?? 0) !== 0 ? 'warn' : 'neutral'}>
                {fmtQty(artifact.summary.final_position ?? 0, 4)} 期末持仓
                {(artifact.summary.final_position ?? 0) !== 0 ? '（未平仓）' : ''}
              </Badge>
            </div>
          }
        />
        <StatBlock artifact={artifact} />
      </Card>

      <Card>
        <CardHead
          title="权益与回撤"
          hint={`由 ${artifact.equity.sampled_from.toLocaleString()} 点采样至 ${artifact.equity.points.length} 点`}
        />
        <EquityChart equity={artifact.equity.points} drawdown={artifact.drawdown.points} height={280} ddHeight={100} />
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHead title="月度归因" hint="资金费收益正数=赚、负数=亏；成交为 0 的月份收益来自持仓市值变化。" />
          <MonthlyTable rows={artifact.months} />
        </Card>

        <Card>
          <CardHead
            title="订单流"
            hint={`成交 ${artifact.fills.length.toLocaleString()} 笔 · 挂单 ${maker} / 吃单 ${artifact.fills.length - maker}`}
          />
          <div className="grid grid-cols-2 gap-4">
            {Object.entries(counts).map(([status, count]) => (
              <Stat key={status} label={statusLabel(status)} value={count} />
            ))}
            <Stat label="期末挂单" value={artifact.orders.open.length} />
            <Stat
              label="拒单"
              value={artifact.orders.rejection_reasons.reduce((acc, item) => acc + item.count, 0)}
            />
          </div>
          {artifact.orders.rejection_reasons.length ? (
            <div className="mt-4 space-y-1.5 border-t border-line-soft pt-3">
              <div className="label">拒单原因</div>
              {artifact.orders.rejection_reasons.map((item) => (
                <div key={item.reason} className="flex items-center justify-between gap-3 text-[11px]">
                  <span className="min-w-0 truncate font-mono text-muted">{item.reason}</span>
                  <span className="font-mono text-ink">{item.count}</span>
                </div>
              ))}
            </div>
          ) : null}
          {artifact.orders.open.length ? (
            <div className="mt-4 space-y-1.5 border-t border-line-soft pt-3">
              <div className="label">挂单中</div>
              {artifact.orders.open.slice(0, 6).map((order) => (
                <div key={order.client_id} className="flex items-center justify-between gap-3 text-[11px]">
                  <span className={order.side === 'BUY' ? 'text-up' : 'text-down'}>{sideLabel(order.side)}</span>
                  <span className="font-mono text-muted">{fmtPrice(order.price)}</span>
                  <span className="font-mono text-faint">{fmtQty(order.qty, 4)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </Card>
      </div>

      <Card pad={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
          <div>
            <h2 className="text-[13px] font-semibold text-ink">成交</h2>
            <p className="mt-1 text-[11px] text-muted">
              {artifact.fills_truncated ? '仅显示本次运行记录的最新 5,000 笔成交。' : '本次运行的全部模拟成交。'}
            </p>
          </div>
          <Segmented
            value={fillSide}
            onChange={setFillSide}
            options={[
              { value: 'ALL', label: '全部' },
              { value: 'BUY', label: '买入' },
              { value: 'SELL', label: '卖出' },
            ]}
          />
        </div>
        <div className="mt-3 max-h-[440px] overflow-auto border-t border-line-soft">
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
              {fills.map((fill, index) => (
                <tr key={`${fill.ts}-${index}`} className="row-hover border-t border-line-soft/70">
                  <td className="whitespace-nowrap px-5 py-1.5 font-mono text-muted">{fmtTime(fill.ts)}</td>
                  <td className={cx('py-1.5 font-mono', fill.side === 'BUY' ? 'text-up' : 'text-down')}>
                    {sideLabel(fill.side)}
                  </td>
                  <td className="py-1.5 text-right font-mono text-ink">{fmtPrice(fill.price)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtQty(fill.qty, 4)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">
                    {fmtMoney(fill.qty * fill.price, 2)}
                  </td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtMoney(fill.fee, 3)}</td>
                  <td className="py-1.5">
                    <Badge tone={fill.liquidity === 'MAKER' ? 'info' : 'neutral'}>{liquidityLabel(fill.liquidity)}</Badge>
                  </td>
                  <td className="px-5 py-1.5 font-mono text-faint">{fill.tag}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function WalkforwardView({ artifact }: { artifact: WalkforwardArtifact }) {
  const summary = artifact.summary
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4">
        <Stat label="月份数" value={summary.months} />
        <Stat label="月均收益" value={fmtPct(summary.mean_ret)} tone={summary.mean_ret} />
        <Stat label="收益中位数" value={fmtPct(summary.median_ret)} tone={summary.median_ret} />
        <Stat label="最差月份" value={fmtPct(summary.worst_ret)} tone={summary.worst_ret} />
        <Stat label="最佳月份" value={fmtPct(summary.best_ret)} tone={summary.best_ret} />
        <Stat label="盈利月" value={`${summary.positive_months}/${summary.months}`} />
        <Stat label="止损次数" value={summary.stops} tone={summary.stops > 0 ? -1 : undefined} />
        <Stat label="累计收益" value={fmtPct(summary.total_return)} tone={summary.total_return} />
      </div>

      <Card>
        <CardHead
          title="累计收益"
          hint="每月使用相同基准资金独立回放。"
          right={<Badge tone="neutral">最小切片 {artifact.meta.min_days} 天</Badge>}
        />
        <CumulativeChart points={artifact.cumulative} height={260} />
      </Card>

      <Card pad={false}>
        <div className="px-5 pt-5">
          <h2 className="text-[13px] font-semibold text-ink">月度切片</h2>
          <p className="mt-1 text-[11px] text-muted">
            {fmtDate(artifact.meta.start)} → {fmtDate(artifact.meta.end)}
          </p>
        </div>
        <div className="mt-3 overflow-x-auto border-t border-line-soft">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2 font-medium">月份</th>
                <th className="py-2 text-right font-medium">收益</th>
                <th className="py-2 text-right font-medium">最大回撤</th>
                <th className="py-2 text-right font-medium">Sharpe</th>
                <th className="py-2 text-right font-medium">成交</th>
                <th className="py-2 text-right font-medium">手续费</th>
                <th className="py-2 text-right font-medium">资金费率</th>
                <th className="px-5 py-2 text-right font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {artifact.rows.map((row) => (
                <tr key={row.month} className="row-hover border-t border-line-soft/70">
                  <td className="px-5 py-1.5 font-mono text-muted">{row.month}</td>
                  <td className={cx('py-1.5 text-right font-mono', row.ret >= 0 ? 'text-up' : 'text-down')}>
                    {fmtPct(row.ret)}
                  </td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtPct(-Math.abs(row.max_dd))}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtMoney(row.sharpe)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{row.trades}</td>
                  <td className="py-1.5 text-right font-mono text-muted">${fmtMoney(row.fees)}</td>
                  <td className={cx('py-1.5 text-right font-mono', row.funding <= 0 ? 'text-up' : 'text-down')}>
                    {row.funding <= 0 ? '+' : '−'}${fmtMoney(Math.abs(row.funding))}
                  </td>
                  <td className="px-5 py-1.5 text-right">
                    {row.halted ? <Badge tone="down">已停止</Badge> : <span className="text-faint">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function SweepView({
  artifact,
  onApply,
}: {
  artifact: SweepArtifact
  onApply: (row: SweepRow) => void
}) {
  const rows = artifact.rows
  const best = artifact.summary.best
  const maxAnn = Math.max(1, ...rows.map((row) => Math.abs(row.ann_return)))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4">
        <Stat label="组合数" value={artifact.summary.combos} />
        <Stat label="盈利组合" value={`${artifact.summary.positive}/${artifact.summary.combos}`} />
        <Stat
          label="最佳年化"
          value={best ? fmtPct(best.ann_return) : '—'}
          tone={best?.ann_return}
          sub={best ? `${best.spacing_bp}bp · ${best.levels} 层 · ${best.leverage}x` : undefined}
        />
        <Stat
          label="最低回撤"
          value={best ? fmtPct(-Math.abs(best.max_dd)) : '—'}
          tone={-1}
        />
      </div>

      <Card pad={false}>
        <div className="flex items-center justify-between px-5 pt-5">
          <div>
            <h2 className="text-[13px] font-semibold text-ink">参数扫描</h2>
            <p className="mt-1 text-[11px] text-muted">按年化收益排序。点击行载入配置。</p>
          </div>
          <Badge tone="neutral">{artifact.meta.axes?.spacings.join(' / ') ?? ''} bp</Badge>
        </div>
        <div className="mt-3 overflow-x-auto border-t border-line-soft">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                <th className="px-5 py-2 font-medium">间距</th>
                <th className="py-2 text-right font-medium">层数</th>
                <th className="py-2 text-right font-medium">杠杆</th>
                <th className="py-2 text-right font-medium">年化</th>
                <th className="py-2 font-medium"> </th>
                <th className="py-2 text-right font-medium">累计</th>
                <th className="py-2 text-right font-medium">最大回撤</th>
                <th className="py-2 text-right font-medium">Sharpe</th>
                <th className="px-5 py-2 text-right font-medium">成交</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${row.spacing_bp}-${row.levels}-${row.leverage}`}
                  onClick={() => onApply(row)}
                  className="row-hover cursor-pointer border-t border-line-soft/70"
                >
                  <td className="px-5 py-1.5 font-mono text-muted">{row.spacing_bp}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{row.levels}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{row.leverage}x</td>
                  <td className={cx('py-1.5 text-right font-mono', row.ann_return >= 0 ? 'text-up' : 'text-down')}>
                    {fmtPct(row.ann_return)}
                  </td>
                  <td className="w-32 py-1.5 pl-3">
                    <div className="h-1.5 w-full overflow-hidden rounded bg-elevated">
                      <div
                        className={cx('h-full rounded', row.ann_return >= 0 ? 'bg-up/70' : 'bg-down/70')}
                        style={{
                          width: `${Math.min(100, (Math.abs(row.ann_return) / maxAnn) * 100)}%`,
                        }}
                      />
                    </div>
                  </td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtPct(row.total_return)}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtPct(-Math.abs(row.max_dd))}</td>
                  <td className="py-1.5 text-right font-mono text-muted">{fmtMoney(row.sharpe)}</td>
                  <td className="px-5 py-1.5 text-right font-mono text-muted">{row.trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

export function Backtest() {
  const { symbol, toast, snapshot } = useApp()
  const [tab, setTab] = useState<Tab>('replay')
  const [params, setParams] = useState<GridParams>(() => loadParams())
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [minDays, setMinDays] = useState(5)
  const [spacings, setSpacings] = useState('60, 90, 120')
  const [levels, setLevels] = useState('10, 20, 30')
  const [leverages, setLeverages] = useState('0.5, 1.0')
  const [runId, setRunId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const quality = useFetch(() => api.quality(symbol), [symbol])
  const history = useFetch(() => api.runs(undefined, 25), [], { pollMs: 5_000 })

  useEffect(() => {
    if (!quality.data || start || end) return
    const last = new Date(quality.data.end)
    const first = new Date(last.getTime() - 90 * 86_400_000)
    setStart(isoDay(first))
    setEnd(isoDay(last))
  }, [quality.data, start, end])

  const watch = useRunWatch(runId, (run) => {
    history.reload()
    if (run.status === 'succeeded') toast(`${KIND_LABELS[run.kind]}已完成`, 'ok')
    else if (run.status === 'failed') toast(run.error ?? `${KIND_LABELS[run.kind]}失败`, 'error')
  })
  const artifact = useArtifact(runId, watch.run)
  const active = watch.run ? watch.run.status === 'queued' || watch.run.status === 'running' : false

  const updateParams = (next: GridParams) => {
    setParams(next)
    saveParams(next)
  }

  const applyRow = (row: SweepRow) => {
    updateParams({ ...params, spacing_bp: row.spacing_bp, levels: row.levels, leverage: row.leverage })
    setTab('replay')
    toast(`已载入 ${row.spacing_bp}bp · ${row.levels} 层 · ${row.leverage}x`, 'info')
  }

  const selectRun = (run: Run) => {
    setTab(run.kind)
    setRunId(run.id)
    const stored = run.params as Partial<ResearchInput> & { axes?: unknown; min_days?: number }
    if (typeof stored.capital === 'number') {
      updateParams({
        capital: stored.capital,
        spacing_bp: typeof stored.spacing_bp === 'number' ? stored.spacing_bp : params.spacing_bp,
        levels: typeof stored.levels === 'number' ? stored.levels : params.levels,
        leverage: typeof stored.leverage === 'number' ? stored.leverage : params.leverage,
        reanchor_bars: stored.reanchor_bars ?? null,
        stop_dd: stored.stop_dd ?? null,
        maker_fee: typeof stored.maker_fee === 'number' ? stored.maker_fee : params.maker_fee,
        taker_fee: typeof stored.taker_fee === 'number' ? stored.taker_fee : params.taker_fee,
        slip_bp: typeof stored.slip_bp === 'number' ? stored.slip_bp : params.slip_bp,
        intrabar: Boolean(stored.intrabar),
      })
    }
    if (stored.axes) {
      const axes = stored.axes as { spacings: number[]; levels: number[]; leverages: number[] }
      setSpacings(axes.spacings.join(', '))
      setLevels(axes.levels.join(', '))
      setLeverages(axes.leverages.join(', '))
    }
    if (typeof stored.min_days === 'number') setMinDays(stored.min_days)
  }

  const submit = async () => {
    setFormError(null)
    if (!symbol) {
      setFormError('未选择交易对。')
      return
    }
    if (start && end && start > end) {
      setFormError('开始日期不能晚于结束日期。')
      return
    }
    const range = rangePayload(start, end)
    const base: ResearchInput = { ...params, symbol, ...range }
    setSubmitting(true)
    try {
      let result
      if (tab === 'replay') {
        result = await api.submitReplay(base)
      } else if (tab === 'walkforward') {
        result = await api.submitWalkforward({ ...base, min_days: minDays })
      } else {
        const axes = {
          spacings: parseList(spacings),
          levels: parseList(levels, true),
          leverages: parseList(leverages),
        }
        if (!axes.spacings.length || !axes.levels.length || !axes.leverages.length) {
          throw new Error('每个扫描维度至少需要一个正数。')
        }
        result = await api.submitSweep({ ...base, axes })
      }
      setRunId(result.run.id)
      history.reload()
      toast(`${KIND_LABELS[tab]}已入队：${result.run.id}`, 'info')
    } catch (error) {
      const message = errorText(error)
      setFormError(message)
      toast(message, 'error')
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = async () => {
    if (!runId) return
    try {
      await api.cancelRun(runId)
      toast('已请求取消', 'info')
    } catch (error) {
      toast(errorText(error), 'error')
    }
  }

  const exportArtifact = () => {
    if (!artifact.data || !runId) return
    const blob = new Blob([JSON.stringify(artifact.data, null, 2)], { type: 'application/json' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `${runId}-${artifact.data.kind}.json`
    link.click()
    URL.revokeObjectURL(link.href)
  }

  const run = watch.run
  const data = artifact.data

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
      <div className="space-y-4">
        <Card>
          <CardHead
            title="运行配置"
            hint="参数保存在本地，并用于策略预览。"
            right={<Badge tone="accent">{symbol || '—'}</Badge>}
          />
          <div className="mb-4 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => {
                if (!quality.data) return
                const last = new Date(quality.data.end)
                setStart(isoDay(new Date(last.getTime() - 30 * 86_400_000)))
                setEnd(isoDay(last))
              }}
              className="rounded-md border border-line bg-elevated px-2 py-1 text-[10.5px] text-muted hover:text-ink"
            >
              近 30 天
            </button>
            <button
              type="button"
              onClick={() => {
                if (!quality.data) return
                setStart(isoDay(new Date(quality.data.start)))
                setEnd(isoDay(new Date(quality.data.end)))
              }}
              className="rounded-md border border-line bg-elevated px-2 py-1 text-[10.5px] text-muted hover:text-ink"
            >
              全部历史
            </button>
            <button
              type="button"
              onClick={() => {
                setStart('')
                setEnd('')
              }}
              className="rounded-md border border-line bg-elevated px-2 py-1 text-[10.5px] text-muted hover:text-ink"
            >
              清除
            </button>
          </div>
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label">开始</span>
              <input type="date" value={start} onChange={(event) => setStart(event.target.value)} className="input mt-1.5" />
            </label>
            <label className="block">
              <span className="label">结束</span>
              <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} className="input mt-1.5" />
            </label>
          </div>

          <ParamsForm value={params} onChange={updateParams} compact={tab === 'sweep'} />

          {(() => {
            const minNotional = quality.data?.filters?.min_notional ?? 5
            const unitNotional = (params.capital * params.leverage) / Math.max(1, params.levels)
            if (unitNotional + 1e-9 >= minNotional) return null
            return (
              <div className="mt-3">
                <ErrorNote>
                  每格名义约 ${unitNotional.toFixed(2)}，低于交易所最小名义 ${minNotional.toFixed(2)}；
                  回测会直接失败或 0 成交。请提高本金/杠杆，或降低层数。
                </ErrorNote>
              </div>
            )
          })()}

          {params.leverage >= 5 || params.stop_dd === null ? (
            <div className="mt-3">
              <ErrorNote>
                当前 {params.leverage}x 杠杆{params.stop_dd === null ? '、未设回撤止损' : ''}：
                全仓网格在单边趋势中会快速打满库存并触发强平，回测出现 -100% 属于参数风险。
                建议先用 0.5–2x 并设置回撤止损。
              </ErrorNote>
            </div>
          ) : null}

          {tab === 'walkforward' ? (
            <div className="mt-4">
              <label className="block">
                <span className="label">最小切片天数</span>
                <div className="mt-1.5">
                  <NumberInput value={minDays} onChange={(next) => setMinDays(Math.round(next ?? 5))} min={1} max={31} suffix="天" />
                </div>
              </label>
            </div>
          ) : null}

          {tab === 'sweep' ? (
            <div className="mt-4 space-y-3 rounded-lg border border-line-soft bg-[#12151a] p-3">
              <div className="label">扫描维度</div>
              <label className="block">
                <span className="text-[10.5px] text-muted">间距（bp）</span>
                <input className="input mt-1 font-mono text-[12px]" value={spacings} onChange={(event) => setSpacings(event.target.value)} />
              </label>
              <label className="block">
                <span className="text-[10.5px] text-muted">层数</span>
                <input className="input mt-1 font-mono text-[12px]" value={levels} onChange={(event) => setLevels(event.target.value)} />
              </label>
              <label className="block">
                <span className="text-[10.5px] text-muted">杠杆</span>
                <input className="input mt-1 font-mono text-[12px]" value={leverages} onChange={(event) => setLeverages(event.target.value)} />
              </label>
              <p className="text-[10px] leading-snug text-faint">
                {parseList(spacings).length * parseList(levels, true).length * parseList(leverages).length} 组 ·
                上限 48 组
              </p>
            </div>
          ) : null}

          {formError ? (
            <div className="mt-3">
              <ErrorNote>{formError}</ErrorNote>
            </div>
          ) : null}

          <div className="mt-4 flex items-center gap-2">
            <Button variant="primary" className="flex-1" onClick={submit} loading={submitting || active}>
              <Play size={13} /> 开始{KIND_LABELS[tab]}
            </Button>
            {active ? (
              <Button variant="danger" onClick={cancel}>
                <Square size={12} /> 停止
              </Button>
            ) : null}
          </div>
          {active ? (
            <div className="mt-3">
              <Progress value={run?.progress ?? 0} message={run?.message} />
            </div>
          ) : null}
        </Card>

        <Card>
          <CardHead
            title="历史"
            hint="最近 25 次运行，存储于 SQLite。"
            right={
              <button onClick={history.reload} className="text-faint hover:text-ink" aria-label="刷新运行记录">
                <RefreshCw size={12} />
              </button>
            }
          />
          {history.error ? (
            <ErrorNote>{history.error}</ErrorNote>
          ) : history.loading && !history.data ? (
            <Skeleton className="h-24 w-full" />
          ) : history.data?.runs.length ? (
            <div className="max-h-[360px] space-y-1 overflow-y-auto pr-1">
              {history.data.runs.map((item) => (
                <button
                  key={item.id}
                  onClick={() => selectRun(item)}
                  className={cx(
                    'flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[11px] transition-colors',
                    item.id === runId
                      ? 'border-accent/30 bg-accent/8'
                      : 'border-transparent hover:border-line-soft hover:bg-elevated/60',
                  )}
                >
                  <span className="flex-1 truncate font-mono text-[10px] text-muted">{item.id}</span>
                  <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
                  <span className={cx('w-12 text-right font-mono', item.kind === 'sweep' ? 'text-faint' : 'text-ink')}>
                    {item.kind === 'sweep' ? `${Object.keys((item.params.axes as object) ?? {}).length} 个维度` : fmtPct(
                      typeof item.summary?.total_return === 'number' ? item.summary.total_return : null,
                    )}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-[12px] text-muted">暂无运行记录。</p>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
          <Segmented options={TABS} value={tab} onChange={(next) => setTab(next)} />
          <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
            {run ? (
              <span className="min-w-0 truncate font-mono text-[10.5px] text-faint" title={run.id}>
                {run.id} · {timeAgo(run.created_at)}
              </span>
            ) : null}
            {data ? (
              <Button variant="ghost" size="sm" onClick={exportArtifact}>
                <Download size={12} /> JSON
              </Button>
            ) : null}
          </div>
        </div>

        {run && (run.status === 'failed' || run.status === 'canceled') ? (
          <ErrorNote>
            {run.status === 'failed' ? run.error ?? '运行失败' : '运行已取消'} — {run.message ?? ''}
          </ErrorNote>
        ) : null}

        {watch.error ? <ErrorNote>{watch.error}</ErrorNote> : null}

        {artifact.loading && run?.status === 'succeeded' ? (
          <Card>
            <Skeleton className="h-6 w-40" />
            <Skeleton className="mt-4 h-[240px] w-full" />
          </Card>
        ) : data && data.kind === 'replay' && tab === 'replay' ? (
          <ReplayView artifact={data as ReplayArtifact} />
        ) : data && data.kind === 'walkforward' && tab === 'walkforward' ? (
          <WalkforwardView artifact={data as WalkforwardArtifact} />
        ) : data && data.kind === 'sweep' && tab === 'sweep' ? (
          <SweepView artifact={data as SweepArtifact} onApply={applyRow} />
        ) : active ? (
          <Card>
            <CardHead
              title={`${KIND_LABELS[tab]}进行中`}
              hint={run?.message ?? '预热中'}
              right={<Badge tone="accent">{Math.round((run?.progress ?? 0) * 100)}%</Badge>}
            />
            <Progress value={run?.progress ?? 0} message={run?.message} />
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index}>
                  <Skeleton className="h-2.5 w-16" />
                  <Skeleton className="mt-2 h-5 w-24" />
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Card>
            <Empty
              title={`尚未选择${KIND_LABELS[tab]}`}
              body={
                tab === 'sweep'
                  ? '扫描间距 / 层数 / 杠杆组合，检验哪些参数能覆盖手续费与资金费率。'
                  : tab === 'walkforward'
                    ? '按月切片并逐月独立回放，检验策略对市场状态的依赖。'
                    : '按保守成交假设逐根 K 线回放网格，再查看成交与月度归因。'
              }
              action={
                <Button variant="outline" onClick={submit} loading={submitting}>
                  <FlaskConical size={13} /> 立即运行{KIND_LABELS[tab]}
                </Button>
              }
            />
            {run && run.status === 'succeeded' && artifact.error ? <ErrorNote>{artifact.error}</ErrorNote> : null}
          </Card>
        )}

        {artifact.error && run?.status === 'succeeded' ? <ErrorNote>{artifact.error}</ErrorNote> : null}

        {!run && history.data?.runs.length ? (
          <Card>
            <CardHead title="接着上次继续" hint="从历史面板选择已保存的运行。" />
            <div className="grid gap-2 sm:grid-cols-2">
              {history.data.runs.slice(0, 4).map((item) => (
                <button
                  key={item.id}
                  onClick={() => selectRun(item)}
                  className="flex items-center justify-between rounded-lg border border-line-soft bg-elevated/40 px-3 py-2 text-left text-[11.5px] hover:border-line"
                >
                  <span className="flex items-center gap-2">
                    <FlaskConical size={12} className="text-accent" />
                    <span className="font-mono text-[10.5px] text-muted">{item.id}</span>
                  </span>
                  <Badge tone={statusTone(item.status)}>{KIND_LABELS[item.kind]}</Badge>
                </button>
              ))}
            </div>
          </Card>
        ) : null}

        {snapshot && !quality.data ? (
          <p className="text-[10.5px] text-faint">
            实时标记价 {fmtPrice(snapshot.mark_price ?? null)} · 仅合约
          </p>
        ) : null}
      </div>
    </div>
  )
}
