export function fmtTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

export function fmtRelative(value: string | null | undefined): string {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return value
  const seconds = Math.round((then - Date.now()) / 1000)
  const abs = Math.abs(seconds)
  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 365 * 24 * 3600],
    ['month', 30 * 24 * 3600],
    ['day', 24 * 3600],
    ['hour', 3600],
    ['minute', 60],
    ['second', 1],
  ]
  const formatter = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' })
  for (const [unit, size] of units) {
    if (abs >= size || unit === 'second') {
      return formatter.format(Math.round(seconds / size), unit)
    }
  }
  return value
}

export function shortId(value: string | null | undefined, size = 12): string {
  if (!value) return '—'
  return value.length > size ? `${value.slice(0, size)}…` : value
}

export function jsonText(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function fmtBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = value
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** Prefix a root-absolute app URL for the DSH reverse-proxy mount. */
export function appUrl(path: string): string {
  if (!path.startsWith('/')) return path
  const mount = window.__BACMAP_MOUNT__
  if (!mount) return path
  if (path === mount || path.startsWith(`${mount}/`)) return path
  return `${mount}${path}`
}
