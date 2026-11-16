import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { api, ApiError, getToken, setToken, streamUrl, type MarketSnapshot, type ModeInfo, type Session } from './api'

interface Toast {
  id: number
  text: string
  tone: 'error' | 'ok' | 'info'
}

interface AppState {
  session: Session | null
  loading: boolean
  error: string | null
  symbol: string
  setSymbol: (symbol: string) => void
  snapshot: MarketSnapshot | null
  connected: boolean
  lastBeat: number
  refreshSession: () => Promise<void>
  signIn: (token: string) => Promise<void>
  signOut: () => Promise<void>
  killSwitch: boolean
  setKillSwitch: (engaged: boolean) => Promise<void>
  toast: (text: string, tone?: Toast['tone']) => void
  toasts: Toast[]
  dismiss: (id: number) => void
  modes: Record<string, ModeInfo>
}

const AppContext = createContext<AppState | null>(null)
const SYMBOL_KEY = 'gridtrade.symbol'

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [symbol, setSymbolState] = useState(() => localStorage.getItem(SYMBOL_KEY) ?? '')
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastBeat, setLastBeat] = useState(0)
  const [killSwitch, setKill] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = ++toastId.current
    setToasts((list) => [...list.slice(-2), { id, text, tone }])
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), 5200)
  }, [])

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const refreshSession = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.session()
      setSession(data)
      setKill(data.kill_switch)
      setSymbolState((current) => {
        if (current && data.symbols.includes(current)) return current
        return data.symbol
      })
      setError(null)
    } catch (err) {
      setSession(null)
      setError(err instanceof ApiError ? err.message : '会话初始化失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (getToken()) void refreshSession()
    else setLoading(false)
  }, [refreshSession])

  const setSymbol = useCallback((next: string) => {
    setSymbolState(next)
    localStorage.setItem(SYMBOL_KEY, next)
    setSnapshot(null)
  }, [])

  const signIn = useCallback(
    async (token: string) => {
      await api.login(token)
      setToken(token)
      await refreshSession()
    },
    [refreshSession],
  )

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      /* cookie may already be gone */
    }
    setToken('')
    setSession(null)
    setSnapshot(null)
  }, [])

  const setKillSwitch = useCallback(
    async (engaged: boolean) => {
      const result = await api.setKillSwitch(engaged)
      setKill(result.kill_switch)
      toast(engaged ? '紧急停止已触发' : '紧急停止已解除', engaged ? 'error' : 'ok')
    },
    [toast],
  )

  const activeSymbol = symbol || session?.symbol || ''

  // Market stream: reconnect with backoff, poll once when the socket is down.
  useEffect(() => {
    if (!session || !activeSymbol) return
    let socket: WebSocket | null = null
    let closed = false
    let retry = 0
    let timer = 0

    const connect = () => {
      if (closed) return
      try {
        socket = new WebSocket(streamUrl(activeSymbol))
      } catch {
        schedule()
        return
      }
      socket.onopen = () => {
        retry = 0
        setConnected(true)
      }
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data as string)
          if (payload?.type === 'market' && payload.data) {
            setSnapshot(payload.data as MarketSnapshot)
            setLastBeat(Date.now())
          }
        } catch {
          /* ignore malformed frames */
        }
      }
      socket.onclose = () => {
        setConnected(false)
        if (!closed) schedule()
      }
      socket.onerror = () => socket?.close()
    }

    const schedule = () => {
      retry += 1
      const delay = Math.min(15000, 1000 * 2 ** Math.min(retry, 4))
      timer = window.setTimeout(connect, delay)
    }

    const prime = async () => {
      try {
        const data = await api.snapshot(activeSymbol)
        setSnapshot(data)
        setLastBeat(Date.now())
      } catch {
        /* the socket will fill this in */
      }
    }

    void prime()
    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      socket?.close()
      setConnected(false)
    }
  }, [session, activeSymbol])

  const value = useMemo<AppState>(
    () => ({
      session,
      loading,
      error,
      symbol: activeSymbol,
      setSymbol,
      snapshot,
      connected,
      lastBeat,
      refreshSession,
      signIn,
      signOut,
      killSwitch,
      setKillSwitch,
      toast,
      toasts,
      dismiss,
      modes: session?.modes ?? {},
    }),
    [
      session,
      loading,
      error,
      activeSymbol,
      setSymbol,
      snapshot,
      connected,
      lastBeat,
      refreshSession,
      signIn,
      signOut,
      killSwitch,
      setKillSwitch,
      toast,
      toasts,
      dismiss,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppState {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used inside AppProvider')
  return context
}
