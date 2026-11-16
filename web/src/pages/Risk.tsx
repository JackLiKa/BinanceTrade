import { useState } from 'react'
import { AlertTriangle, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import { ParamsForm } from '../components/inputs'
import { Badge, Button, Card, CardHead, ErrorNote, Skeleton, Stat, Toggle } from '../components/ui'
import { cx, fmtDate, fmtMoney, fmtPct, fmtQty, fmtTime, timeAgo } from '../format'
import { statusTone, useFetch } from '../hooks'
import { loadParams, type GridParams } from '../params'
import { useApp } from '../store'
import { auditLabel } from '../labels'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  canceled: '已取消',
}

const REJECTION_LABEL: Record<string, string> = {
  qty_nonpositive: '数量非正',
  bad_price: '价格无效',
  price_deviation: '价格偏离',
  reduce_only_flat: '无持仓可减',
  reduce_only_flip: '减仓越过零轴',
  max_position: '超过最大持仓',
  max_order_notional: '超过单笔名义上限',
  max_gross_notional: '超过总名义上限',
  max_open_orders: '超过挂单上限',
  order_rate: '超过提交频率上限',
  missing_tag: '缺少标签',
  duplicate_tag: '标签重复',
  exchange_reject: '交易所拒单',
  rejected: '已拒单',
}

