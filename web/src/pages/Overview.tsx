import type { ReactNode } from 'react'
import { ArrowUpRight, CircleDot, Database, FlaskConical, Lock, ShieldAlert, Wifi } from 'lucide-react'
import { api } from '../api'
import { EquityChart } from '../components/charts'
import { Badge, Card, CardHead, Empty, ErrorNote, Skeleton, Stat } from '../components/ui'
import { fmtCompact, fmtDate, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtRate, fmtTime, timeAgo } from '../format'
import { statusTone, useArtifact, useFetch } from '../hooks'
import { navigate } from '../router'
import { useApp } from '../store'
import type { Artifact, ReplayArtifact, Run, RunKind } from '../api'

const STATUS_LABELS: Record<Run['status'], string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
}

const KIND_LABELS: Record<RunKind, string> = {
  replay: '回放',
  walkforward: '前向滚动',
  sweep: '参数扫描',
}

const SOURCE_LABELS: Record<string, string> = {
  binance: 'Binance',
  dataset: '数据集',
  offline: '离线',
}

function runReturn(run: { summary: Record<string, unknown> | null }): number | null {
  const value = run.summary?.total_return
  return typeof value === 'number' ? value : null
}

function MonthlyBars({ rows, months }: { rows: Array<{ month: string; ret: number }>; months?: number }) {
  if (!rows.length) {
    return <p className="py-6 text-center text-[12px] text-muted">暂无月度切片。</p>
  }
  const max = Math.max(1.2, ...rows.map((row) => Math.abs(row.ret)))
  return (
    <div className="space-y-1.5">
      {rows.slice(-(months ?? 12)).map((row) => (
        <div key={row.month} className="flex items-center gap-3 text-[11px]">
          <span className="w-16 shrink-0 font-mono text-faint">{row.month}</span>
          <div className="relative h-4 flex-1 overflow-hidden rounded bg-elevated">
            <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
            <div
              className={`absolute inset-y-0.5 rounded-sm ${row.ret >= 0 ? 'bg-up/70' : 'bg-down/70'}`}
              style={{
                left: row.ret >= 0 ? '50%' : `${50 - (Math.abs(row.ret) / max) * 50}%`,
                width: `${(Math.abs(row.ret) / max) * 50}%`,
              }}
            />
          </div>
          <span className={`w-14 shrink-0 text-right font-mono ${row.ret >= 0 ? 'text-up' : 'text-down'}`}>
            {fmtPct(row.ret)}
          </span>
        </div>
      ))}
    </div>
  )
}

function ModeRow({
  name,
  enabled,
  locked,
  detail,
}: {
  name: string
  enabled: boolean
  locked?: boolean
  detail: string
}) {
  return (
    <div className="flex items-start gap-3 border-t border-line-soft py-2.5 first:border-0 first:pt-0 last:pb-0">
      <span
        className={`mt-[3px] grid h-5 w-5 shrink-0 place-items-center rounded-md border ${
          enabled ? 'border-up/30 bg-up/10 text-up' : 'border-line bg-elevated text-faint'
        }`}
      >
        {locked ? <Lock size={10} /> : <CircleDot size={10} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] font-medium text-ink">{name}</span>
          <Badge tone={enabled ? 'up' : locked ? 'neutral' : 'warn'}>
            {enabled ? '可用' : locked ? '已锁定' : '规划中'}
          </Badge>
        </div>
        <p className="mt-0.5 text-[10.5px] leading-snug text-faint">{detail}</p>
      </div>
    </div>
  )
}

function ArtifactSummary({ artifact }: { artifact: Artifact | null }): ReactNode {
  if (!artifact || artifact.kind !== 'replay') return null
  const replay = artifact as ReplayArtifact
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Stat label="总收益" value={fmtPct(replay.summary.total_return)} tone={replay.summary.total_return} />
      <Stat label="最大回撤" value={fmtPct(-Math.abs(replay.summary.max_dd))} tone={-1} />
      <Stat label="Sharpe" value={fmtMoney(replay.summary.sharpe)} />
      <Stat label="成交" value={fmtMoney(replay.summary.trades, 0)} />
    </div>
  )
}

