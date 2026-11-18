import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Artifact, type Run } from './api'

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '发生未知错误'
}

export interface FetchState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

export function useFetch<T>(
  loader: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
  options: { enabled?: boolean; pollMs?: number } = {},
) {
  const { enabled = true, pollMs } = options
  const [state, setState] = useState<FetchState<T>>({ data: null, error: null, loading: true })
  const [version, setVersion] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const reload = useCallback(() => setVersion((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) {
      setState((current) => ({ ...current, loading: false }))
      return
    }
    let cancelled = false
    setState((current) => ({ ...current, loading: true }))
    const run = () => {
      loaderRef
        .current()
        .then((data) => {
          if (!cancelled) setState({ data, error: null, loading: false })
        })
        .catch((error) => {
          if (!cancelled) setState((current) => ({ ...current, error: errorText(error), loading: false }))
        })
    }
    run()
    const timer = pollMs ? window.setInterval(run, pollMs) : 0
    return () => {
      cancelled = true
      if (timer) window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, enabled, pollMs, ...deps])

  return { ...state, reload }
}

const ACTIVE: Run['status'][] = ['queued', 'running']

export function useRunWatch(runId: string | null, onSettled?: (run: Run) => void) {
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const settled = useRef<string | null>(null)
  const callback = useRef(onSettled)
  callback.current = onSettled

  useEffect(() => {
    if (!runId) {
      setRun(null)
      setError(null)
      return
    }
    let cancelled = false
    let timer = 0
    settled.current = null

    const tick = async () => {
      try {
        const result = await api.run(runId)
        if (cancelled) return
        setRun(result.run)
        setError(null)
        if (ACTIVE.includes(result.run.status)) {
          timer = window.setTimeout(tick, 700)
        } else if (settled.current !== result.run.id) {
          settled.current = result.run.id
          callback.current?.(result.run)
        }
      } catch (err) {
        if (!cancelled) setError(errorText(err))
      }
    }
    void tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [runId])

  return { run, error }
}

export function useArtifact(runId: string | null, run: Run | null | undefined) {
  const ready = Boolean(runId) && run?.id === runId && run.status === 'succeeded'
  const state = useFetch<Artifact>(
    () => api.artifact(runId as string),
    [runId, run?.id, run?.status],
    { enabled: ready },
  )
  return ready ? state : { ...state, data: null }
}

export function useInterval(callback: () => void, ms: number | null) {
  const ref = useRef(callback)
  ref.current = callback
  useEffect(() => {
    if (!ms) return
    const id = window.setInterval(() => ref.current(), ms)
    return () => window.clearInterval(id)
  }, [ms])
}

export function statusTone(status: Run['status']): 'neutral' | 'up' | 'down' | 'accent' | 'info' {
  switch (status) {
    case 'succeeded':
      return 'up'
    case 'failed':
      return 'down'
    case 'running':
      return 'accent'
    case 'queued':
      return 'info'
    default:
      return 'neutral'
  }
}


/** True once the element has been near the viewport; stays true afterwards. */
export function useInView<T extends Element>(rootMargin = '240px') {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    if (inView) return
    const node = ref.current
    if (!node) return
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true)
          observer.disconnect()
        }
      },
      { rootMargin },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [inView, rootMargin])

  return [ref, inView] as const
}

/** Mount expensive children only after the first paint (or a short idle delay). */
export function useDeferredMount(delayMs = 16) {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (typeof window === 'undefined') return
    let timer = window.setTimeout(() => setReady(true), delayMs)
    const idle = window.requestIdleCallback?.(
      () => {
        window.clearTimeout(timer)
        setReady(true)
      },
      { timeout: delayMs + 400 },
    )
    return () => {
      window.clearTimeout(timer)
      if (idle != null) window.cancelIdleCallback?.(idle)
    }
  }, [delayMs])
  return ready
}
