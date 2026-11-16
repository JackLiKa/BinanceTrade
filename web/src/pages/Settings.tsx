import { useState, type FormEvent } from 'react'
import { CheckCircle2, Database, KeyRound, Lock, LogOut, Server, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api, getServer, getToken, setServer, setToken, type ModeInfo } from '../api'
import { Badge, Button, Card, CardHead, ErrorNote, Field, Skeleton, Stat, Toggle } from '../components/ui'
import { cx, fmtDate, fmtDuration, fmtTime } from '../format'
import { errorText, useFetch } from '../hooks'
import { useApp } from '../store'
import { auditLabel } from '../labels'

const modeLabels: Record<string, string> = {
  research: '研究',
  paper: '模拟',
  live: '实盘',
}

function ModeRow({ name, info }: { name: string; info: ModeInfo }) {
  const available = info.enabled
  return (
    <div className="flex items-start gap-3 border-t border-line-soft py-3 first:border-0 first:pt-0 last:pb-0">
      <span
        className={cx(
          'mt-[2px] grid h-6 w-6 shrink-0 place-items-center rounded-md border',
          available
            ? 'border-up/30 bg-up/10 text-up'
            : info.locked
              ? 'border-line bg-elevated text-faint'
              : 'border-line bg-elevated text-faint',
        )}
      >
        {info.locked ? <Lock size={11} /> : <CheckCircle2 size={11} />}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] font-medium capitalize text-ink">{modeLabels[name] ?? name}</span>
          <Badge tone={available ? 'up' : info.locked ? 'neutral' : 'warn'}>
            {available ? '可用' : info.locked ? '已锁定' : '规划中'}
          </Badge>
        </div>
        <p className="mt-0.5 text-[10.5px] leading-relaxed text-faint">{info.detail}</p>
      </div>
    </div>
  )
}