export function Overview() {
  const { symbol, snapshot, killSwitch, modes } = useApp()
  const overview = useFetch(() => api.overview(symbol), [symbol], { pollMs: 60_000 })
  const data = overview.data
  const replayRun = data?.replay?.run ?? null
  const artifact = useArtifact(replayRun?.id ?? null, replayRun)
  const walkforward = data?.walkforward ?? null
  const quality = data?.dataset
  const replay = artifact.data?.kind === 'replay' ? (artifact.data as ReplayArtifact) : null

  if (overview.loading && !data) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card key={index}>
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-3 h-7 w-32" />
              <Skeleton className="mt-2 h-2.5 w-24" />
            </Card>
          ))}
        </div>
        <Card>
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-4 h-[220px] w-full" />
        </Card>
      </div>
    )
  }

  if (overview.error) {
    return <ErrorNote>{overview.error}</ErrorNote>
  }

  const market = data?.market ?? snapshot
  const change = market?.change_24h_pct ?? null
  const wf = walkforward?.summary
  const datasetAge = quality ? Math.max(0, Math.round((Date.now() - new Date(quality.end).getTime()) / 60000)) : null

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <Stat
            label={`${symbol || '市场'} 标记价格`}
            value={fmtPrice(market?.mark_price ?? null)}
            tone={change}
            sub={
              change === null
                ? market?.source === 'dataset'
                  ? `数据集收盘 · ${market?.as_of ? timeAgo(market.as_of) : '已过期'}`
                  : '等待行情推送'
                : `${fmtPct(change)} · 24 小时 ${market?.high_24h ? fmtPrice(market.low_24h, 2) + ' – ' + fmtPrice(market.high_24h, 2) : ''}`
            }
            large
          />
        </Card>
        <Card>
          <Stat
            label="最近回放"
            value={replayRun ? fmtPct(runReturn(replayRun)) : '—'}
            tone={replayRun ? runReturn(replayRun) : undefined}
            sub={
              replayRun
                ? `${replayRun.id} · ${timeAgo(replayRun.finished_at ?? replayRun.created_at)}`
                : '暂无回放'
            }
            large
          />
        </Card>
        <Card>
          <Stat
            label="前向滚动中位数"
            value={wf ? fmtPct(wf.median_ret) : '—'}
            tone={wf ? wf.median_ret : undefined}
            sub={
              wf
                ? `${wf.positive_months}/${wf.months} 个月为正 · 最差 ${fmtPct(wf.worst_ret)}`
                : '运行一次前向滚动即可填充'
            }
            large
          />
        </Card>
        <Card>
          <Stat
            label="数据集覆盖率"
            value={quality?.coverage_pct !== null && quality?.coverage_pct !== undefined ? `${quality.coverage_pct.toFixed(2)}%` : '—'}
            sub={
              quality
                ? `${fmtCompact(quality.bars)} 根 K 线 · ${fmtDate(quality.start)}`
                : '暂无数据集'
            }
            large
          />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.75fr_1fr]">
        <Card>
          <CardHead
            title="回放权益"
            hint={
              replay
                ? `${replay.meta.symbol} · ${replay.meta.start?.slice(0, 10)} → ${replay.meta.end?.slice(0, 10)} · ${replay.meta.bars.toLocaleString()} 根 K 线`
                : '最近一次回放的权益与回撤'
            }
            right={
              replay ? (
                <Badge tone={replay.summary.halted ? 'down' : 'up'}>
                  {replay.summary.halted ? '已停止' : '正常'}
                </Badge>
              ) : null
            }
          />
          {artifact.loading ? (
            <Skeleton className="h-[300px] w-full" />
          ) : replay ? (
            <>
              <EquityChart
                equity={replay.equity.points}
                drawdown={replay.drawdown.points}
                height={226}
                ddHeight={88}
              />
              <div className="mt-4 border-t border-line-soft pt-4">
                <ArtifactSummary artifact={artifact.data} />
              </div>
            </>
          ) : (
            <Empty
              title="暂无回放产物"
              body="在回测实验室中按日期区间运行网格。结果、成交与月度归因均保存在本地。"
              action={
                <button
                  onClick={() => navigate('backtest')}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-[12px] font-semibold text-[#0b0e11]"
                >
                  <FlaskConical size={13} /> 打开回测实验室
                </button>
              }
            />
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHead title="执行" hint="实盘交易保持锁定：无实盘适配器，无对账。" />
            <div className="space-y-0">
              <ModeRow
                name="研究"
                enabled={modes.research?.enabled ?? true}
                detail={modes.research?.detail ?? '本地 Parquet 回放'}
              />
              <ModeRow
                name="模拟"
                enabled={modes.paper?.enabled ?? false}
                detail={modes.paper?.detail ?? '规划中'}
              />
              <ModeRow
                name="实盘"
                enabled={modes.live?.enabled ?? false}
                locked={modes.live?.locked ?? true}
                detail={modes.live?.detail ?? '尚未提供实盘适配器'}
              />
            </div>
            {killSwitch ? (
              <div className="mt-3 flex items-center gap-2 rounded-lg border border-down/30 bg-down/8 px-3 py-2 text-[11px] text-down">
                <ShieldAlert size={13} /> 熔断已启用 — 新的研究任务仅供参考。
              </div>
            ) : null}
          </Card>

          <Card>
            <CardHead
              title="数据源"
              hint={market?.source === 'binance' ? 'Binance USD-M 实时标记价格' : '本地数据集回退'}
              right={
                <Badge tone={market?.source === 'binance' ? 'up' : 'warn'}>
                  <Wifi size={9} /> {market?.source ? SOURCE_LABELS[market.source] ?? market.source : SOURCE_LABELS.offline}
                </Badge>
              }
            />
            <div className="grid grid-cols-2 gap-4">
              <Stat label="资金费率" value={fmtRate(market?.last_funding_rate ?? null, 4)} />
              <Stat
                label="下次资金费率"
                value={
                  market?.next_funding_time
                    ? fmtTime(market.next_funding_time)
                    : '—'
                }
                mono={false}
              />
              <Stat label="24 小时成交量" value={fmtCompact(market?.quote_volume_24h ?? market?.volume_24h ?? null)} />
              <Stat
                label="K 线延迟"
                value={
                market?.bar_age_minutes != null
                  ? `${market.bar_age_minutes} 分钟`
                  : datasetAge != null
                    ? `${datasetAge} 分钟`
                    : '—'
              }
              />
            </div>
            <div className="mt-3 border-t border-line-soft pt-3 text-[10.5px] leading-relaxed text-faint">
              {quality
                ? `${fmtCompact(quality.bars)} 根 1 分钟 K 线 · ${fmtQty(quality.funding_settlements, 0)} 次资金费率结算 · ${quality.gap_count} 个超过 1 分钟的缺口`
                : '数据集不可用'}
            </div>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardHead
            title="前向滚动月度"
            hint={wf ? `${wf.months} 个月 · 止损 ${wf.stops} 次` : '逐月样本外切片'}
            right={
              <button
                onClick={() => navigate('backtest')}
                className="text-[11px] text-accent transition-opacity hover:opacity-80"
              >
                详情
              </button>
            }
          />
          {walkforward?.rows?.length ? (
            <MonthlyBars rows={walkforward.rows} months={9} />
          ) : (
            <Empty
              title="暂无前向滚动结果"
              body="月度切片可揭示单一全周期回放所掩盖的行情依赖。"
              action={
                <button
                  onClick={() => navigate('backtest')}
                  className="inline-flex items-center gap-1 rounded-lg border border-line bg-elevated px-3 py-2 text-[12px] text-ink"
                >
                  运行前向滚动 <ArrowUpRight size={12} />
                </button>
              }
            />
          )}
        </Card>

        <Card>
          <CardHead
            title="最近任务"
            hint="排队中、运行中与已完成的研究任务。"
            right={
              <button
                onClick={() => navigate('backtest')}
                className="text-[11px] text-accent transition-opacity hover:opacity-80"
              >
                全部任务
              </button>
            }
          />
          {data?.runs?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-[11.5px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                    <th className="pb-2 font-medium">任务</th>
                    <th className="pb-2 font-medium">类型</th>
                    <th className="pb-2 font-medium">状态</th>
                    <th className="pb-2 text-right font-medium">收益</th>
                    <th className="pb-2 text-right font-medium">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.runs.slice(0, 6).map((run) => (
                    <tr key={run.id} className="row-hover border-t border-line-soft">
                      <td className="py-2 font-mono text-[10.5px] text-muted">{run.id}</td>
                      <td className="py-2 text-muted">{KIND_LABELS[run.kind]}</td>
                      <td className="py-2">
                        <Badge tone={statusTone(run.status)}>{STATUS_LABELS[run.status]}</Badge>
                      </td>
                      <td className="py-2 text-right font-mono text-ink">{fmtPct(runReturn(run))}</td>
                      <td className="py-2 text-right text-faint">{timeAgo(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="暂无任务"
              body="先回放最近 30 天，再检查前向滚动的稳定性。"
              action={
                <button
                  onClick={() => navigate('backtest')}
                  className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-[12px] font-semibold text-[#0b0e11]"
                >
                  <Database size={12} /> 打开实验室
                </button>
              }
            />
          )}
        </Card>
      </div>
    </div>
  )
}