export function Risk() {
  const { symbol, killSwitch, setKillSwitch, toast } = useApp()
  const [params, setParams] = useState<GridParams>(() => loadParams())
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

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
    { pollMs: 20_000 },
  )
  const audit = useFetch(() => api.audit(50), [], { pollMs: 30_000 })

  const data = risk.data
  const limits = data?.limits
  const grid = data?.grid ?? {
    spacing_bp: params.spacing_bp,
    levels: params.levels,
    leverage: params.leverage,
  }

  const toggleKill = async (engaged: boolean) => {
    setBusy(true)
    try {
      await setKillSwitch(engaged)
      setConfirming(false)
    } catch (err) {
      toast(err instanceof Error ? err.message : '紧急停止操作失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  const limitRows = limits
    ? [
        {
          label: '最大持仓数量',
          value: fmtQty(limits.max_position_qty, 4),
          formula: `size × levels × 1.05`,
          note: '单边持仓的硬性上限。',
        },
        {
          label: '单笔最大名义',
          value: `$${fmtMoney(limits.max_order_notional, 0)}`,
          formula: `size × price × 3`,
          note: '拒绝超出上限的单笔委托。',
        },
        {
          label: '最大总名义',
          value: `$${fmtMoney(limits.max_gross_notional, 0)}`,
          formula: `capital × leverage × 1.3`,
          note: '双边合计的账面敞口。',
        },
        {
          label: '最大挂单数',
          value: String(limits.max_open_orders),
          formula: `max(levels × 2, 10)`,
          note: '交易所侧未完成订单上限。',
        },
        {
          label: '每分钟最大提交数',
          value: String(limits.max_submits_per_minute),
          formula: '固定 120',
          note: '限流用于保护交易所与 API。',
        },
        {
          label: '最大价格偏离',
          value: `${fmtMoney(limits.max_price_deviation_bp, 0)} bp`,
          formula: `spacing × (levels + 2) × 2`,
          note: '拒绝偏离标记价格过远的档位。',
        },
      ]
    : []

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHead
              title="紧急停止"
              hint="阻止新的模拟委托，并将新研究标记为参考。"
              right={
                <Badge tone={killSwitch ? 'down' : 'up'}>{killSwitch ? '已触发' : '已就绪'}</Badge>
              }
            />
            <div
              className={cx(
                'rounded-xl border p-4',
                killSwitch ? 'border-down/35 bg-down/8' : 'border-line-soft bg-[#12151a]',
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cx(
                    'grid h-9 w-9 shrink-0 place-items-center rounded-lg border',
                    killSwitch
                      ? 'border-down/40 bg-down/10 text-down'
                      : 'border-up/30 bg-up/10 text-up',
                  )}
                >
                  {killSwitch ? <ShieldAlert size={17} /> : <ShieldCheck size={17} />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium text-ink">
                    {killSwitch ? '交易已暂停' : '交易允许'}
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted">
                    {killSwitch
                      ? '解除紧急停止前，交易台不会提交新委托。已有研究任务不受影响。'
                      : '允许研究与模拟委托。无论此开关状态如何，实盘交易保持锁定。'}
                  </p>
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-line-soft pt-3">
                <Toggle
                  checked={killSwitch}
                  onChange={(next) => {
                    if (next) setConfirming(true)
                    else void toggleKill(false)
                  }}
                  label={killSwitch ? '解除' : '触发'}
                  disabled={busy}
                />
                {confirming ? (
                  <div className="flex items-center gap-1.5">
                    <Button variant="danger" size="sm" loading={busy} onClick={() => void toggleKill(true)}>
                      确认暂停
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                      取消
                    </Button>
                  </div>
                ) : null}
              </div>
            </div>
          </Card>

          <Card>
            <CardHead title="限额参数" hint="限额依据已保存的网格配置。" />
            <ParamsForm value={params} onChange={setParams} compact />
          </Card>
        </div>

        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Card>
              <Stat
                label="网格"
                value={`${grid.spacing_bp}bp / ${grid.levels} 层`}
                sub={`${grid.leverage} 倍杠杆`}
                large
                mono={false}
              />
            </Card>
            <Card>
              <Stat
                label="本金"
                value={`$${fmtMoney(params.capital, 0)}`}
                sub={`止损 ${params.stop_dd === null ? '无' : fmtPct(params.stop_dd * 100, 1, false)}`}
                large
              />
            </Card>
            <Card>
              <Stat
                label="最大总名义"
                value={limits ? `$${fmtMoney(limits.max_gross_notional, 0)}` : '—'}
                sub="压力上限"
                large
              />
            </Card>
            <Card>
              <Stat
                label="最近运行"
                value={
                  data?.latest_run
                    ? typeof data.latest_run.summary?.halted === 'boolean' && data.latest_run.summary.halted
                      ? '已暂停'
                      : '正常'
                    : '—'
                }
                tone={data?.latest_run?.summary?.halted === true ? -1 : 1}
                sub={data?.latest_run ? timeAgo(data.latest_run.created_at) : '暂无运行记录'}
                large
                mono={false}
              />
            </Card>
          </div>

          <Card pad={false}>
            <div className="px-5 pt-5">
              <h2 className="text-[13px] font-semibold text-ink">生效限额</h2>
              <p className="mt-1 text-[11px] text-muted">
                由服务端根据本金、杠杆与网格形态计算。
              </p>
            </div>
            {risk.error ? (
              <div className="p-5">
                <ErrorNote>{risk.error}</ErrorNote>
              </div>
            ) : limits ? (
              <div className="mt-4 overflow-x-auto border-t border-line-soft">
                <table className="w-full text-[11.5px]">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                      <th className="px-5 py-2 font-medium">限额</th>
                      <th className="py-2 text-right font-medium">数值</th>
                      <th className="px-5 py-2 font-medium">推导</th>
                    </tr>
                  </thead>
                  <tbody>
                    {limitRows.map((row) => (
                      <tr key={row.label} className="border-t border-line-soft/70">
                        <td className="px-5 py-2.5">
                          <div className="text-ink">{row.label}</div>
                          <div className="mt-0.5 text-[10.5px] text-faint">{row.note}</div>
                        </td>
                        <td className="py-2.5 text-right font-mono text-ink">{row.value}</td>
                        <td className="px-5 py-2.5 font-mono text-[10.5px] text-muted">{row.formula}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-5">
                <Skeleton className="h-48 w-full" />
              </div>
            )}
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHead
                title="最近拒单"
                hint="来自最新的回放产物。"
                right={
                  data?.latest_run ? (
                    <Badge tone={statusTone(data.latest_run.status)}>
                      {STATUS_LABEL[data.latest_run.status] ?? data.latest_run.status}
                    </Badge>
                  ) : null
                }
              />
              {data?.rejections.length ? (
                <div className="space-y-2">
                  {data.rejections.map((item) => (
                    <div key={item.reason} className="flex items-center justify-between gap-3 text-[11.5px]">
                      <span className="min-w-0 truncate font-mono text-muted">
                        {REJECTION_LABEL[item.reason] ?? item.reason}
                      </span>
                      <span className="num shrink-0 text-ink">{item.count}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex items-start gap-2.5 text-[11.5px] leading-relaxed text-muted">
                  <AlertTriangle size={13} className="mt-[2px] shrink-0 text-faint" />
                  {data?.latest_run
                    ? '最新运行中没有被拒绝的委托。'
                    : '运行一次回放以生成拒单诊断。'}
                </div>
              )}
            </Card>

            <Card>
              <CardHead title="保护行为" hint="触及止损后的处理方式。" />
              <ul className="space-y-2.5 text-[11.5px] leading-relaxed text-muted">
                <li>
                  回撤以起始本金为基准，而非权益峰值。
                </li>
                <li>
                  触发后，引擎会撤销挂单、以市价平仓，并将该次运行标记为已暂停。
                </li>
                <li>
                  被暂停的月份不计入滚动推进复利，但仍会出现在分段表中。
                </li>
                <li>
                  研究运行不会触及实盘账户——当前构建没有实盘适配器。
                </li>
              </ul>
            </Card>
          </div>
        </div>
      </div>

      <Card pad={false}>
        <div className="flex items-center justify-between px-5 pt-5">
          <div>
            <h2 className="text-[13px] font-semibold text-ink">审计日志</h2>
            <p className="mt-1 text-[11px] text-muted">
              登录、紧急停止变更、运行记录与设置写入。
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={audit.reload}>
            刷新
          </Button>
        </div>
        <div className="mt-3 max-h-[380px] overflow-auto border-t border-line-soft">
          {audit.error ? (
            <div className="p-5">
              <ErrorNote>{audit.error}</ErrorNote>
            </div>
          ) : audit.data?.entries.length ? (
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">时间</th>
                  <th className="py-2 font-medium">操作者</th>
                  <th className="py-2 font-medium">操作</th>
                  <th className="px-5 py-2 font-medium">详情</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.entries.map((entry) => (
                  <tr key={entry.id} className="row-hover border-t border-line-soft/70">
                    <td className="whitespace-nowrap px-5 py-1.5 font-mono text-faint">
                      {fmtTime(entry.ts)}
                    </td>
                    <td className="py-1.5 font-mono text-muted">{entry.actor}</td>
                    <td className="py-1.5">
                      <Badge tone={entry.action.includes('kill') ? 'down' : 'neutral'}>
                        {auditLabel(entry.action)}
                      </Badge>
                    </td>
                    <td className="max-w-[520px] truncate px-5 py-1.5 font-mono text-[10.5px] text-muted">
                      {entry.detail ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="px-5 py-10 text-center text-[12px] text-muted">暂无审计记录。</p>
          )}
        </div>
      </Card>
    </div>
  )
}
