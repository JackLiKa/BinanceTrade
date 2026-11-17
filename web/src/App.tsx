import { Activity } from 'lucide-react'
import { AppProvider, useApp } from './store'
import { useRoute } from './router'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Overview } from './pages/Overview'
import { Market } from './pages/Market'
import { Strategy } from './pages/Strategy'
import { Backtest } from './pages/Backtest'
import { Paper } from './pages/Paper'
import { Live } from './pages/Live'
import { Orders } from './pages/Orders'
import { Positions } from './pages/Positions'
import { Risk } from './pages/Risk'
import { Quality } from './pages/Quality'
import { Settings } from './pages/Settings'

function Splash() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-4 bg-base">
      <div className="relative grid h-12 w-12 place-items-center rounded-xl border border-accent/25 bg-accent/10">
        <Activity size={22} className="text-accent" />
        <span className="absolute inset-0 animate-ping rounded-xl border border-accent/20" />
      </div>
      <div className="text-center">
        <p className="text-[13px] font-semibold tracking-wide text-ink">Gridtrade</p>
        <p className="mt-1 text-[10.5px] uppercase tracking-[0.2em] text-faint">正在恢复会话</p>
      </div>
    </div>
  )
}

function Shell() {
  const { session, loading } = useApp()
  const route = useRoute()

  if (loading) return <Splash />
  if (!session) return <Login />

  return (
    <Layout>
      {route === 'overview' ? (
        <Overview />
      ) : route === 'market' ? (
        <Market />
      ) : route === 'strategy' ? (
        <Strategy />
      ) : route === 'backtest' ? (
        <Backtest />
      ) : route === 'paper' ? (
        <Paper />
      ) : route === 'live' ? (
        <Live />
      ) : route === 'orders' ? (
        <Orders />
      ) : route === 'positions' ? (
        <Positions />
      ) : route === 'risk' ? (
        <Risk />
      ) : route === 'quality' ? (
        <Quality />
      ) : (
        <Settings />
      )}
    </Layout>
  )
}

export function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  )
}
