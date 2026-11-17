import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, type BinanceFillView, type BinanceOrderView, type BinancePositionView } from '../api'
import { Badge, Button, Card, CardHead, ErrorNote, Skeleton } from '../components/ui'
import { useFetch } from '../hooks'

function num(value: string | number | null | undefined): number {
  const parsed = typeof value === 'number' ? value : Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function money(value: string | number | null | undefined, digits = 4): string {
  return num(value).toFixed(digits)
}

function sizeText(value: string | number | null | undefined): string {
  const parsed = num(value)
  return parsed === 0 ? '0' : parsed.toFixed(Math.abs(parsed) < 1 ? 6 : 4)
}

function stamp(ms: number | undefined): string {
  if (!ms) return '—'
  return new Date(ms).toLocaleString('zh-CN', { hour12: false })
}

export function Binance() {
  const [symbol] = useState<string | undefined>(undefined)
  const state = useFetch(() => api.binanceState(symbol), [symbol], { pollMs: 15000 })
  const data = state.data
  const health = data?.health
  const account = data?.account?.account
  const positions = (data?.positions?.positions ?? []) as BinancePositionView[]
  const orders = (data?.orders?.orders ?? []) as BinanceOrderView[]
  const fills = (data?.fills?.fills ?? []) as BinanceFillView[]
  const history = (data?.history?.orders ?? []) as BinanceOrderView[]
  const alerts = data?.alerts?.alerts ?? []
  const criticalAlerts = alerts.filter((row) => row.level === 'critical')
  const warnAlerts = alerts.filter((row) => row.level === 'warn')
  const errors = data?.errors ?? {}
  const offline = !health || health.reachable === false

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[15px] font-semibold tracking-[0.01em] text-ink">Binance 执行节点</h1>
          <p className="mt-1 text-[11.5px] text-faint">
            东京节点 · 只读视图 · 经 WireGuard 隧道访问
            {data?.node_url ? ` · ${data.node_url}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {health ? (
            <>
              <Badge tone={offline ? 'warn' : 'up'}>{offline ? '节点不可达' : '节点在线'}</Badge>
              <Badge tone={health.configured ? 'info' : 'warn'}>
                {health.configured ? '已配置 Key' : '未配置 Key'}
              </Badge>
              <Badge tone={health.trading_enabled && !health.kill_switch ? 'warn' : 'neutral'}>
                {health.kill_switch
                  ? '写锁：KILL 在位'
                  : health.trading_enabled
                    ? '写锁：已开启（谨慎）'
                    : '写锁：TRADING=0'}
              </Badge>
              <Badge tone="neutral">对时 {health.server_offset_ms} ms</Badge>
            </>
          ) : null}
          <Button onClick={state.reload} disabled={state.loading}>
            <RefreshCw size={14} className={state.loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        </div>
      </div>

      {state.error ? <ErrorNote>{state.error}</ErrorNote> : null}
      {!state.error && data && Object.keys(errors).length > 0 ? (
        <ErrorNote>
          部分数据读取失败：
          {Object.entries(errors)
            .map(([key, msg]) => `${key}: ${msg}`)
            .join('；')}
        </ErrorNote>
      ) : null}

      {criticalAlerts.length > 0 ? (
        <ErrorNote>
          对账告警（critical）：{criticalAlerts.slice(0, 3).map((row) => row.message).join('；')}
        </ErrorNote>
      ) : warnAlerts.length > 0 ? (
        <ErrorNote>
          对账告警（warn）：{warnAlerts.slice(0, 3).map((row) => row.message).join('；')}
        </ErrorNote>
      ) : null}

      {state.loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <Card key={index}>
              <Skeleton className="h-16 w-full" />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card>
            <div className="text-[11px] uppercase tracking-[0.14em] text-faint">钱包余额 (USDT)</div>
            <div className="mt-2 font-mono text-[22px] text-ink">
              {account ? money(account.totalWalletBalance, 4) : '—'}
            </div>
            <div className="mt-1 text-[11px] text-faint">
              可用 {account ? money(account.availableBalance, 4) : '—'}
            </div>
          </Card>
          <Card>
            <div className="text-[11px] uppercase tracking-[0.14em] text-faint">未实现盈亏 (USDT)</div>
            <div
              className={`mt-2 font-mono text-[22px] ${
                num(account?.totalUnrealizedProfit) >= 0 ? 'text-up' : 'text-down'
              }`}
            >
              {account ? money(account.totalUnrealizedProfit, 4) : '—'}
            </div>
            <div className="mt-1 text-[11px] text-faint">持仓保证金 {account ? money(account.totalPositionInitialMargin, 4) : '—'}</div>
          </Card>
          <Card>
            <div className="text-[11px] uppercase tracking-[0.14em] text-faint">持仓 / 挂单</div>
            <div className="mt-2 font-mono text-[22px] text-ink">
              {positions.length} / {orders.length}
            </div>
            <div className="mt-1 text-[11px] text-faint">
              保证金模式 {account?.multiAssetsMargin ? '多资产' : '单资产'} · 费率档 {account?.feeTier ?? '—'}
            </div>
          </Card>
          <Card>
            <div className="text-[11px] uppercase tracking-[0.14em] text-faint">节点状态</div>
            <div className="mt-2 font-mono text-[22px] text-ink">{offline ? 'OFFLINE' : 'ONLINE'}</div>
            <div className="mt-1 text-[11px] text-faint">
              {health?.base_url ?? '—'} · {health?.position_mode ?? 'auto'}
              {health?.dual_side_position != null ? (health.dual_side_position ? '（双边持仓）' : '（单向持仓）') : ''}
            </div>
          </Card>
        </div>
      )}

      <Card>
        <CardHead
          title="持仓"
          hint={`${positions.length} 个非零持仓`}
          right={<span className="text-[11px] text-faint">来自节点 /positions</span>}
        />
        {positions.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-faint">当前没有持仓</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[12px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">合约</th>
                  <th className="py-2 pr-3">方向</th>
                  <th className="py-2 pr-3 text-right">数量</th>
                  <th className="py-2 pr-3 text-right">开仓价</th>
                  <th className="py-2 pr-3 text-right">标记价</th>
                  <th className="py-2 pr-3 text-right">未实现</th>
                  <th className="py-2 pr-3 text-right">杠杆</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((row) => (
                  <tr key={`${row.symbol}-${row.positionSide ?? 'BOTH'}`} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3 font-mono text-ink">{row.symbol}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={num(row.positionAmt) >= 0 ? 'up' : 'down'}>
                        {row.positionSide ?? (num(row.positionAmt) >= 0 ? 'LONG' : 'SHORT')}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.positionAmt)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{money(row.entryPrice, 6)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{money(row.markPrice, 6)}</td>
                    <td
                      className={`py-2 pr-3 text-right font-mono ${
                        num(row.unRealizedProfit) >= 0 ? 'text-up' : 'text-down'
                      }`}
                    >
                      {money(row.unRealizedProfit, 4)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">{row.leverage ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="挂单"
          hint={`${orders.length} 个未成交订单`}
          right={<span className="text-[11px] text-faint">来自节点 /open_orders</span>}
        />
        {orders.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-faint">当前没有挂单</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-[12px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">动作</th>
                  <th className="py-2 pr-3">单号</th>
                  <th className="py-2 pr-3">合约</th>
                  <th className="py-2 pr-3">方向</th>
                  <th className="py-2 pr-3">类型</th>
                  <th className="py-2 pr-3 text-right">价格</th>
                  <th className="py-2 pr-3 text-right">数量</th>
                  <th className="py-2 pr-3 text-right">已成交</th>
                  <th className="py-2 pr-3">状态</th>
                  <th className="py-2 pr-3">下单时间</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((row) => (
                  <tr key={row.orderId} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3">
                      <Badge tone={row.action?.startsWith('OPEN') ? 'info' : 'warn'}>
                        {row.actionLabel ?? row.action ?? row.side}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-faint">
                      {row.orderId}
                      {row.clientOrderId ? <div className="truncate">{row.clientOrderId}</div> : null}
                    </td>
                    <td className="py-2 pr-3 font-mono text-ink">{row.symbol}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={row.side === 'BUY' ? 'up' : 'down'}>
                        {row.side}
                        {row.positionSide ? ` · ${row.positionSide}` : ''}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3">{row.type}</td>
                    <td className="py-2 pr-3 text-right font-mono">{money(row.price, 6)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.origQty)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.executedQty)}</td>
                    <td className="py-2 pr-3">{row.status}</td>
                    <td className="py-2 pr-3 text-[11px] text-faint">{stamp(row.time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="成交明细"
          hint={`最近 ${fills.length} 笔成交`}
          right={<span className="text-[11px] text-faint">来自节点 /fills（userTrades）</span>}
        />
        {fills.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-faint">暂无成交</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-[12px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">动作</th>
                  <th className="py-2 pr-3">单号</th>
                  <th className="py-2 pr-3">合约</th>
                  <th className="py-2 pr-3">方向</th>
                  <th className="py-2 pr-3 text-right">价格</th>
                  <th className="py-2 pr-3 text-right">数量</th>
                  <th className="py-2 pr-3 text-right">名义</th>
                  <th className="py-2 pr-3 text-right">手续费</th>
                  <th className="py-2 pr-3 text-right">费率</th>
                  <th className="py-2 pr-3 text-right">已实现盈亏</th>
                  <th className="py-2 pr-3">时间</th>
                </tr>
              </thead>
              <tbody>
                {fills.map((row, index) => (
                  <tr key={`${row.id ?? row.orderId}-${index}`} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3">
                      <Badge tone={row.action?.startsWith('OPEN') ? 'info' : 'warn'}>
                        {row.actionLabel ?? row.action ?? row.side}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-faint">{row.orderId ?? '—'}</td>
                    <td className="py-2 pr-3 font-mono text-ink">{row.symbol}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={row.side === 'BUY' ? 'up' : 'down'}>{row.side}</Badge>
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">{money(row.price, 6)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.qty)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{row.notional != null ? money(row.notional, 4) : '—'}</td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {row.commission ?? '—'}
                      {row.commissionAsset ? ` ${row.commissionAsset}` : ''}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">{row.feeBp != null ? `${row.feeBp} bp` : '—'}</td>
                    <td
                      className={`py-2 pr-3 text-right font-mono ${num(row.realizedPnl) >= 0 ? 'text-up' : 'text-down'}`}
                    >
                      {row.realizedPnl != null ? money(row.realizedPnl, 4) : '—'}
                    </td>
                    <td className="py-2 pr-3 text-[11px] text-faint">{stamp(row.time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="历史订单"
          hint={`最近 ${history.length} 条`}
          right={<span className="text-[11px] text-faint">来自节点 /orders（allOrders）</span>}
        />
        {history.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-faint">暂无历史订单</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[12px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">动作</th>
                  <th className="py-2 pr-3">单号</th>
                  <th className="py-2 pr-3">合约</th>
                  <th className="py-2 pr-3">类型</th>
                  <th className="py-2 pr-3 text-right">价格</th>
                  <th className="py-2 pr-3 text-right">数量</th>
                  <th className="py-2 pr-3 text-right">成交</th>
                  <th className="py-2 pr-3">状态</th>
                  <th className="py-2 pr-3">时间</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.orderId} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3">
                      <Badge tone={row.action?.startsWith('OPEN') ? 'info' : 'warn'}>
                        {row.actionLabel ?? row.action ?? row.side}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono text-[11px] text-faint">
                      {row.orderId}
                      {row.clientOrderId ? <div className="truncate">{row.clientOrderId}</div> : null}
                    </td>
                    <td className="py-2 pr-3 font-mono text-ink">{row.symbol}</td>
                    <td className="py-2 pr-3">{row.type}</td>
                    <td className="py-2 pr-3 text-right font-mono">{money(row.price, 6)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.origQty)}</td>
                    <td className="py-2 pr-3 text-right font-mono">{sizeText(row.executedQty)}</td>
                    <td className="py-2 pr-3">{row.status}</td>
                    <td className="py-2 pr-3 text-[11px] text-faint">{stamp(row.time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="对账与监控"
          hint="节点每 15s 拉取挂单/持仓，与本地账本比对；critical 会自动挂 KILL 开关"
          right={<Badge tone={criticalAlerts.length > 0 ? 'down' : warnAlerts.length > 0 ? 'warn' : 'up'}>
            {criticalAlerts.length > 0 ? `${criticalAlerts.length} 条 critical` : warnAlerts.length > 0 ? `${warnAlerts.length} 条 warn` : '全部正常'}
          </Badge>}
        />
        {alerts.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-faint">最近没有对账告警</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[12px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint">
                <tr className="border-b border-line-soft">
                  <th className="py-2 pr-3">时间</th>
                  <th className="py-2 pr-3">级别</th>
                  <th className="py-2 pr-3">类型</th>
                  <th className="py-2 pr-3">说明</th>
                </tr>
              </thead>
              <tbody>
                {alerts.slice(0, 10).map((row, index) => (
                  <tr key={`${row.ts}-${index}`} className="border-b border-line-soft/60">
                    <td className="py-2 pr-3 text-[11px] text-faint">{stamp(row.ts * 1000)}</td>
                    <td className="py-2 pr-3">
                      <Badge tone={row.level === 'critical' ? 'down' : row.level === 'warn' ? 'warn' : 'neutral'}>
                        {row.level}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono">{row.kind}</td>
                    <td className="py-2 pr-3">{row.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHead
          title="成本模型（计划值）"
          hint="来自节点 BINANCE_*_FEE_BP / SLIPPAGE_BP 配置；实际费率以成交明细里的 commission 为准"
        />
        {health?.cost ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-faint">maker 往返</div>
              <div className="mt-1 font-mono text-[16px] text-ink">
                {num(health.cost.round_trip_maker_bp).toFixed(2)} bp
              </div>
              <div className="text-[11px] text-faint">
                费率 {num(health.cost.maker_fee_bp).toFixed(2)} bp × 2 + 滑点 2×
                {num(health.cost.slippage_bp).toFixed(2)} bp
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-faint">taker 往返</div>
              <div className="mt-1 font-mono text-[16px] text-ink">
                {num(health.cost.round_trip_taker_bp).toFixed(2)} bp
              </div>
              <div className="text-[11px] text-faint">费率 {num(health.cost.taker_fee_bp).toFixed(2)} bp × 2 + 滑点 × 2</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-faint">资金费 / 8h</div>
              <div className="mt-1 font-mono text-[16px] text-ink">
                {num(health.cost.funding_bp_per_8h).toFixed(4)} bp
              </div>
              <div className="text-[11px] text-faint">正=多头付；空头符号相反</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-faint">保本间距</div>
              <div className="mt-1 font-mono text-[16px] text-ink">
                {num(health.cost.breakeven_spacing_bp).toFixed(2)} bp
              </div>
              <div className="text-[11px] text-faint">
                {health.cost.is_profitable != null
                  ? `当前间距净边际 ${num(health.cost.net_edge_bp).toFixed(2)} bp`
                  : '网格间距需大于该值才有正期望'}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-[12px] text-faint">节点未返回成本模型（升级适配器后可见）。</p>
        )}
      </Card>

      <p className="text-[11px] leading-relaxed text-faint">
        说明：本页只读，所有下单/撤单仍需在东京节点上人工操作（`BINANCE_TRADING=0` 且 KILL 文件在位时，
        适配器会直接拒绝写请求）。节点地址由服务端 `GRIDTRADE_BINANCE_NODE_URL` 配置，仅隧道地址可达。
      </p>
    </div>
  )
}