export function Settings() {
  const { session, signOut, toast, refreshSession, killSwitch, setKillSwitch } = useApp()
  const settings = useFetch(() => api.settings(), [])
  const audit = useFetch(() => api.audit(30), [], { pollMs: 30_000 })

  const [server, setServerValue] = useState(() => getServer())
  const [token, setTokenValue] = useState(() => getToken())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [killBusy, setKillBusy] = useState(false)

  const data = settings.data

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!token.trim()) {
      setError('请输入 var/token 中的访问令牌。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      setServer(server)
      setToken(token.trim())
      const next = await api.session()
      await refreshSession()
      toast(`已连接到 ${next.symbol} · ${next.symbols.length} 个交易对`, 'ok')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleKill = async (engaged: boolean) => {
    setKillBusy(true)
    try {
      await setKillSwitch(engaged)
    } catch (err) {
      toast(errorText(err), 'error')
    } finally {
      setKillBusy(false)
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1.25fr_1fr]">
      <div className="space-y-4">
        <Card>
          <CardHead
            title="连接"
            hint="将该应用指向 FastAPI 服务端。由 API 自身提供页面时，地址留空即可。"
            right={<Badge tone={session ? 'up' : 'down'}>{session ? '已认证' : '未登录'}</Badge>}
          />
          <form onSubmit={save} className="space-y-3.5">
            <Field label="服务器地址" hint="局域网 IP、Tailscale 名称或 HTTPS 隧道；末尾无需斜杠。">
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
            </Field>
            <Field label="访问令牌" hint="仅保存在本设备；服务端同时会设置 httpOnly Cookie。">
              <input
                className="input font-mono"
                type="password"
                value={token}
                onChange={(event) => setTokenValue(event.target.value)}
                placeholder="••••••••••••••••••••"
                autoComplete="current-password"
              />
            </Field>
            {error ? <ErrorNote>{error}</ErrorNote> : null}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button type="submit" variant="primary" loading={busy}>
                <KeyRound size={13} /> 保存并重连
              </Button>
              <Button type="button" variant="ghost" onClick={() => void signOut()}>
                <LogOut size={13} /> 退出登录
              </Button>
            </div>
          </form>
          <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line-soft pt-4 text-[11px]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-faint">来源</span>
              <span className="truncate font-mono text-muted">{server || '同源'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-faint">令牌</span>
              <span className="font-mono text-muted">
                {data?.auth.token_hint ?? (token ? `${token.slice(0, 4)}…` : '无')}
              </span>
            </div>
          </div>
        </Card>

        <Card>
          <CardHead
            title="执行模式"
            hint="实盘交易有意不提供：无交易所适配器、无持仓对账、无 listenKey 续期。"
            right={<Badge tone="warn">仅研究</Badge>}
          />
          {data ? (
            <div>
              {(['research', 'paper', 'live'] as const).map((mode) =>
                data.modes[mode] ? <ModeRow key={mode} name={mode} info={data.modes[mode]} /> : null,
              )}
            </div>
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
          <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-[#f0b90b]/25 bg-[#f0b90b]/6 px-3 py-2.5 text-[10.5px] leading-relaxed text-[#f0b90b]">
            <Lock size={12} className="mt-[2px] shrink-0" />
            解锁实盘需要经过认证的订单适配器、持仓对账、订单状态恢复与 listenKey 续期，当前版本均未提供。
          </div>
        </Card>

        <Card>
          <CardHead
            title="审计日志"
            hint="记录每次登录、任务提交、紧急停止变更与设置写入。"
            right={
              <button
                onClick={audit.reload}
                className="text-[11px] text-accent transition-opacity hover:opacity-80"
              >
                刷新
              </button>
            }
          />
          {audit.error ? (
            <ErrorNote>{audit.error}</ErrorNote>
          ) : audit.data?.entries.length ? (
            <div className="max-h-[300px] overflow-y-auto pr-1">
              {audit.data.entries.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-start gap-3 border-t border-line-soft py-2 text-[11px] first:border-0 first:pt-0"
                >
                  <span className="w-28 shrink-0 font-mono text-[10px] text-faint">
                    {fmtTime(entry.ts)}
                  </span>
                  <Badge
                    tone={entry.action.includes('kill') ? 'down' : entry.action.includes('login') ? 'info' : 'neutral'}
                  >
                    {auditLabel(entry.action)}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-muted">
                    {entry.detail ?? '—'}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-[11.5px] text-muted">暂无审计记录。</p>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <Card>
          <CardHead
            title="服务端"
            hint="由 API 进程上报的运行时信息。"
            right={
              data?.paths.web_built ? (
                <Badge tone="up">已构建 SPA</Badge>
              ) : (
                <Badge tone="warn">未构建</Badge>
              )
            }
          />
          {data ? (
            <div className="grid grid-cols-2 gap-4">
              <Stat label="版本" value={data.version} mono={false} />
              <Stat label="运行时长" value={fmtDuration(data.server.uptime_s)} mono={false} />
              <Stat label="主机" value={data.server.host} mono={false} />
              <Stat label="端口" value={data.server.port} />
              <Stat label="标的" value={data.symbol} />
              <Stat label="周期" value={data.intervals.join(' · ')} mono={false} />
            </div>
          ) : (
            <Skeleton className="h-32 w-full" />
          )}
          {data ? (
            <div className="mt-4 space-y-2 border-t border-line-soft pt-3 text-[10.5px]">
              <div className="flex items-start justify-between gap-3">
                <span className="text-faint">CORS</span>
                <div className="flex flex-wrap justify-end gap-1">
                  {data.server.cors_origins.length ? (
                    data.server.cors_origins.map((origin) => (
                      <span key={origin} className="rounded border border-line px-1.5 py-0.5 font-mono text-[9.5px] text-muted">
                        {origin}
                      </span>
                    ))
                  ) : (
                    <span className="font-mono text-muted">仅同源</span>
                  )}
                </div>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-faint">Cookie</span>
                <span className="font-mono text-muted">{data.auth.cookie} · httpOnly</span>
              </div>
            </div>
          ) : null}
        </Card>

        <Card>
          <CardHead title="存储与路径" hint="所有数据均保留在本地，遥测不会离开本机。" />
          {data ? (
            <div className="space-y-2.5 text-[11px]">
              {[
                ['数据集', data.paths.data],
                ['状态', data.paths.var],
                ['Web 构建', data.paths.web],
              ].map(([label, value]) => (
                <div key={label} className="flex items-start justify-between gap-3 border-b border-line-soft pb-2 last:border-0 last:pb-0">
                  <span className="shrink-0 text-muted">{label}</span>
                  <span className="truncate font-mono text-[10px] text-faint" title={value}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <Skeleton className="h-24 w-full" />
          )}
          <div className="mt-4 grid grid-cols-2 gap-4 border-t border-line-soft pt-3">
            <Stat label="标的数" value={data?.symbols.length ?? '—'} sub={data?.symbols.join(', ')} mono={false} />
            <Stat label="认证" value={data?.auth.mode ?? '—'} sub="单操作员" mono={false} />
          </div>
        </Card>

        <Card>
          <CardHead
            title="紧急停止"
            hint="与顶栏控制相同，仅多一步确认。"
            right={<Badge tone={killSwitch ? 'down' : 'up'}>{killSwitch ? '已触发' : '待命'}</Badge>}
          />
          <div
            className={cx(
              'flex items-start gap-3 rounded-lg border px-3 py-3',
              killSwitch ? 'border-down/35 bg-down/8' : 'border-line-soft bg-[#12151a]',
            )}
          >
            {killSwitch ? (
              <ShieldAlert size={16} className="mt-[1px] shrink-0 text-down" />
            ) : (
              <ShieldCheck size={16} className="mt-[1px] shrink-0 text-up" />
            )}
            <p className="flex-1 text-[11px] leading-relaxed text-muted">
              {killSwitch
                ? '新的模拟订单已被拦截。研究任务仍可运行，但结果仅供参考。'
                : '允许模拟下单；实盘在 API 层仍保持锁定。'}
            </p>
            <Toggle checked={killSwitch} onChange={(next) => void toggleKill(next)} disabled={killBusy} />
          </div>
        </Card>

        <Card>
          <CardHead title="关于" hint="Gridtrade 引擎的研究终端。" />
          <div className="space-y-2 text-[11px] leading-relaxed text-muted">
            <div className="flex items-center gap-2">
              <Database size={12} className="text-accent" />
              本地 Parquet K 线、资金费率归档与 SQLite 运行记录库。
            </div>
            <div className="flex items-center gap-2">
              <Server size={12} className="text-info" />
              FastAPI 后端，支持 Bearer / Cookie 认证与 WebSocket 行情推送。
            </div>
            <div className="flex items-center gap-2">
              <Lock size={12} className="text-faint" />
              无实盘交易适配器，仅提供模拟执行。
            </div>
          </div>
          <p className="mt-4 border-t border-line-soft pt-3 font-mono text-[9.5px] leading-relaxed text-faint">
            客户端构建 {data?.version ?? '—'} · 令牌保存在 localStorage · 将面板暴露到 tailnet 之外时请使用 HTTPS。
          </p>
        </Card>
      </div>
    </div>
  )
}
