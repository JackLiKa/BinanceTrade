/** Runtime shell detection: the Android WebView app appends GridtradeShell to its UA. */
export function isShellApp(): boolean {
  return typeof navigator !== 'undefined' && navigator.userAgent.includes('GridtradeShell')
}

export function defaultRoute(): 'market' | 'overview' {
  return isShellApp() ? 'market' : 'overview'
}
