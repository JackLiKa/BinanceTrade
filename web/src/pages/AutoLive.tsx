import { useState } from 'react'
import { Bot, Power, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, CardHead, ErrorNote, Stat } from '../components/ui'

type AutoState = {
  armed: boolean
  status: string
  symbol: string
  last_error: string | null
  anchor: number
  unit: number
  step: number
  level: number
  position: number
  start_equity: number
  orders: Array<{ clientOrderId?: string; side?: string; price?: string; status?: string }>
  log: string[]
  config: Record<string, number | string>
}

export function AutoLivePage() {
  const [state, setState] = useState<AutoState | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    symbol: 'AMGNUSDT', capital: 10, levels: 4, leverage: 1, spacing_bp: 100,
    stop_dd_pct: 10, max_order_notional: 6, max_position_notional: 10,
    daily_loss_limit_pct: 5, poll_seconds: 5,
  })

  const load = async () => {
    try { setState(await api.autoLive() as unknown as AutoState); setError('') } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }
  const arm = async () => {
    const answer = window.prompt('真实自动交易。输入 ARM 确认：')
    if (answer !== 'ARM') return
    setBusy(true); setError('')
    try {
      setState(await api.autoLiveArm({ ...form, confirm: true }) as unknown as AutoState)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const disarm = async () => {
    setBusy(true)
    try { setState(await api.autoLiveDisarm() as unknown as AutoState) } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  if (!state) {
    return <div className="space-y-4"><ErrorNote>{error || '正在读取自动实盘状态…'}</ErrorNote><Button onClick={load}>刷新</Button></div>
  }

  const armed = state.armed
  const field = (key: keyof typeof form, label: string, suffix = '') => (
    <label className="text-[11px] text-faint">
      {label}
      <input
        className="mt-1 w-full rounded border border-line bg-elevated px-2 py-1.5 font-mono text-[12px] text-ink"
        type="number"
        value={form[key]}
        onChange={(event) => setForm({ ...form, [key]: Number(event.target.value) })}
      />
      <span className="ml-1">{suffix}</span>
    </label>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[15px] font-semibold text-ink">自动实盘</h1>
          <p className="mt-1 text-[11.5px] text-faint">节点端执行 · 默认关闭 · 手动 ARM 后才下单 · 重启自动回到关闭</p>
        </div>
        <Badge tone={armed ? 'warn' : 'neutral'}>{armed ? '运行中' : '已关闭'}</Badge>
      </div>

      {error ? <ErrorNote>{error}</ErrorNote> : null}
      {state.last_error ? <ErrorNote>{state.last_error}</ErrorNote> : null}

      <Card>
        <CardHead title="安全边界" right={<Badge tone="warn">REAL MONEY</Badge>} />
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="状态" value={state.status} />
          <Stat label="标的" value={state.symbol || '—'} />
          <Stat label="起始权益" value={`$${Number(state.start_equity || 0).toFixed(2)}`} />
          <Stat label="锚点" value={state.anchor.toFixed(2)} />
          <Stat label="每格数量" value={String(state.unit)} />
          <Stat label="当前持仓" value={String(state.position)} />
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-down">
          自动实盘会真实下单。仅在东京节点 BINANCE_TRADING=1、KILL 不存在、且你输入 ARM 后运行。
          触发日亏损限制会自动撤单并停止，但不会自动市价平仓。
        </p>
      </Card>

      <Card>
        <CardHead title="参数（节点侧再校验）" />
        <div className="grid gap-3 sm:grid-cols-3">
          {field('symbol', '标的')}
          {field('capital', '本金 USDT')}
          {field('levels', '层数')}
          {field('leverage', '杠杆', 'x')}
          {field('spacing_bp', '间距', 'bp')}
          {field('stop_dd_pct', '止损', '%')}
          {field('max_order_notional', '单笔上限 USDT')}
          {field('max_position_notional', '持仓上限 USDT')}
          {field('daily_loss_limit_pct', '日亏损上限', '%')}
          {field('poll_seconds', '轮询秒')}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={arm} loading={busy} disabled={armed}><Bot size={14} /> 开启自动实盘</Button>
          <Button variant="danger" onClick={disarm} loading={busy} disabled={!armed}><Power size={14} /> 立即停止</Button>
          <Button onClick={load}>刷新状态</Button>
        </div>
      </Card>

      <Card>
        <CardHead title="自动挂单" right={<Badge tone="neutral">{state.orders.length}</Badge>} />
        <pre className="max-h-48 overflow-auto text-[11px] text-muted">{JSON.stringify(state.orders, null, 2)}</pre>
        <CardHead title="事件日志" right={<ShieldAlert size={14} />} />
        <pre className="max-h-64 overflow-auto text-[11px] text-muted">{state.log.join('\n') || '暂无'}</pre>
      </Card>
    </div>
  )
}
