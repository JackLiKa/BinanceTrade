import { useEffect, useState } from 'react'

export const ROUTES = [
  'overview',
  'market',
  'strategy',
  'backtest',
  'paper',
  'live',
  'binance',
  'orders',
  'positions',
  'risk',
  'quality',
  'settings',
] as const

export type RouteName = (typeof ROUTES)[number]

function read(): RouteName {
  const raw = window.location.hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES as readonly string[]).includes(raw) ? (raw as RouteName) : 'overview'
}

export function navigate(route: RouteName): void {
  if (read() === route) return
  window.location.hash = `#/${route}`
}

export function useRoute(): RouteName {
  const [route, setRoute] = useState<RouteName>(read)
  useEffect(() => {
    const onChange = () => {
      setRoute(read())
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', onChange)
    if (!window.location.hash) window.location.hash = '#/overview'
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
