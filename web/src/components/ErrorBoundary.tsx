import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'

interface Props {
  children: ReactNode
  title?: string
}

interface State {
  error: Error | null
}

/** Keeps a single broken chart/page from turning the whole WebView black. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Visible in adb logcat through the native console bridge.
    console.error('[gridtrade] render error', error.message, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="m-4 rounded-xl border border-down/30 bg-down/5 p-5">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-down">
          <AlertTriangle size={16} /> {this.props.title ?? '页面渲染出错'}
        </div>
        <p className="mt-2 break-words font-mono text-[11px] leading-relaxed text-muted">
          {this.state.error.message || '未知渲染错误'}
        </p>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-[11px] text-ink hover:bg-elevated"
        >
          <RotateCcw size={12} /> 重试渲染
        </button>
      </div>
    )
  }
}
