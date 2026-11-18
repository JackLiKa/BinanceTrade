import { useState } from 'react'
import { Play, Send } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, CardHead, ErrorNote } from '../components/ui'

type Product = 'spot' | 'usdm' | 'coinm' | 'options' | 'wallet'

const PRESETS: Array<{ product: Product; method: string; path: string; signed: boolean; label: string }> = [
  { product: 'spot', method: 'GET', path: '/api/v3/ticker/24hr', signed: false, label: '现货 24h 行情' },
  { product: 'spot', method: 'GET', path: '/api/v3/account', signed: true, label: '现货账户' },
  { product: 'spot', method: 'GET', path: '/api/v3/openOrders', signed: true, label: '现货挂单' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/time', signed: false, label: 'U本位服务器时间' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/exchangeInfo', signed: false, label: 'U本位交易规则' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/leverageBracket', signed: true, label: 'U本位杠杆档位' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/insuranceBalance', signed: false, label: 'U本位保险基金' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/symbolAdlRisk', signed: false, label: 'U本位 ADL 风险' },
  { product: 'usdm', method: 'GET', path: '/fapi/v2/account', signed: true, label: 'U本位账户' },
  { product: 'usdm', method: 'GET', path: '/fapi/v2/positionRisk', signed: true, label: 'U本位持仓' },
  { product: 'usdm', method: 'GET', path: '/fapi/v1/openOrders', signed: true, label: 'U本位挂单' },
  { product: 'coinm', method: 'GET', path: '/dapi/v1/time', signed: false, label: '币本位服务器时间' },
  { product: 'coinm', method: 'GET', path: '/dapi/v1/exchangeInfo', signed: false, label: '币本位交易规则' },
  { product: 'coinm', method: 'GET', path: '/dapi/v1/account', signed: true, label: '币本位账户' },
  { product: 'options', method: 'GET', path: '/eapi/v1/time', signed: false, label: '期权服务器时间' },
  { product: 'options', method: 'GET', path: '/eapi/v1/exchangeInfo', signed: false, label: '期权交易规则' },
  { product: 'options', method: 'GET', path: '/eapi/v1/account', signed: true, label: '期权账户' },
  { product: 'wallet', method: 'GET', path: '/sapi/v1/capital/config/getall', signed: true, label: '钱包币种配置' },
  { product: 'wallet', method: 'GET', path: '/sapi/v1/account/status', signed: true, label: '账户状态' },
]

export function BinanceApi() {
  const [product, setProduct] = useState<Product>('usdm')
  const [method, setMethod] = useState('GET')
  const [path, setPath] = useState('/fapi/v1/time')
  const [params, setParams] = useState('{}')
  const [signed, setSigned] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [result, setResult] = useState<string>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const call = async () => {
    setBusy(true)
    setError('')
    setResult('')
    try {
      let parsed: Record<string, unknown> = {}
      try {
        parsed = JSON.parse(params || '{}')
      } catch {
        throw new Error('params 不是合法 JSON')
      }
      const response = await api.binanceGateway({ product, method, path, params: parsed, signed, confirm })
      setResult(JSON.stringify(response, null, 2))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[15px] font-semibold text-ink">Binance API</h1>
          <p className="mt-1 text-[11.5px] text-faint">
            通用官方接口控制台 · 只读全部产品；写接口需节点 BINANCE_TRADING=1 + confirm。
            提现/划转只走服务器本地 scripts/binance_cli.py，不经面板。
          </p>
        </div>
        <Badge tone="warn">写接口默认锁定</Badge>
      </div>

      {error ? <ErrorNote>{error}</ErrorNote> : null}

      <Card>
        <CardHead title="常用接口" hint="点击填入；也可直接输入任意官方 REST 路径" />
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((preset) => (
            <button
              key={`${preset.product}-${preset.path}-${preset.signed}`}
              type="button"
              className="rounded border border-line bg-elevated px-2 py-1 text-[11px] text-muted hover:text-ink"
              onClick={() => {
                setProduct(preset.product)
                setMethod(preset.method)
                setPath(preset.path)
                setSigned(preset.signed)
                setParams('{}')
              }}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <CardHead title="请求" right={<Badge tone="neutral">{product}</Badge>} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-[11px] text-faint">
            产品
            <select
              className="mt-1 w-full rounded border border-line bg-elevated px-2 py-1.5 text-[12px] text-ink"
              value={product}
              onChange={(event) => setProduct(event.target.value as Product)}
            >
              <option value="spot">现货 Spot</option>
              <option value="usdm">U 本位 USDⓈ-M</option>
              <option value="coinm">币本位 COIN-M</option>
              <option value="options">期权 Options</option>
              <option value="wallet">钱包 Wallet</option>
            </select>
          </label>
          <label className="text-[11px] text-faint">
            方法
            <select
              className="mt-1 w-full rounded border border-line bg-elevated px-2 py-1.5 text-[12px] text-ink"
              value={method}
              onChange={(event) => setMethod(event.target.value)}
            >
              {['GET', 'POST', 'PUT', 'DELETE'].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="mt-3 block text-[11px] text-faint">
          路径
          <input
            className="mt-1 w-full rounded border border-line bg-elevated px-2 py-1.5 font-mono text-[12px] text-ink"
            value={path}
            onChange={(event) => setPath(event.target.value)}
          />
        </label>
        <label className="mt-3 block text-[11px] text-faint">
          params（JSON）
          <textarea
            className="mt-1 min-h-[110px] w-full rounded border border-line bg-elevated px-2 py-1.5 font-mono text-[12px] text-ink"
            value={params}
            onChange={(event) => setParams(event.target.value)}
          />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-4 text-[12px] text-muted">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={signed} onChange={(event) => setSigned(event.target.checked)} />
            签名请求（需要 API Key）
          </label>
          {method !== 'GET' ? (
            <label className="flex items-center gap-2 text-down">
              <input type="checkbox" checked={confirm} onChange={(event) => setConfirm(event.target.checked)} />
              确认真实写操作
            </label>
          ) : null}
          <Button onClick={call} loading={busy} disabled={!path}>
            {method === 'GET' ? <Play size={13} /> : <Send size={13} />} 发送
          </Button>
        </div>
      </Card>

      <Card>
        <CardHead title="响应" right={<Badge tone="neutral">{result ? '200 / raw' : '—'}</Badge>} />
        <pre className="max-h-[520px] overflow-auto rounded border border-line bg-elevated/60 p-3 text-[11px] leading-relaxed text-muted">
          {result || '尚无响应'}
        </pre>
      </Card>
    </div>
  )
}
