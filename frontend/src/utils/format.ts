export function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatBytes(value?: number | null): string {
  if (value == null || value < 0) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export function shortId(value?: string | null): string {
  if (!value) return '—'
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-3)}` : value
}

const statusLabels: Record<string, string> = {
  active: '启用',
  archived: '已归档',
  building: '构建中',
  cancelled: '已取消',
  completed: '已完成',
  deleting: '删除中',
  degraded: '降级',
  disabled: '已禁用',
  enabled: '已启用',
  failed: '失败',
  generating: '生成中',
  paused: '已暂停',
  queued: '排队中',
  ready: '就绪',
  refused: '已拒答',
  running: '运行中',
  validated: '已验证',
  validating: '验证中',
  'local_only': '仅本地模型',
  'external_allowed': '允许外部模型',
  'external_required': '仅外部模型',
  'dual_engine': '双引擎',
  'elastic_single': 'ES 单引擎',
}

export function statusLabel(value?: string | null): string {
  if (!value) return '—'
  return statusLabels[value] ?? value
}

export function parseLines(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}
