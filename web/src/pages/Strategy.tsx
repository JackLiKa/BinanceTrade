import { useMemo, useState } from 'react'
import { ArrowRight, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Badge, Button, Card, CardHead, Stat } from '../components/ui'
import { ParamsForm } from '../components/inputs'
import { fmtMoney, fmtPct, fmtPrice, fmtQty } from '../format'
import { buildPreview, loadParams, saveParams, type GridParams } from '../params'
import { navigate } from '../router'
import { useApp } from '../store'

export function Strategy() {
  const { snapshot, symbol } = useApp()
  const [params, setParams] = useState<GridParams>(() => loadParams())
  const price = snapshot?.mark_price ?? null
  const preview = useMemo(() => buildPreview(price, params), [price, params])

  const update = (next: GridParams) => {
    setParams(next)
    saveParams(next)
  }

  const feeRoundTripPct = (params.maker_fee * 2 + params.slip_bp / 10_000) * 100
  const spacingPct = params.spacing_bp / 100
  const warnings: string[] = []
  if (params.leverage > 1) warnings.push('杠杆高于 1 倍时，行情快速波动可能导致库存被强制平仓；回放成交仅为近似。')
  if (spacingPct < feeRoundTripPct) warnings.push('网格间距小于往返成本，每完成一轮都会亏损。')
  if (params.stop_dd === null) warnings.push('未设置回撤保护：持续单边趋势会让阶梯无限延伸。')
  if (params.levels > 200) warnings.push('层数超过 200 会拖慢引擎，并接近交易所挂单上限。')
  const ok = warnings.length === 0

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
      <div className="space-y-4">
        <Card>
          <CardHead
            title="网格参数"
            hint="预览与回测实验室共用。"
            right={<Badge tone="accent">本地</Badge>}
          />
          <ParamsForm
            value={params}
            onChange={update}
            footer={
              <Button
                variant="primary"
                className="w-full"
                onClick={() => {
                  saveParams(params)
                  navigate('backtest')
                }}
              >
                用于回测实验室 <ArrowRight size={14} />
              </Button>
            }
          />
        </Card>

        <Card>
          <CardHead title="参数校验" hint="运行回测前的静态检查。" />
          {ok ? (
            <div className="flex items-start gap-2.5 text-[11.5px] leading-relaxed text-up">
              <CheckCircle2 size={14} className="mt-[1px]" />
              网格间距已覆盖往返成本，杠杆处于研究范围之内。
            </div>
          ) : (
            <ul className="space-y-2">
              {warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2.5 text-[11.5px] leading-relaxed text-[#f0b90b]">
                  <AlertTriangle size={13} className="mt-[2px] shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card>
            <Stat label="锚定价格" value={fmtPrice(preview?.price ?? null)} sub={symbol} large />
          </Card>
          <Card>
            <Stat
              label="总敞口"
              value={preview ? fmtMoney(preview.grossNotional, 0) : '—'}
              sub={preview ? `每层 ${fmtMoney(preview.notionalPerLevel, 0)}` : '—'}
              large
            />
          </Card>
          <Card>
            <Stat
              label="总杠杆"
              value={preview ? `${preview.grossLeverage.toFixed(2)}x` : '—'}
              tone={preview && preview.grossLeverage > 1 ? -1 : undefined}
              sub={preview ? `每层 ${fmtQty(preview.qtyPerLevel, 4)} ${symbol.replace('USDT', '')}` : '—'}
              large
            />
          </Card>
          <Card>
            <Stat
              label="单轮净收益"
              value={preview ? `${preview.netProfitPerGrid.toFixed(3)}%` : '—'}
              tone={preview && preview.netProfitPerGrid > 0 ? 1 : -1}
              sub={preview ? `手续费 ${preview.roundTripFees.toFixed(3)}% + 滑点` : '—'}
              large
            />
          </Card>
        </div>

        <Card>
          <CardHead
            title="价格区间"
            hint="订单围绕当前标记价格挂出；重新锚定会重建阶梯。"
            right={
              preview ? (
                <span className="font-mono text-[10.5px] text-faint">
                  间距 {preview.stepPct.toFixed(2)}%
                </span>
              ) : null
            }
          />
          {preview ? (
            <div className="space-y-4">
              <div className="relative h-14 overflow-hidden rounded-lg border border-line-soft bg-[#12151a]">
                <div className="absolute inset-y-0 left-0 w-full">
                  <div
                    className="absolute inset-y-0 bg-accent/8"
                    style={{
                      left: `${((preview.lower - preview.lower) / (preview.upper - preview.lower)) * 100}%`,
                      width: '100%',
                    }}
                  />
                  <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
                  <div
                    className="absolute inset-y-1 w-0.5 bg-accent"
                    style={{
                      left: `${((preview.price - preview.lower) / (preview.upper - preview.lower)) * 100}%`,
                    }}
                  />
                  <div
                    className="absolute inset-y-1 w-px bg-down/70"
                    style={{
                      left: `${Math.max(0, Math.min(100, ((preview.stopPrice ?? preview.lower) - preview.lower) / (preview.upper - preview.lower) * 100))}%`,
                    }}
                  />
                </div>
                <div className="absolute inset-x-3 top-2 flex justify-between font-mono text-[10px] text-faint">
                  <span>{fmtPrice(preview.lower)}</span>
                  <span className="text-accent">{fmtPrice(preview.price)}</span>
                  <span>{fmtPrice(preview.upper)}</span>
                </div>
                <div className="absolute inset-x-3 bottom-2 flex justify-between font-mono text-[9.5px] text-faint">
                  <span>下限</span>
                  <span>{preview.stopPrice ? `止损 ≈ ${fmtPrice(preview.stopPrice)}` : '无止损'}</span>
                  <span>上限</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="层数" value={params.levels} />
                <Stat label="止损风险" value={fmtMoney(preview.maxLossToStop, 0)} sub="资金 × 止损" />
                <Stat label="区间宽度" value={`${(((preview.upper - preview.lower) / preview.price) * 100).toFixed(2)}%`} />
                <Stat label="单轮收益" value={`${preview.gridYieldPct.toFixed(3)}%`} sub="每轮全部层数" />
              </div>
            </div>
          ) : (
            <p className="py-10 text-center text-[12px] text-muted">
              正在等待标记价格。行情源恢复后将自动回退到数据集。
            </p>
          )}
        </Card>

        <Card pad={false}>
          <div className="flex items-center justify-between px-5 pt-5">
            <div>
              <h2 className="text-[13px] font-semibold text-ink">网格阶梯预览</h2>
              <p className="mt-1 text-[11px] text-muted">
                {preview
                  ? `${preview.levels.filter((level) => level.side === 'BUY').length} 买 · ${preview.levels.filter((level) => level.side === 'SELL').length} 卖`
                  : '暂无标记价格'}
              </p>
            </div>
            <Badge tone="neutral">post-only</Badge>
          </div>
          <div className="mt-3 max-h-[420px] overflow-y-auto border-t border-line-soft">
            <table className="w-full text-[11.5px]">
              <thead className="sticky top-0 bg-panel">
                <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                  <th className="px-5 py-2 font-medium">方向</th>
                  <th className="py-2 text-right font-medium">价格</th>
                  <th className="py-2 text-right font-medium">距离</th>
                  <th className="py-2 text-right font-medium">数量</th>
                  <th className="px-5 py-2 text-right font-medium">名义价值</th>
                </tr>
              </thead>
              <tbody>
                {preview?.levels.map((level) => (
                  <tr key={level.price} className="row-hover border-t border-line-soft/70">
                    <td className="px-5 py-1.5">
                      <span className={level.side === 'BUY' ? 'text-up' : 'text-down'}>{level.side === 'BUY' ? '买入' : '卖出'}</span>
                    </td>
                    <td className="py-1.5 text-right font-mono text-ink">{fmtPrice(level.price)}</td>
                    <td className="py-1.5 text-right font-mono text-muted">{fmtPct(level.distancePct, 2)}</td>
                    <td className="py-1.5 text-right font-mono text-muted">{fmtQty(level.qty, 4)}</td>
                    <td className="px-5 py-1.5 text-right font-mono text-muted">{fmtMoney(level.notional, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  )
}
