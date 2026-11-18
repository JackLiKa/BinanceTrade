import { useEffect, useState } from 'react'
import { KeyRound, Lock, RefreshCw, ShieldCheck, Unlock } from 'lucide-react'
import { api, type LiveConfigInput, type LiveConfigView, type LiveOrderInput, type LiveSnapshot } from '../api'
import { NumberInput } from '../components/inputs'
import { Badge, Button, Card, CardHead, Empty, ErrorNote, Field, Skeleton, Stat, Toggle } from '../components/ui'
import { cx, fmtMoney, fmtPct, fmtPrice, fmtQty, fmtTime, timeAgo } from '../format'
import { errorText, useFetch } from '../hooks'
import { useApp } from '../store'

const SYMBOLS = ['SKHY_USDT', 'SPCX_USDT', 'GOOGL_USDT', 'AMGN_USDT']
const row = (value: Record<string, unknown>, key: string): string => {
  const raw = value[key]
  return raw === null || raw === undefined ? '—' : String(raw)
}

interface Form {
  max_notional: number
  max_order_notional: number
  max_position_notional: number
  max_open_orders: number
}

const FORM_DEFAULTS: Form = {
  max_notional: 5_000,
  max_order_notional: 1_000,
  max_position_notional: 3_000,
  max_open_orders: 20,
}

