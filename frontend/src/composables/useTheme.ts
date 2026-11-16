import { computed, ref } from 'vue'

export type ThemePreference = 'dark' | 'light' | 'gray' | 'system'
export type ResolvedTheme = 'dark' | 'light' | 'gray'

const STORAGE_KEY = 'bacmap-theme'
// 报告页是服务端注入主题的独立 HTML（sandbox CSP 禁脚本）：把控制台主题
// 同步到 cookie，直接访问 /samples/{id}/report 也能跟随当前主题。
const THEME_COOKIE = 'bacmap-theme'
const preference = ref<ThemePreference>('dark')
const systemDark = ref(true)
let initialized = false

function normalize(value: string | null): ThemePreference {
  return value === 'light' || value === 'gray' || value === 'system' || value === 'dark'
    ? value
    : 'dark'
}

function resolveTheme(): ResolvedTheme {
  if (preference.value === 'system') return systemDark.value ? 'dark' : 'light'
  return preference.value
}

function applyTheme() {
  const resolved = resolveTheme()
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved === 'dark' ? 'dark' : 'light'
  try {
    document.cookie = `${THEME_COOKIE}=${resolved}; path=/; max-age=31536000; SameSite=Lax`
  } catch {
    // cookie 不可用时报告退回默认暗色主题。
  }
}

export function initTheme(): void {
  if (initialized) return
  initialized = true
  try {
    preference.value = normalize(localStorage.getItem(STORAGE_KEY))
  } catch {
    preference.value = 'dark'
  }
  if (typeof window !== 'undefined' && window.matchMedia) {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    systemDark.value = media.matches
    media.addEventListener('change', (event) => {
      systemDark.value = event.matches
      if (preference.value === 'system') applyTheme()
    })
  }
  applyTheme()
}

export function useTheme() {
  initTheme()
  const resolved = computed<ResolvedTheme>(() => resolveTheme())

  function setTheme(next: ThemePreference) {
    preference.value = next
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage 不可用时仅当前会话生效。
    }
    applyTheme()
  }

  function toggle() {
    const order: ResolvedTheme[] = ['dark', 'light', 'gray']
    setTheme(order[(order.indexOf(resolved.value) + 1) % order.length])
  }

  return { preference, resolved, setTheme, toggle }
}
