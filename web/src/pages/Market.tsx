import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../api'
import { FundingChart, PriceChart } from '../components/charts'
import { Badge, Button, Card, CardHead, ErrorNote, Skeleton, Stat } from '../components/ui'
import { fmtCompact, fmtPct, fmtPrice, fmtRate, fmtTime, timeAgo } from '../format'
import { useDeferredMount, useFetch, useInView } from '../hooks'
import { useApp } from '../store'

const INTERVALS = ['1m', '5m', '15m', '1h', '4h', '1d'] as const

export function Market() {
  const { symbol, snapshot } = useApp()
  const [span, setSpan] = useState<(typeof INTERVALS)[number]>('1h')
  const [limit, setLimit] = useState(180)
  const candles = useFetch(
    () => api.candles({ symbol, interval: span, limit }),
    [symbol, span, limit],
  )
  // Funding history is below the fold: only fetch/draw it after the user scrolls near it.
  const [fundingRef, fundingInView] = useInView<HTMLDivElement>('280px')
  const funding = useFetch(() => api.funding({ symbol, limit: 120 }), [symbol, fundingInView], {
    enabled: fundingInView,
  })
  // Paint the stat cards first, then mount the canvas chart on the next frame.
  const chartReady = useDeferredMount(0)
  const data = candles.data
  const last = data?.candles.at(-1) ?? null
  const previous = data?.candles.at(-2) ?? null
  const change = last && previous ? ((last[4] / previous[4] - 1) * 100) : null
  const rangeHigh = data ? Math.max(...data.candles.map((candle) => candle[2])) : null
  const rangeLow = data ? Math.min(...data.candles.map((candle) => candle[3])) : null

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <Stat
            label={`${symbol} 标记价格`}
            value={fmtPrice(snapshot?.mark_price ?? (last ? last[4] : null))}
            tone={snapshot?.change_24h_pct ?? change}
            sub={snapshot ? `${fmtPct(snapshot.change_24h_pct)} · 24 小时` : '仅数据集'}
            large
          />
        </Card>
        <Card>
          <Stat
            label="24 小时区间"
            value={
              snapshot?.low_24h != null && snapshot?.high_24h != null
                ? `${fmtPrice(snapshot.low_24h, 2)} – ${fmtPrice(snapshot.high_24h, 2)}`
                : rangeLow != null && rangeHigh != null
                  ? `${fmtPrice(rangeLow, 2)} – ${fmtPrice(rangeHigh, 2)}`
                  : '—'
            }
            sub="最高 / 最低"
            mono={false}
          />
        </Card>
        <Card>
          <Stat
            label="24 小时成交量"
            value={fmtCompact(snapshot?.quote_volume_24h ?? null)}
            sub={snapshot?.volume_24h != null ? `${fmtCompact(snapshot.volume_24h)} 张合约` : '计价成交额'}
          />
        </Card>
        <Card>
          <Stat
            label="最近资金费率"
            value={fmtRate(snapshot?.last_funding_rate ?? funding.data?.summary.mean_rate ?? null, 4)}
            sub={
              snapshot?.next_funding_time
                ? `下次 ${fmtTime(snapshot.next_funding_time)}`
                : funding.data
                  ? `每 ${funding.data.summary.interval_hours} 小时结算`
                  : '—'
            }
          />
        </Card>
      </div>

      <Card>
        <CardHead
          title="价格走势"
          hint={
            last
              ? `${data?.count.toLocaleString()} 根 K 线 · ${fmtTime(data?.from)} → ${fmtTime(data?.to)}`
              : '正在加载本地 K 线'
          }
          right={
            <div className="flex items-center gap-2">
              <div className="flex overflow-hidden rounded-lg border border-line">
                {INTERVALS.map((item) => (
                  <button
                    key={item}
                    onClick={() => setSpan(item)}
                    className={`px-2.5 py-1.5 font-mono text-[10.5px] transition-colors ${
                      item === span
                        ? 'bg-elevated text-accent'
                        : 'text-muted hover:bg-elevated/60 hover:text-ink'
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={candles.reload}
                aria-label="刷新 K 线"
                className="hidden sm:inline-flex"
              >
                <RefreshCw size={12} />
              </Button>
            </div>
          }
        />
        {candles.error ? (
          <ErrorNote>{candles.error}</ErrorNote>
        ) : candles.loading && !data ? (
          <Skeleton className="h-[380px] w-full" />
        ) : data && data.candles.length ? (
          <>
            <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <span className="num text-[22px] font-semibold text-ink">{fmtPrice(last?.[4] ?? null)}</span>
              <span className={`num text-[12px] ${change !== null && change >= 0 ? 'text-up' : 'text-down'}`}>
                {fmtPct(change)} <span className="text-faint">区间 {span}</span>
              </span>
              <span className="num ml-auto text-[10.5px] text-faint">
                开 {fmtPrice(last?.[1] ?? null)} 高 {fmtPrice(last?.[2] ?? null)} 低 {fmtPrice(last?.[3] ?? null)} · 量{' '}
                {fmtCompact(last?.[5] ?? null)}
              </span>
            </div>
            {chartReady ? (
              <PriceChart candles={data.candles} height={400} />
            ) : (
              <Skeleton className="h-[400px] w-full" />
            )}
          </>
        ) : (
          <p className="py-16 text-center text-[12px] text-muted">该周期暂无 K 线。</p>
        )}
      </Card>

      <div ref={fundingRef} className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHead
            title="资金费率历史"
            hint={
              funding.data
                ? `${funding.data.summary.count} 次结算 · 每 ${funding.data.summary.interval_hours} 小时`
                : '正在加载资金费率结算'
            }
            right={
              funding.data ? (
                <Badge tone={funding.data.summary.annualized_pct >= 0 ? 'up' : 'down'}>
                  {fmtPct(funding.data.summary.annualized_pct)} 年化
                </Badge>
              ) : null
            }
          />
          {!fundingInView ? (
            <Skeleton className="h-[200px] w-full" />
          ) : funding.error ? (
            <ErrorNote>{funding.error}</ErrorNote>
          ) : funding.loading && !funding.data ? (
            <Skeleton className="h-[200px] w-full" />
          ) : funding.data?.points.length ? (
            chartReady ? (
              <FundingChart points={funding.data.points} height={220} />
            ) : (
              <Skeleton className="h-[200px] w-full" />
            )
          ) : (
            <p className="py-12 text-center text-[12px] text-muted">暂无资金费率数据。</p>
          )}
        </Card>

        <Card>
          <CardHead title="套息快照" hint="符号约定：正值表示多头向空头支付。" />
          {!fundingInView ? (
            <Skeleton className="h-24 w-full" />
          ) : funding.data ? (
            <div className="grid grid-cols-2 gap-4">
              <Stat label="平均费率" value={fmtRate(funding.data.summary.mean_rate, 4)} />
              <Stat label="中位费率" value={fmtRate(funding.data.summary.median_rate, 4)} />
              <Stat
                label="正值占比"
                value={`${funding.data.summary.positive_pct.toFixed(1)}%`}
                sub="占结算次数"
              />
              <Stat
                label="年化"
                value={fmtPct(funding.data.summary.annualized_pct)}
                tone={funding.data.summary.annualized_pct}
              />
              <Stat label="结算周期" value={`${funding.data.summary.interval_hours} 小时`} />
              <Stat label="上次结算" value={timeAgo(funding.data.summary.last)} mono={false} />
            </div>
          ) : (
            <Skeleton className="h-24 w-full" />
          )}
        </Card>
      </div>
    </div>
  )
}