export function Live() {
  const { toast } = useApp()
  const state = useFetch(() => api.live(), [], { pollMs: 15_000 })
  const [cfg, setCfg] = useState<LiveConfigView | null>(null)
  const [form, setForm] = useState<Form>(FORM_DEFAULTS)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [trading, setTrading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const data = state.data

  useEffect(() => {
    if (!data) return
    setCfg(data.config)
    setForm({
      max_notional: data.config.max_notional,
      max_order_notional: data.config.max_order_notional,
      max_position_notional: data.config.max_position_notional,
      max_open_orders: data.config.max_open_orders,
    })
    setEnabled(data.config.enabled)
    setTrading(data.config.trading_enabled)
  }, [data])

  const patch = (key: keyof Form) => (value: number | null) => {
    if (value === null) return
    setForm((current) => ({ ...current, [key]: value }))
  }

  const run = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusy(key)
    setError(null)
    try {
      await action()
      state.reload()
      toast(message, 'ok')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(null)
    }
  }

  const save = () =>
    run(
      'save',
      async () => {
        const payload: LiveConfigInput = {
          enabled,
          trading_enabled: trading,
          confirm_trading: trading,
          ...form,
        }
        if (apiKey.trim()) payload.api_key = apiKey.trim()
        if (apiSecret.trim()) payload.api_secret = apiSecret.trim()
        const result = await api.saveLiveConfig(payload)
        setCfg(result.config)
        setApiKey('')
        setApiSecret('')
      },
      '实盘配置已写入服务器 .env',
    )

  const test = () => run('test', () => api.testLive(), '实盘连接成功')
  const sync = () => run('sync', () => api.liveSync(), '已刷新实盘账户')
  const clear = () =>
    run('clear', () => api.saveLiveConfig({ clear_credentials: true, enabled: false, trading_enabled: false }), '已清除实盘凭据')

  const toggleTrading = (next: boolean) => {
    if (next) {
      const ok = window.confirm(
        '开启后本页面可以提交真实订单（受风控上限约束）。确认已经完成 Gate API Key 权限、IP 白名单与资金规模核对？',
      )
      if (!ok) return
    }
    setTrading(next)
  }

  const configCard = (
    <Card>
      <CardHead
        title="实盘配置"
        hint="凭据保存在服务器 .env（0600）；页面只显示 Key 后四位，Secret 永不回传。"
        right={
          <Badge tone={cfg?.configured ? 'up' : 'neutral'}>
            {cfg?.configured ? `已配置 ${cfg.api_key_hint}` : '未配置'}
          </Badge>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Gate API Key" hint={cfg?.configured ? '留空表示不修改' : '建议只读权限；下单需交易权限且禁用提现'}>
          <input
            className="input font-mono"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={cfg?.api_key_hint || '粘贴 API Key'}
            autoComplete="off"
          />
        </Field>
        <Field label="Gate API Secret" hint={cfg?.has_secret ? '已保存；留空表示不修改' : '仅写入服务器 .env'}>
          <input
            className="input font-mono"
            type="password"
            value={apiSecret}
            onChange={(event) => setApiSecret(event.target.value)}
            placeholder="粘贴 API Secret"
            autoComplete="new-password"
          />
        </Field>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-5 border-t border-line-soft pt-4">
        <Toggle checked={enabled} onChange={setEnabled} label="启用实盘账户同步" />
        <Toggle checked={trading} onChange={toggleTrading} label="允许实盘下单（默认锁定）" />
        {trading ? (
          <span className="flex items-center gap-1 text-[11px] text-down">
            <Unlock size={12} /> 下单已解锁：提交前请再次核对金额
          </span>
        ) : (
          <span className="flex items-center gap-1 text-[11px] text-faint">
            <Lock size={12} /> 下单锁定中（不会发送任何订单）
          </span>
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line-soft pt-4 sm:grid-cols-4">
        <Field label="总名义上限" hint="USDT">
          <NumberInput value={form.max_notional} onChange={patch('max_notional')} min={1} suffix="$" />
        </Field>
        <Field label="单笔上限" hint="USDT">
          <NumberInput value={form.max_order_notional} onChange={patch('max_order_notional')} min={1} suffix="$" />
        </Field>
        <Field label="单标的上限" hint="USDT">
          <NumberInput value={form.max_position_notional} onChange={patch('max_position_notional')} min={1} suffix="$" />
        </Field>
        <Field label="最大挂单数" hint="个">
          <NumberInput value={form.max_open_orders} onChange={patch('max_open_orders')} min={1} suffix="个" />
        </Field>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" loading={busy === 'save'} onClick={save}>
          <KeyRound size={13} /> 保存到 .env
        </Button>
        <Button loading={busy === 'test'} disabled={!cfg?.configured} onClick={test}>
          <ShieldCheck size={13} /> 测试连接
        </Button>
        <Button loading={busy === 'sync'} disabled={!cfg?.configured || !enabled} onClick={sync}>
          <RefreshCw size={13} /> 刷新账户
        </Button>
        {cfg?.configured ? (
          <Button variant="danger" loading={busy === 'clear'} onClick={clear}>
            清除凭据
          </Button>
        ) : null}
      </div>
      {error ? <div className="mt-3"><ErrorNote>{error}</ErrorNote></div> : null}
      {!cfg?.configured ? (
        <div className="mt-4 rounded-lg border border-line bg-elevated/40 p-3 text-[11px] leading-relaxed text-muted">
          在 Gate 后台创建 API Key：开启「合约账户读取」；若要下单再开「合约交易」，务必关闭提现权限，
          并将 IP 白名单设为服务器出口 IP（81.71.71.131）。保存后点“测试连接”，再按需开启同步与下单。
        </div>
      ) : null}
    </Card>
  )

  if (state.error && !data) {
    return (
      <div className="space-y-4">
        <ErrorNote>{state.error}</ErrorNote>
        <Button onClick={state.reload}>重试</Button>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  const analysis = data.analysis
  const account = data.account
  const tradingLocked = !data.config.trading_enabled

  return (
    <div className="space-y-4">
      {configCard}

      {!data.config.configured ? (
        <Empty
          title="还没有配置实盘凭据"
          body="填写上方 API Key 与 Secret 并保存到服务器 .env 后，这里会显示 Gate 实盘账户余额、持仓、挂单、成交与盈亏分析。"
        />
      ) : null}

      {data.config.configured && !data.config.enabled ? (
        <Empty title="实盘同步未启用" body="在上方打开“启用实盘账户同步”并保存，页面会开始拉取账户数据。" />
      ) : null}

      {data.error ? <ErrorNote>{data.error}</ErrorNote> : null}

      {account && analysis ? (
        <>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[13px] font-semibold text-ink">Gate 实盘账户</h2>
                  <Badge tone="info">{data.exchange}</Badge>
                  <Badge tone={data.config.trading_enabled ? 'down' : 'neutral'}>
                    {data.config.trading_enabled ? '下单已解锁' : '下单锁定'}
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] text-muted">
                  同步于 {data.synced_at ? timeAgo(data.synced_at) : '—'} · {data.config.api_key_hint}
                </p>
              </div>
              <Stat label="账户权益" value={`$${fmtMoney(analysis.equity, 2)}`} large tone={analysis.unrealized} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4 border-t border-line-soft pt-4 sm:grid-cols-4">
              <Stat label="可用" value={`$${fmtMoney(analysis.available, 2)}`} />
              <Stat label="未实现" value={`$${fmtMoney(analysis.unrealized, 2)}`} tone={analysis.unrealized} />
              <Stat label="已实现" value={`$${fmtMoney(analysis.realized, 2)}`} tone={analysis.realized} />
              <Stat label="维持保证金率" value={analysis.margin_ratio === null ? '—' : fmtPct(analysis.margin_ratio * 100, 2, false)} tone={analysis.margin_ratio && analysis.margin_ratio > 0.7 ? -1 : undefined} />
              <Stat label="手续费" value={`$${fmtMoney(analysis.fees_paid, 3)}`} />
              <Stat label="资金费" value={`$${fmtMoney(analysis.funding_paid, 3)}`} />
              <Stat label="总名义" value={`$${fmtMoney(analysis.gross_notional, 0)}`} sub={`净敞口 $${fmtMoney(analysis.net_notional, 0)}`} />
              <Stat label="挂单" value={`${analysis.open_orders} 个`} sub={`名义 $${fmtMoney(analysis.open_orders_notional, 0)}`} />
            </div>
            {analysis.warnings.length ? (
              <div className="mt-3 space-y-1">
                {analysis.warnings.map((warning) => (
                  <ErrorNote key={warning}>{warning}</ErrorNote>
                ))}
              </div>
            ) : null}
          </Card>

          <Card pad={false}>
            <div className="px-5 pt-5">
              <CardHead title="持仓" hint="名义按合约数量 × 标记价 × quanto_multiplier 计算。" right={<Badge tone="neutral">{data.positions.length}</Badge>} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-[11.5px]">
                <thead>
                  <tr className="border-t border-line-soft text-left text-[10px] uppercase tracking-wider text-faint">
                    <th className="px-5 py-2 font-medium">合约</th>
                    <th className="py-2 text-right font-medium">数量</th>
                    <th className="py-2 text-right font-medium">均价</th>
                    <th className="py-2 text-right font-medium">标记价</th>
                    <th className="py-2 text-right font-medium">未实现</th>
                    <th className="py-2 text-right font-medium">名义</th>
                    <th className="py-2 text-right font-medium">杠杆</th>
                    <th className="py-2 pr-5 text-right font-medium">强平价</th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.length === 0 ? (
                    <tr><td colSpan={8} className="px-5 py-8 text-center text-[12px] text-muted">当前无持仓</td></tr>
                  ) : (
                    data.positions.map((position) => (
                      <tr key={position.contract} className="border-t border-line-soft">
                        <td className="px-5 py-2 font-mono text-ink">{position.contract}</td>
                        <td className={cx('py-2 text-right font-mono tabular-nums', position.size > 0 ? 'text-up' : 'text-down')}>
                          {fmtQty(position.size)}
                        </td>
                        <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(position.entry_price)}</td>
                        <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(position.mark_price)}</td>
                        <td className={cx('py-2 text-right font-mono tabular-nums', (position.unrealized ?? 0) >= 0 ? 'text-up' : 'text-down')}>
                          {fmtMoney(position.unrealized ?? 0, 2)}
                        </td>
                        <td className="py-2 text-right font-mono tabular-nums">{fmtMoney(position.notional, 0)}</td>
                        <td className="py-2 text-right font-mono tabular-nums">{position.leverage ?? '—'}</td>
                        <td className="py-2 pr-5 text-right font-mono tabular-nums text-muted">{fmtPrice(position.liq_price)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card pad={false}>
              <div className="px-5 pt-5">
                <CardHead title="挂单" hint={tradingLocked ? '下单锁定，撤单按钮不可用。' : '可撤销单笔挂单。'} right={<Badge tone="neutral">{data.orders.length}</Badge>} />
              </div>
              <div className="max-h-[320px] overflow-auto">
                <table className="w-full text-[11.5px]">
                  <thead className="sticky top-0 bg-panel">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                      <th className="px-5 py-2 font-medium">时间</th>
                      <th className="py-2 font-medium">合约</th>
                      <th className="py-2 text-right font-medium">价格</th>
                      <th className="py-2 text-right font-medium">剩余</th>
                      <th className="py-2 pr-5 text-right font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.orders.length === 0 ? (
                      <tr><td colSpan={5} className="px-5 py-8 text-center text-[12px] text-muted">无挂单</td></tr>
                    ) : (
                      data.orders.map((order) => (
                        <tr key={row(order, 'id')} className="border-t border-line-soft">
                          <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(row(order, 'create_time'))}</td>
                          <td className="py-2 font-mono text-[10.5px]">{row(order, 'contract')}</td>
                          <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(Number(row(order, 'price')))}</td>
                          <td className="py-2 text-right font-mono tabular-nums">{row(order, 'left')}</td>
                          <td className="py-2 pr-5 text-right">
                            <Button
                              size="sm"
                              disabled={tradingLocked}
                              onClick={() =>
                                run('cancel', () => api.cancelLiveOrder(row(order, 'id')), '已提交撤单')
                              }
                            >
                              撤单
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card pad={false}>
              <div className="px-5 pt-5">
                <CardHead title="交割单（成交）" hint="手数与价格来自 Gate 私有接口。" right={<Badge tone="neutral">{data.trades.length}</Badge>} />
              </div>
              <div className="max-h-[320px] overflow-auto">
                <table className="w-full text-[11.5px]">
                  <thead className="sticky top-0 bg-panel">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                      <th className="px-5 py-2 font-medium">时间</th>
                      <th className="py-2 font-medium">合约</th>
                      <th className="py-2 text-right font-medium">数量</th>
                      <th className="py-2 text-right font-medium">价格</th>
                      <th className="py-2 pr-5 text-right font-medium">手续费</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.length === 0 ? (
                      <tr><td colSpan={5} className="px-5 py-8 text-center text-[12px] text-muted">无成交</td></tr>
                    ) : (
                      data.trades.map((trade) => (
                        <tr key={row(trade, 'id')} className="border-t border-line-soft">
                          <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(row(trade, 'create_time'))}</td>
                          <td className="py-2 font-mono text-[10.5px]">{row(trade, 'contract')}</td>
                          <td className="py-2 text-right font-mono tabular-nums">{row(trade, 'size')}</td>
                          <td className="py-2 text-right font-mono tabular-nums">{fmtPrice(Number(row(trade, 'price')))}</td>
                          <td className="py-2 pr-5 text-right font-mono tabular-nums text-muted">{row(trade, 'fee')}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <Card pad={false}>
            <div className="px-5 pt-5">
              <CardHead title="资金流水" hint="Gate account_book：pnl=已实现、fee=手续费、fund=资金费；可对照交割单。" right={<Badge tone="neutral">{data.ledger.length}</Badge>} />
            </div>
            <div className="max-h-[300px] overflow-auto">
              <table className="w-full text-[11.5px]">
                <thead className="sticky top-0 bg-panel">
                  <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                    <th className="px-5 py-2 font-medium">时间</th>
                    <th className="py-2 font-medium">类型</th>
                    <th className="py-2 font-medium">合约</th>
                    <th className="py-2 pr-5 text-right font-medium">变动</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ledger.length === 0 ? (
                    <tr><td colSpan={4} className="px-5 py-8 text-center text-[12px] text-muted">无流水</td></tr>
                  ) : (
                    data.ledger.map((item, index) => (
                      <tr key={`${row(item, 'time')}-${index}`} className="border-t border-line-soft">
                        <td className="px-5 py-2 font-mono text-[10.5px] text-muted">{fmtTime(row(item, 'time'))}</td>
                        <td className="py-2 font-mono text-[10.5px]">{row(item, 'type')}</td>
                        <td className="py-2 font-mono text-[10.5px]">{row(item, 'contract')}</td>
                        <td className={cx('py-2 pr-5 text-right font-mono tabular-nums', Number(row(item, 'change')) >= 0 ? 'text-up' : 'text-down')}>
                          {row(item, 'change')}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card>
            <CardHead
              title="实盘风控"
              hint="下单前会校验这些上限；即使开启下单，超过上限的订单也会被拒绝。"
              right={<Badge tone="warn">默认锁定</Badge>}
            />
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="总名义上限" value={`$${fmtMoney(analysis.limits.max_notional, 0)}`} />
              <Stat label="单笔上限" value={`$${fmtMoney(analysis.limits.max_order_notional, 0)}`} />
              <Stat label="单标的上限" value={`$${fmtMoney(analysis.limits.max_position_notional, 0)}`} />
              <Stat label="最大挂单" value={`${analysis.limits.max_open_orders} 个`} />
            </div>
          </Card>

          <Card>
            <CardHead
              title="实盘下单（锁定）"
              hint="未开启“允许实盘下单”时按钮不可用；开启后订单仍受上方风控上限与紧急停止约束。"
              right={<Badge tone={tradingLocked ? 'neutral' : 'down'}>{tradingLocked ? '已锁定' : '已解锁'}</Badge>}
            />
            <OrderTicket locked={tradingLocked} onDone={state.reload} toast={toast} />
          </Card>
        </>
      ) : null}
    </div>
  )
}

function OrderTicket({
  locked,
  onDone,
  toast,
}: {
  locked: boolean
  onDone: () => void
  toast: (text: string, tone?: 'ok' | 'error' | 'info') => void
}) {
  const [contract, setContract] = useState(SYMBOLS[0])
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [size, setSize] = useState<number | null>(1)
  const [price, setPrice] = useState('')
  const [reduceOnly, setReduceOnly] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!size || size <= 0) {
      toast('数量必须为正整数（合约张数）', 'error')
      return
    }
    const signed = side === 'BUY' ? Math.trunc(size) : -Math.trunc(size)
    const body: LiveOrderInput = { contract, size: signed, reduce_only: reduceOnly, tif: price ? 'gtc' : 'ioc' }
    if (price) body.price = price
    setBusy(true)
    try {
      await api.liveOrder(body)
      toast('实盘订单已提交', 'ok')
      onDone()
    } catch (err) {
      toast(errorText(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-4 sm:grid-cols-5">
      <Field label="合约">
        <select className="input" value={contract} onChange={(event) => setContract(event.target.value)}>
          {SYMBOLS.map((symbol) => (
            <option key={symbol} value={symbol}>{symbol}</option>
          ))}
        </select>
      </Field>
      <Field label="方向">
        <select className="input" value={side} onChange={(event) => setSide(event.target.value as 'BUY' | 'SELL')}>
          <option value="BUY">买入 / 做多</option>
          <option value="SELL">卖出 / 做空</option>
        </select>
      </Field>
      <Field label="数量（张）" hint="Gate 合约张数">
        <NumberInput value={size} onChange={setSize} min={1} />
      </Field>
      <Field label="价格" hint="留空 = 市价 IOC">
        <input className="input font-mono" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="限价" />
      </Field>
      <Field label="只减仓">
        <Toggle checked={reduceOnly} onChange={setReduceOnly} label="reduce-only" />
      </Field>
      <div className="sm:col-span-5 flex items-center gap-3">
        <Button variant="danger" loading={busy} disabled={locked} onClick={submit}>
          提交实盘订单
        </Button>
        {locked ? (
          <span className="text-[11px] text-faint">已锁定：保存配置时开启“允许实盘下单”后才可用。</span>
        ) : (
          <span className="text-[11px] text-down">注意：这是真实资金订单。</span>
        )}
      </div>
    </div>
  )
}
