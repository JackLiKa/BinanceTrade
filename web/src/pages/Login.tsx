import { useEffect, useState, type FormEvent } from 'react'
import {
  Activity,
  ArrowRight,
  Check,
  Copy,
  ExternalLink,
  KeyRound,
  Server,
  ShieldCheck,
} from 'lucide-react'
import { api, getServer, getToken, setServer, type AuthProviders, type GoogleDeviceStart, type GooglePollResult } from '../api'
import { useApp } from '../store'
import { Button, Field } from '../components/ui'
import { errorText } from '../hooks'

function GoogleIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

export function Login() {
  const { signIn, refreshSession, toast } = useApp()
  const [token, setTokenValue] = useState(() => getToken())
  const [server, setServerValue] = useState(() => getServer())
  const [showServer, setShowServer] = useState(() => Boolean(getServer()))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<string | null>(null)
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [flow, setFlow] = useState<GoogleDeviceStart | null>(null)
  const [poll, setPoll] = useState<GooglePollResult | null>(null)
  const [copied, setCopied] = useState(false)
  const google = providers?.google

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
    api
      .authProviders()
      .then((data) => {
        if (active) setProviders(data)
      })
      .catch(() => {
        if (active) setProviders(null)
      })
    return () => {
      active = false
    }
  }, [server])

  // Poll Google while the user completes authorization in another tab/browser.
  useEffect(() => {
    if (!flow) return
    let cancelled = false
    let timer = 0
    const tick = async () => {
      try {
        const result = await api.googlePoll(flow.flow_id)
        if (cancelled) return
        setPoll(result)
        if (result.status === 'ok') {
          setFlow(null)
          toast(`已登录 ${result.email ?? 'Google 账号'}`, 'ok')
          await refreshSession()
        } else if (result.status === 'pending') {
          timer = window.setTimeout(tick, Math.max(5, result.interval ?? flow.interval) * 1000)
        } else {
          setError(result.error ?? 'Google 登录失败')
          setFlow(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorText(err))
          setFlow(null)
        }
      }
    }
    timer = window.setTimeout(tick, Math.max(5, flow.interval) * 1000)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [flow, refreshSession, toast])

  const startGoogle = async () => {
    setBusy(true)
    setError(null)
    setPoll(null)
    try {
      const started = await api.googleStart()
      setFlow(started)
      // WebView/APK routes window.open to the system browser (MainActivity).
      window.open(started.verification_url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const copyCode = async () => {
    if (!flow) return
    try {
      await navigator.clipboard.writeText(flow.user_code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      window.prompt('复制授权码', flow.user_code)
    }
  }

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
              <KeyRound size={14} className="text-accent" /> Google 账号登录，管理员白名单
            </li>
          </ul>
        </div>

        <div className="flex flex-col justify-center gap-4 p-7 md:p-8">
          <div className="md:hidden">
            <div className="flex items-center gap-2">
              <Activity size={16} className="text-accent" />
              <span className="text-[13px] font-semibold text-ink">Gridtrade 研究终端</span>
            </div>
          </div>
          <div>
            <h1 className="text-[17px] font-semibold tracking-tight text-ink">登录研究终端</h1>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              使用管理员允许的 Google 账号登录；授权一次后会话保持 30 天。
            </p>
          </div>

          {error ? (
            <div className="rounded-lg border border-down/30 bg-down/8 px-3 py-2 text-[11.5px] leading-relaxed text-down">
              {error}
            </div>
          ) : null}

          {google?.enabled ? (
            flow ? (
              <div className="space-y-3 rounded-xl border border-line bg-elevated/40 p-4">
                <p className="text-[12px] text-muted">
                  在打开的 Google 页面输入下面的授权码；没有自动打开就点按钮。
                </p>
                <div className="flex items-center justify-between rounded-lg border border-accent/30 bg-accent/10 px-3 py-2.5">
                  <span className="font-mono text-[20px] font-semibold tracking-[0.18em] text-accent">
                    {flow.user_code}
                  </span>
                  <button
                    type="button"
                    onClick={copyCode}
                    className="inline-flex items-center gap-1 rounded-md border border-accent/30 px-2 py-1 text-[10.5px] text-accent"
                  >
                    {copied ? <Check size={11} /> : <Copy size={11} />}
                    {copied ? '已复制' : '复制'}
                  </button>
                </div>
                <a
                  href={flow.verification_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1.5 text-[11.5px] text-accent hover:underline"
                >
                  <ExternalLink size={12} /> 打开 Google 授权页
                </a>
                <p className="text-[10.5px] text-faint">
                  {poll?.status === 'pending' ? '等待 Google 授权…' : '正在等待授权结果…'}
                </p>
              </div>
            ) : (
              <Button type="button" variant="primary" loading={busy} className="w-full" onClick={startGoogle}>
                <GoogleIcon />
                使用 Google 账号登录
              </Button>
            )
          ) : (
            <div className="rounded-lg border border-line bg-elevated/30 px-3 py-2 text-[11px] leading-relaxed text-muted">
              {google?.configured
                ? 'Google 登录已配置但未启用，请在 /admin 开启。'
                : 'Google 登录尚未配置；请管理员在 /admin 填写 Client ID/Secret 并添加允许账号。'}
            </div>
          )}

          <details className="group rounded-lg border border-line/70 px-3 py-2">
            <summary className="cursor-pointer text-[11px] text-muted marker:content-none">
              使用访问令牌登录（备用）
            </summary>
            <form onSubmit={submit} className="mt-3 space-y-3">
              <Field label="访问令牌">
                <input
                  className="input font-mono"
                  type="password"
                  autoComplete="current-password"
                  value={token}
                  onChange={(event) => setTokenValue(event.target.value)}
                  placeholder="••••••••••••••••••••"
                />
              </Field>
              <button
                type="button"
                onClick={() => setShowServer((open) => !open)}
                className="flex items-center gap-1.5 text-[11px] text-muted transition-colors hover:text-ink"
              >
                <Server size={12} />
                {showServer ? '隐藏服务器地址' : '服务器地址'}
              </button>
              {showServer ? (
                <div>
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
                </div>
              ) : null}
              <Button type="submit" variant="ghost" loading={busy} className="w-full">
                用令牌登录 <ArrowRight size={14} />
              </Button>
            </form>
          </details>

          <div className="flex items-center justify-between text-[10.5px] text-faint">
            <span>{health ?? '服务端不可达'}</span>
            <span className="font-mono">{server || '同源'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
