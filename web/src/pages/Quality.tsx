import { RefreshCw } from 'lucide-react'
import { api, type DatasetQuality } from '../api'
import { Badge, Button, Card, CardHead, ErrorNote, Skeleton, Stat } from '../components/ui'
import { cx, fmtCompact, fmtDate, fmtMoney, fmtPct, fmtPrice, fmtTime, timeAgo } from '../format'
import { useFetch } from '../hooks'
import { useApp } from '../store'

function bytes(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

const CONTRACT_LABELS: Record<string, string> = {
  TRADIFI_PERPETUAL: 'TradFi 永续',
  PERPETUAL: '永续',
}

const UNDERLYING_LABELS: Record<string, string> = {
  EQUITY: '股票',
  INDEX: '指数',
  FX: '外汇',
  COMMODITY: '商品',
}

const SESSION_LABELS: Record<string, string> = {
  REGULAR: '常规',
  PRE_MARKET: '盘前',
  AFTER_MARKET: '盘后',
  NO_TRADING: '休市',
  UNKNOWN: '未知',
}

const MARKET_LABELS: Record<string, string> = {
  CN_EQUITY: '中国股票',
  HK_EQUITY: '港股',
  KR_EQUITY: '韩国股票',
  US_EQUITY: '美股',
  EQUITY: '股票',
  FX: '外汇',
  COMMODITY: '商品',
}

const labelOf = (map: Record<string, string>, value: string) => map[value] ?? value

interface Check {
  name: string
  state: 'pass' | 'warn' | 'fail'
  detail: string
}

function checks(quality: DatasetQuality): Check[] {
  const out: Check[] = []
  out.push({
    name: '时序索引',
    state: quality.out_of_order ? 'fail' : 'pass',
    detail: quality.out_of_order ? 'K 线时间未严格递增。' : 'K 线时间严格有序。',
  })
  out.push({
    name: '重复时间戳',
    state: quality.duplicate_timestamps ? 'fail' : 'pass',
    detail: quality.duplicate_timestamps
      ? `发现 ${quality.duplicate_timestamps} 个重复时间戳。`
      : '无重复分钟 K 线。',
  })
  out.push({
    name: 'OHLC 完整性',
    state: quality.bad_ohlc ? 'fail' : 'pass',
    detail: quality.bad_ohlc
      ? `${quality.bad_ohlc} 根 K 线不满足 high ≥ open/close ≥ low。`
      : '所有 K 线均满足 high ≥ open、close ≥ low。',
  })
  const coverage = quality.coverage_pct
  out.push({
    name: '覆盖',
    state: coverage === null ? 'warn' : coverage >= 99 ? 'pass' : coverage >= 95 ? 'warn' : 'fail',
    detail: coverage === null ? '无法计算覆盖率。' : `预期分钟数据中已有 ${coverage.toFixed(2)}%。`,
  })
  out.push({
    name: '缺口分布',
    state: quality.max_gap_minutes > 10 ? 'warn' : 'pass',
    detail: `${quality.gap_count} 个缺口 · 最长 ${fmtMoney(quality.max_gap_minutes, 0)} 分钟。`,
  })
  out.push({
    name: '资金费率节奏',
    state:
      quality.funding_median_interval_hours !== null &&
      Math.abs((quality.funding_median_interval_hours ?? 0) - 8) > 0.5
        ? 'warn'
        : 'pass',
    detail:
      quality.funding_median_interval_hours === null
        ? '无资金费率结算记录。'
        : `中位间隔 ${quality.funding_median_interval_hours.toFixed(1)} 小时 · 最长 ${fmtMoney(quality.funding_max_interval_hours ?? 0, 1)} 小时。`,
  })
  return out
}

const TONE = {
  pass: 'up',
  warn: 'warn',
  fail: 'down',
} as const

const LABEL = {
  pass: '通过',
  warn: '警告',
  fail: '失败',
} as const

export function Quality() {
  const { symbol } = useApp()
  const quality = useFetch(() => api.quality(symbol), [symbol])
  const data = quality.data

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[15px] font-semibold text-ink">{symbol} 数据集完整性</h1>
          <p className="mt-1 text-[11.5px] text-muted">
            本地 Parquet 审计。这里的缺口会在每次回放中变成隐性的成交假设。
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={quality.reload} loading={quality.loading}>
          <RefreshCw size={12} /> 重新扫描
        </Button>
      </div>

      {quality.error ? (
        <ErrorNote>{quality.error}</ErrorNote>
      ) : !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Card key={index}>
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-3 h-7 w-28" />
              </Card>
            ))}
          </div>
          <Card>
            <Skeleton className="h-[260px] w-full" />
          </Card>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <Stat
                label="分钟 K 线"
                value={data.bars.toLocaleString()}
                sub={`预期 ${data.expected_bars.toLocaleString()} 根`}
                large
              />
            </Card>
            <Card>
              <Stat
                label="覆盖"
                value={data.coverage_pct === null ? '—' : `${data.coverage_pct.toFixed(2)}%`}
                tone={data.coverage_pct === null ? undefined : data.coverage_pct >= 99 ? 1 : -1}
                sub={`缺失 ${data.missing_bars.toLocaleString()} 分钟`}
                large
              />
            </Card>
            <Card>
              <Stat
                label="最新收盘价"
                value={fmtPrice(data.last_close)}
                sub={`${fmtDate(data.start)} → ${fmtDate(data.end)}`}
                large
              />
            </Card>
            <Card>
              <Stat
                label="文件大小"
                value={bytes(data.bytes)}
                sub={`磁盘存储 ${fmtCompact(data.bars)} 行`}
                large
              />
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
            <Card>
              <CardHead
                title="完整性检查"
                hint="存在阻断性问题时，应先修复再信任回测结果。"
                right={<Badge tone="neutral">{data.symbol}</Badge>}
              />
              <div className="space-y-0">
                {checks(data).map((check) => (
                  <div
                    key={check.name}
                    className="flex items-start gap-3 border-t border-line-soft py-2.5 first:border-0 first:pt-0 last:pb-0"
                  >
                    <Badge tone={TONE[check.state]} className="mt-[1px] w-11 justify-center">
                      {LABEL[check.state]}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] text-ink">{check.name}</div>
                      <div className="mt-0.5 text-[10.5px] leading-relaxed text-faint">
                        {check.detail}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <CardHead title="价格与缺口" hint="连续合约分钟 K 线。" />
              <div className="grid grid-cols-2 gap-4">
                <Stat label="最低价" value={fmtPrice(data.price_min)} />
                <Stat label="最高价" value={fmtPrice(data.price_max)} />
                <Stat
                  label="中位缺口"
                  value={data.median_gap_minutes === null ? '—' : `${fmtMoney(data.median_gap_minutes, 1)} 分钟`}
                />
                <Stat
                  label="最大缺口"
                  value={`${fmtMoney(data.max_gap_minutes, 0)} 分钟`}
                  tone={data.max_gap_minutes > 10 ? -1 : undefined}
                />
                <Stat label="缺口数量" value={data.gap_count.toLocaleString()} />
                <Stat
                  label="零成交量"
                  value={fmtPct(data.zero_volume_pct, 2, false)}
                  tone={data.zero_volume_pct > 5 ? -1 : undefined}
                />
                <Stat label="异常 OHLC" value={data.bad_ohlc} tone={data.bad_ohlc ? -1 : undefined} />
                <Stat
                  label="重复"
                  value={data.duplicate_timestamps}
                  tone={data.duplicate_timestamps ? -1 : undefined}
                />
              </div>
              <div className="mt-4 space-y-2 border-t border-line-soft pt-3 text-[10.5px] leading-relaxed text-faint">
                <div className="flex justify-between gap-3">
                  <span>首根 K 线</span>
                  <span className="font-mono text-muted">{fmtTime(data.start)}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span>末根 K 线</span>
                  <span className="font-mono text-muted">{fmtTime(data.end)}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span>数据新鲜度</span>
                  <span className="font-mono text-muted">{timeAgo(data.end)}</span>
                </div>
              </div>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card>
              <CardHead title="合约" hint="过滤器参数来自交易所元数据。" />
              <div className="space-y-2 text-[11.5px]">
                {[
                  ['类型', data.contract.contract_type ? labelOf(CONTRACT_LABELS, data.contract.contract_type) : '—'],
                  ['标的类型', data.contract.underlying_type ? labelOf(UNDERLYING_LABELS, data.contract.underlying_type) : '—'],
                  ['上线日期', data.contract.onboard ? fmtDate(data.contract.onboard) : '—'],
                  [
                    '资金费率间隔',
                    data.contract.funding_interval_hours === null
                      ? '—'
                      : `${data.contract.funding_interval_hours} 小时`,
                  ],
                  ['最小价格变动', String(data.filters.tick_size)],
                  ['数量步长', String(data.filters.step_size)],
                  ['最小名义价值', `$${fmtMoney(data.filters.min_notional, 0)}`],
                  ['最大挂单数', String(data.filters.max_orders)],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between gap-3 border-b border-line-soft pb-2 last:border-0 last:pb-0">
                    <span className="min-w-0 truncate text-muted">{label}</span>
                    <span className="num shrink-0 text-ink">{value}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <CardHead title="资金费率数据" hint="结算记录来自资金费率归档。" />
              <div className="grid grid-cols-2 gap-4">
                <Stat label="结算次数" value={data.funding_settlements.toLocaleString()} />
                <Stat
                  label="中位间隔"
                  value={
                    data.funding_median_interval_hours === null
                      ? '—'
                      : `${data.funding_median_interval_hours.toFixed(1)} 小时`
                  }
                />
                <Stat
                  label="最大间隔"
                  value={
                    data.funding_max_interval_hours === null
                      ? '—'
                      : `${data.funding_max_interval_hours.toFixed(1)} 小时`
                  }
                  tone={
                    data.funding_max_interval_hours !== null && data.funding_max_interval_hours > 9
                      ? -1
                      : undefined
                  }
                />
                <Stat label="最近结算" value={data.last_funding ? timeAgo(data.last_funding) : '—'} mono={false} />
              </div>
              <p className="mt-4 border-t border-line-soft pt-3 text-[10.5px] leading-relaxed text-faint">
                资金费率以现金形式计入权益曲线。结算过于稀疏会在月份之间形成隐性的持有成本漂移。
              </p>
            </Card>

            <Card>
              <CardHead
                title="交易时间表"
                hint={`${data.schedule.sessions} 个交易时段 · ${data.schedule.markets.map((m) => labelOf(MARKET_LABELS, m)).join('、') || '未知市场'}`}
              />
              {data.schedule.no_trading_recent.length ? (
                <div className="space-y-2">
                  {data.schedule.no_trading_recent.slice(0, 6).map((session, index) => (
                    <div
                      key={`${session.start}-${index}`}
                      className="rounded-lg border border-line-soft bg-[#12151a] px-3 py-2 text-[10.5px]"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-muted">{labelOf(SESSION_LABELS, session.type)}</span>
                        <span className="text-faint">{labelOf(MARKET_LABELS, session.market)}</span>
                      </div>
                      <div className="mt-1 font-mono text-[10px] text-faint">
                        {fmtTime(session.start)} → {fmtTime(session.end)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="py-8 text-center text-[11.5px] text-muted">
                  近期无休市时段。
                </p>
              )}
              <p className={cx('mt-3 text-[10px] leading-relaxed text-faint')}>
                加密合约连续交易；此处时段仅反映交易所维护窗口。
              </p>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
