const AUDIT_LABELS: Record<string, string> = {
  'server.start': '服务启动',
  'server.stop': '服务停止',
  'auth.failed': '登录失败',
  'auth.login': '登录成功',
  'auth.logout': '退出登录',
  'run.replay.queued': '回放任务入队',
  'run.walkforward.queued': '前向滚动入队',
  'run.sweep.queued': '参数扫描入队',
  'run.cancel': '任务取消',
  'risk.kill_switch': '紧急停止切换',
  'settings.write': '设置已保存',
}

export function auditLabel(action: string): string {
  return AUDIT_LABELS[action] ?? action
}
