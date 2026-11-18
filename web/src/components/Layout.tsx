import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  Bot,
  CandlestickChart,
  Database,
  FlaskConical,
  Info,
  Landmark,
  Bitcoin,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  MoreHorizontal,
  Search,
  Settings as SettingsIcon,
  ShieldAlert,
  Wallet,
  X,
} from 'lucide-react'
import { cx, fmtPct, fmtPrice, timeAgo } from '../format'
import { isShellApp } from '../env'
import { navigate, useRoute, type RouteName } from '../router'
import { useApp } from '../store'
import { Badge, Button, useNow } from './ui'

interface NavItem {
  route: RouteName
  label: string
  short?: string
  icon: typeof LayoutDashboard
  mobile: boolean
}

const NAV: NavItem[] = [
  { route: 'overview', label: '总览', icon: LayoutDashboard, mobile: true },
  { route: 'market', label: '行情', icon: CandlestickChart, mobile: true },
  { route: 'strategy', label: '策略', icon: BarChart3, mobile: false },
  { route: 'backtest', label: '回测实验室', short: '回测', icon: FlaskConical, mobile: true },
  { route: 'paper', label: '模拟盘', icon: Bot, mobile: false },
  { route: 'live', label: '实盘', icon: Landmark, mobile: false },
  { route: 'binance', label: 'Binance 节点', short: 'Binance', icon: Bitcoin, mobile: false },
  { route: 'orders', label: '订单与成交', icon: ListOrdered, mobile: false },
  { route: 'positions', label: '持仓', icon: Wallet, mobile: false },
  { route: 'risk', label: '风控', icon: ShieldAlert, mobile: true },
  { route: 'quality', label: '数据质量', icon: Database, mobile: false },
  { route: 'settings', label: '设置', icon: SettingsIcon, mobile: false },
]

const SHELL_NAV: NavItem[] = [
  { route: 'market', label: '首页', short: '首页', icon: CandlestickChart, mobile: true },
  { route: 'live', label: '实盘', short: '实盘', icon: Landmark, mobile: true },
  { route: 'paper', label: '模拟盘', short: '模拟盘', icon: Bot, mobile: true },
  { route: 'binance', label: 'Binance账户', short: 'Binance', icon: Bitcoin, mobile: true },
  { route: 'overview', label: '数据面板', short: '数据', icon: LayoutDashboard, mobile: true },
]

export const TITLES: Record<RouteName, string> = {
  overview: '总览',
  market: '行情',
  strategy: '策略',
  backtest: '回测实验室',
  paper: '模拟盘',
  live: '实盘',
  binance: 'Binance 节点',
  orders: '订单与成交',
  positions: '持仓',
  risk: '风控',
  quality: '数据质量',
  settings: '设置',
}

function ConnectionPill() {
  const { connected, snapshot } = useApp()
  const live = connected && snapshot?.source === 'binance'
  return (
    <span className="flex items-center gap-2 text-[11px] text-muted">
      <span
        className={cx(
          'inline-block h-1.5 w-1.5 rounded-full',
          live ? 'live-dot' : connected ? 'bg-[#f0b90b]' : 'bg-[#5e6673]',
        )}
      />
      <span>{live ? 'Binance 实时' : connected ? '本地数据' : '重连中'}</span>
    </span>
  )
}

function SymbolSelect() {
  const { session, symbol, setSymbol } = useApp()
  const symbols = session?.symbols ?? []
  if (symbols.length <= 1) {
    return (
      <span className="rounded-md border border-line bg-elevated px-2 py-1 font-mono text-[11px] text-ink">
        {symbol || '—'}
      </span>
    )
  }
  return (
    <select
      value={symbol}
      onChange={(event) => setSymbol(event.target.value)}
      className="rounded-md border border-line bg-elevated px-2 py-1 font-mono text-[11px] text-ink outline-none"
    >
      {symbols.map((item) => (
        <option key={item} value={item}>
          {item}
        </option>
      ))}
    </select>
  )
}

function PriceTicker() {
  const { snapshot, symbol } = useApp()
  const change = snapshot?.change_24h_pct ?? null
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-mono text-[15px] font-semibold tabular-nums text-ink">
        {fmtPrice(snapshot?.mark_price ?? null)}
      </span>
      <span
        className={cx(
          'font-mono text-[11px] tabular-nums',
          change === null ? 'text-muted' : change >= 0 ? 'text-up' : 'text-down',
        )}
      >
        {fmtPct(change)}
      </span>
      <span className="hidden text-[10px] text-faint md:inline">{symbol}</span>
    </div>
  )
}

