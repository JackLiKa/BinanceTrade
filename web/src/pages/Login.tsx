import { useEffect, useState, type FormEvent } from 'react'
import { Activity, ArrowRight, KeyRound, Server, ShieldCheck } from 'lucide-react'
import { api, getServer, getToken, setServer } from '../api'
import { useApp } from '../store'
import { Button, Field } from '../components/ui'
import { errorText } from '../hooks'

export function Login() {
  const { signIn, toast } = useApp()
  const [token, setTokenValue] = useState(() => getToken())
  const [server, setServerValue] = useState(() => getServer())
  const [showServer, setShowServer] = useState(() => Boolean(getServer()))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setServer(server)
    api
      .health()
      .then((data) => {
        if (active) setHealth(`服务端 ${data.version} 已连接`)
      })
      .catch(() => {
        if (active) setHealth(null)
      })
    return () => {
      active = false
    }
  }, [server])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!token.trim()) {
      setError('请输入 var/token 中的访问令牌。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      setServer(server)
      await signIn(token.trim())
      toast('已登录', 'ok')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden bg-base px-4 py-10">
      <div className="pointer-events-none absolute inset-0 grid-motif opacity-60" />
      <div className="relative grid w-full max-w-3xl overflow-hidden rounded-2xl border border-line-soft bg-panel shadow-[0_30px_80px_-40px_rgba(0,0,0,0.9)] md:grid-cols-[1.05fr_1fr]">
        <div className="hidden flex-col justify-between border-r border-line-soft bg-[#0d1014] p-8 md:flex">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="grid h-9 w-9 place-items-center rounded-xl border border-accent/30 bg-accent/10">
                <Activity size={18} className="text-accent" />
              </div>
              <div>
                <div className="text-[14px] font-semibold tracking-wide text-ink">Gridtrade</div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-faint">
                  研究终端
                </div>
              </div>
            </div>
            <p className="mt-8 max-w-[26ch] text-[20px] font-semibold leading-snug tracking-tight text-ink">
              诚实的成交、资金费率与回撤，本地网格研究。
            </p>
            <p className="mt-3 text-[12px] leading-relaxed text-muted">
              回放复用模拟盘同一套引擎。所有数字均来自本地 Parquet
              数据——没有未来函数，也没有美化成交。
            </p>
          </div>
          <ul className="space-y-3 text-[11.5px] text-muted">
            <li className="flex items-center gap-2.5">
              <ShieldCheck size={14} className="text-up" /> 回测 · 模拟盘 · 只读实盘分析
            </li>
            <li className="flex items-center gap-2.5">
              <Server size={14} className="text-info" /> 运行在本机或 Tailscale
            </li>
            <li className="flex items-center gap-2.5">
              <KeyRound size={14} className="text-accent" /> 单一令牌，httpOnly Cookie
            </li>
          </ul>
        </div>

        <form onSubmit={submit} className="flex flex-col justify-center gap-4 p-7 md:p-8">
          <div className="md:hidden">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-accent" />
              <span className="text-[13px] font-semibold text-ink">Gridtrade 研究终端</span>
            </div>
          </div>
          <div>
            <h1 className="text-[17px] font-semibold tracking-tight text-ink">解锁研究终端</h1>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              粘贴服务端生成的访问令牌，通常位于 <code className="font-mono text-accent">var/token</code>。
            </p>
          </div>

          <Field label="访问令牌">
            <input
              className="input font-mono"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(event) => setTokenValue(event.target.value)}
              placeholder="••••••••••••••••••••"
              autoFocus
            />
          </Field>

          <div>
            <button
              type="button"
              onClick={() => setShowServer((open) => !open)}
              className="flex items-center gap-1.5 text-[11px] text-muted transition-colors hover:text-ink"
            >
              <Server size={12} />
              {showServer ? '隐藏服务器地址' : '服务器地址'}
            </button>
            {showServer ? (
              <div className="mt-2">
                <input
                  className="input font-mono text-[12px]"
                  value={server}
                  onChange={(event) => setServerValue(event.target.value)}
                  placeholder="http://192.168.1.20:8000"
                  inputMode="url"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                />
                <p className="mt-1.5 text-[10.5px] leading-snug text-faint">
                  面板由 API 自身提供时留空；APK 中请填写局域网或 Tailscale 地址。
                </p>
              </div>
            ) : null}
          </div>

          {error ? (
            <div className="rounded-lg border border-down/30 bg-down/8 px-3 py-2 text-[11.5px] leading-relaxed text-down">
              {error}
            </div>
          ) : null}

          <Button type="submit" variant="primary" loading={busy} className="w-full">
            登录 <ArrowRight size={14} />
          </Button>

          <div className="flex items-center justify-between text-[10.5px] text-faint">
            <span>{health ?? '服务端不可达'}</span>
            <span className="font-mono">{server || '同源'}</span>
          </div>
        </form>
      </div>
    </div>
  )
}