function KillSwitchButton() {
  const { killSwitch, setKillSwitch, toast } = useApp()
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)

  const engage = async () => {
    setBusy(true)
    try {
      await setKillSwitch(!killSwitch)
      setConfirming(false)
    } catch (err) {
      toast(err instanceof Error ? err.message : '紧急停止操作失败', 'error')
    } finally {
      setBusy(false)
    }
  }

  if (killSwitch) {
    return (
      <Button variant="danger" size="sm" onClick={engage} loading={busy} title="紧急停止已触发">
        <ShieldAlert size={13} /> <span className="hidden sm:inline">已停止</span>
      </Button>
    )
  }
  if (confirming) {
    return (
      <div className="flex items-center gap-1.5">
        <Button variant="danger" size="sm" onClick={engage} loading={busy}>
          确认停止
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
          取消
        </Button>
      </div>
    )
  }
  return (
    <Button variant="outline" size="sm" onClick={() => setConfirming(true)} title="紧急停止">
      <ShieldAlert size={13} /> <span className="hidden sm:inline">紧急停止</span>
    </Button>
  )
}

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { session, setSymbol, killSwitch, setKillSwitch, signOut, toast } = useApp()
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    window.setTimeout(() => inputRef.current?.focus(), 20)
  }, [open])

  const commands = [
    ...NAV.map((item) => ({
      id: item.route,
      label: `前往${item.label}`,
      hint: '页面',
      run: () => navigate(item.route),
    })),
    ...(session?.symbols ?? []).map((item) => ({
      id: `symbol-${item}`,
      label: `切换交易对至 ${item}`,
      hint: '交易对',
      run: () => setSymbol(item),
    })),
    {
      id: 'kill',
      label: killSwitch ? '解除紧急停止' : '触发紧急停止',
      hint: '风控',
      run: () => void setKillSwitch(!killSwitch).catch(() => toast('紧急停止操作失败', 'error')),
    },
    { id: 'logout', label: '退出登录', hint: '会话', run: () => void signOut() },
  ]
  const filtered = commands.filter((command) =>
    command.label.toLowerCase().includes(query.trim().toLowerCase()),
  )

  const close = () => onClose()

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[12vh] backdrop-blur-sm" onClick={close}>
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-panel shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line-soft px-4">
          <Search size={15} className="text-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setIndex(0)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') close()
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setIndex((current) => Math.min(filtered.length - 1, current + 1))
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault()
                setIndex((current) => Math.max(0, current - 1))
              }
              if (event.key === 'Enter') {
                const command = filtered[index]
                if (command) {
                  command.run()
                  close()
                }
              }
            }}
            placeholder="跳转到页面、交易对或操作"
            className="h-12 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:text-faint"
          />
          <kbd className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-faint">esc</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <p className="px-4 py-6 text-center text-[12px] text-muted">无匹配项</p>
          ) : (
            filtered.map((command, i) => (
              <button
                key={command.id}
                onMouseEnter={() => setIndex(i)}
                onClick={() => {
                  command.run()
                  close()
                }}
                className={cx(
                  'flex w-full items-center justify-between px-4 py-2 text-left text-[13px]',
                  i === index ? 'bg-elevated text-ink' : 'text-muted',
                )}
              >
                <span>{command.label}</span>
                <span className="font-mono text-[10px] uppercase tracking-wide text-faint">
                  {command.hint}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function Toasts() {
  const { toasts, dismiss } = useApp()
  return (
    <div className="pointer-events-none fixed bottom-20 right-4 z-50 flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2 md:bottom-6">
      {toasts.map((item) => (
        <div
          key={item.id}
          className={cx(
            'pointer-events-auto flex items-start gap-3 rounded-lg border px-3.5 py-3 text-[12px] shadow-xl',
            item.tone === 'error'
              ? 'border-down/40 bg-[#2a1216] text-[#ff8b9b]'
              : item.tone === 'ok'
                ? 'border-up/35 bg-[#0f2119] text-[#7ce5b6]'
                : 'border-line bg-panel text-ink',
          )}
        >
          <span className="flex-1 leading-relaxed">{item.text}</span>
          <button onClick={() => dismiss(item.id)} className="text-faint hover:text-ink">
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  )
}

export function Layout({ children }: { children: ReactNode }) {
  const shell = isShellApp()
  const route = useRoute()
  const { signOut, lastBeat, snapshot, loading, killSwitch, setKillSwitch, toast, symbol, session } = useApp()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const now = useNow(5000)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    setMoreOpen(false)
  }, [route])

  const mobileNav = shell ? SHELL_NAV : NAV.filter((item) => item.mobile)
  const shellTitles: Partial<Record<RouteName, string>> = {
    market: '行情',
    live: '实盘',
    paper: '模拟盘',
    binance: 'Binance账户',
    overview: '数据面板',
  }
  const title = shell ? (shellTitles[route] ?? TITLES[route]) : TITLES[route]

  return (
    <div className="flex min-h-full bg-base">
      <aside className={cx('fixed inset-y-0 left-0 z-30 w-[228px] flex-col border-r border-line-soft bg-[#0d1014]', shell ? 'hidden' : 'hidden md:flex')}>
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg border border-accent/25 bg-accent/10">
            <Activity size={16} className="text-accent" />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-wide text-ink">Gridtrade</div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-faint">研究终端</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2.5 py-2">
          {NAV.map((item) => {
            const active = item.route === route
            const Icon = item.icon
            return (
              <button
                key={item.route}
                data-route={item.route}
                onClick={() => navigate(item.route)}
                className={cx(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[12.5px] transition-colors',
                  active
                    ? 'bg-elevated text-ink'
                    : 'text-muted hover:bg-[#15181d] hover:text-ink',
                )}
              >
                <Icon size={15} className={active ? 'text-accent' : 'text-faint'} />
                <span className="flex-1 text-left">{item.label}</span>
                {active ? <span className="h-1.5 w-1.5 rounded-full bg-accent" /> : null}
              </button>
            )
          })}
        </nav>
        <div className="space-y-3 px-4 pb-5">
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex w-full items-center gap-2 rounded-lg border border-line bg-elevated px-2.5 py-2 text-[11px] text-faint transition-colors hover:text-muted"
          >
            <Search size={12} />
            <span className="flex-1 text-left">搜索</span>
            <kbd className="rounded border border-line px-1 font-mono text-[9px]">⌘K</kbd>
          </button>
          <div className="rounded-lg border border-line-soft bg-[#12151a] px-3 py-2.5">
            <div className="flex items-center justify-between">
              <span className="label">数据源</span>
              <ConnectionPill />
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px]">
              <span className="text-faint">最后推送</span>
              <span className="num text-muted">
                {snapshot ? timeAgo(lastBeat || Date.now()) : '—'}
              </span>
            </div>
          </div>
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => void signOut()}>
            <LogOut size={13} /> 退出登录
          </Button>
          <p className="px-1 font-mono text-[9.5px] leading-relaxed text-faint">
            回测 · 模拟盘 · Binance 执行节点（只读）
          </p>
        </div>
      </aside>

      <div className={cx('flex min-h-full w-full flex-col', shell ? '' : 'md:pl-[228px]')}>
        <header className="sticky top-0 z-20 border-b border-line-soft bg-base">
          <div className="flex h-14 items-center gap-3 px-3 md:px-6">
            {shell ? (
              <button
                onClick={() => navigate('settings')}
                aria-label="设置"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-elevated text-muted active:bg-panel"
              >
                <SettingsIcon size={17} />
              </button>
            ) : (
              <div className="hidden items-center gap-2 sm:flex md:hidden">
                <div className="grid h-7 w-7 place-items-center rounded-md border border-accent/25 bg-accent/10">
                  <Activity size={13} className="text-accent" />
                </div>
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <h1 className="truncate text-[14px] font-semibold text-ink">{title}</h1>
                <span className="shrink-0">
                  <SymbolSelect />
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-3 text-[10.5px] text-faint">
                <span className={now - lastBeat < 15000 && lastBeat ? 'text-up' : ''}>
                  {snapshot ? `更新于 ${timeAgo(lastBeat || Date.now())}` : '等待数据'}
                </span>
                {snapshot?.last_funding_rate !== null && snapshot?.last_funding_rate !== undefined ? (
                  <span className="hidden font-mono sm:inline">
                    资金费率 {fmtPct((snapshot.last_funding_rate ?? 0) * 100, 4)}
                  </span>
                ) : null}
              </div>
            </div>
            {shell ? (
              <button
                onClick={() => setMoreOpen(true)}
                aria-label="其他信息"
                className="flex h-9 shrink-0 items-center gap-1 rounded-lg border border-line bg-elevated px-2.5 text-[10.5px] text-muted active:bg-panel"
              >
                <Info size={14} /> 其他
              </button>
            ) : (
              <>
                <div className="hidden items-center gap-3 md:flex">
                  <ConnectionPill />
                  <PriceTicker />
                </div>
                <KillSwitchButton />
              </>
            )}
          </div>
        </header>

        <main className={cx('flex-1 px-3 pb-24 pt-3 md:px-6 md:pb-8 md:pt-4', loading && 'opacity-90')}>
          <div className="mx-auto w-full max-w-[1440px] animate-[rise_0.32s_cubic-bezier(0.22,1,0.36,1)_both]">
            {children}
          </div>
        </main>

        <nav className={cx('fixed inset-x-0 bottom-0 z-30 border-t border-line-soft bg-[#0d1014]', shell ? '' : 'md:hidden')}>
          <div className="mx-auto flex max-w-lg items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)]">
            {mobileNav.map((item) => {
              const active = item.route === route
              const Icon = item.icon
              return (
                <button
                  key={item.route}
                  data-route={item.route}
                  onClick={() => navigate(item.route)}
                  className={cx(
                    'flex flex-1 flex-col items-center gap-1 py-2.5 text-[9.5px]',
                    active ? 'text-accent' : 'text-faint',
                  )}
                >
                  <Icon size={18} strokeWidth={active ? 2.2 : 1.8} />
                  {item.short ?? item.label.split(' ')[0]}
                </button>
              )
            })}
            {shell ? null : (
              <button
                onClick={() => setMoreOpen((open) => !open)}
                className={cx(
                  'flex flex-1 flex-col items-center gap-1 py-2.5 text-[9.5px]',
                  moreOpen ? 'text-accent' : 'text-faint',
                )}
              >
                <MoreHorizontal size={18} strokeWidth={1.8} />
                更多
              </button>
            )}
          </div>
        </nav>

        {moreOpen ? (
          <div className={cx('fixed inset-0 z-40', shell ? '' : 'md:hidden')} onClick={() => setMoreOpen(false)}>
            <div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" />
            <div
              className="absolute inset-x-0 bottom-0 max-h-[82vh] overflow-y-auto rounded-t-2xl border-t border-line bg-panel px-3 pb-[calc(env(safe-area-inset-bottom)+16px)] pt-3"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line" />
              {shell ? (
                <>
                  <div className="mb-3 flex items-center justify-between">
                    <h2 className="text-[13px] font-semibold text-ink">其他信息</h2>
                    <button onClick={() => setMoreOpen(false)} className="text-faint">
                      <X size={15} />
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded-xl border border-line-soft bg-elevated px-3 py-2.5">
                      <div className="label">数据源</div>
                      <div className="mt-1"><ConnectionPill /></div>
                    </div>
                    <div className="rounded-xl border border-line-soft bg-elevated px-3 py-2.5">
                      <div className="label">最后推送</div>
                      <div className="num mt-1 text-muted">{snapshot ? timeAgo(lastBeat || Date.now()) : '—'}</div>
                    </div>
                    <div className="rounded-xl border border-line-soft bg-elevated px-3 py-2.5">
                      <div className="label">当前标的</div>
                      <div className="mt-1 font-mono text-ink">{symbol || '—'}</div>
                    </div>
                    <div className="rounded-xl border border-line-soft bg-elevated px-3 py-2.5">
                      <div className="label">版本</div>
                      <div className="mt-1 font-mono text-ink">v{session?.version ?? '—'}</div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2">
                    {NAV.filter((item) => !SHELL_NAV.some((main) => main.route === item.route)).map((item) => {
                      const Icon = item.icon
                      return (
                        <button
                          key={item.route}
                          onClick={() => {
                            navigate(item.route)
                            setMoreOpen(false)
                          }}
                          className={cx(
                            'flex flex-col items-center gap-2 rounded-xl border px-2 py-3 text-[10.5px]',
                            item.route === route
                              ? 'border-accent/30 bg-accent/8 text-accent'
                              : 'border-line-soft bg-elevated text-muted',
                          )}
                        >
                          <Icon size={17} />
                          <span className="text-center leading-tight">{item.label}</span>
                        </button>
                      )
                    })}
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2 rounded-xl border border-line-soft px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <Badge tone={killSwitch ? 'down' : 'neutral'}>{killSwitch ? '紧急停止中' : '运行中'}</Badge>
                      <Button
                        variant={killSwitch ? 'danger' : 'outline'}
                        size="sm"
                        onClick={() => {
                          void setKillSwitch(!killSwitch).catch(() => toast('紧急停止操作失败', 'error'))
                        }}
                      >
                        <ShieldAlert size={13} /> {killSwitch ? '解除停止' : '紧急停止'}
                      </Button>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => void signOut()}>
                      <LogOut size={13} /> 退出
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    {NAV.map((item) => {
                      const Icon = item.icon
                      return (
                        <button
                          key={item.route}
                          onClick={() => {
                            navigate(item.route)
                            setMoreOpen(false)
                          }}
                          className={cx(
                            'flex flex-col items-center gap-2 rounded-xl border px-2 py-3 text-[11px]',
                            item.route === route
                              ? 'border-accent/30 bg-accent/8 text-accent'
                              : 'border-line-soft bg-elevated text-muted',
                          )}
                        >
                          <Icon size={18} />
                          <span className="text-center leading-tight">{item.label}</span>
                        </button>
                      )
                    })}
                  </div>
                  <div className="mt-3 flex items-center justify-between rounded-xl border border-line-soft px-3 py-2.5">
                    <Badge tone="neutral">仅研究</Badge>
                    <Button variant="ghost" size="sm" onClick={() => void signOut()}>
                      <LogOut size={13} /> 退出登录
                    </Button>
                  </div>
                </>
              )}
            </div>
          </div>
        ) : null}
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toasts />
    </div>
  )
}
