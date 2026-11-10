import { computed, ref } from 'vue'

export type ThemePreference = 'dark' | 'light' | 'system'
export type ResolvedTheme = 'dark' | 'light'

const STORAGE_KEY = 'bacmap-theme'
const preference = ref<ThemePreference>('dark')
const systemDark = ref(true)
let initialized = false

function normalize(value: string | null): ThemePreference {
  return value === 'light' || value === 'system' || value === 'dark' ? value : 'dark'
}

function resolveTheme(): ResolvedTheme {
  if (preference.value === 'system') return systemDark.value ? 'dark' : 'light'
  return preference.value
}

function applyTheme() {
  const resolved = resolveTheme()
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved
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
    setTheme(resolved.value === 'dark' ? 'light' : 'dark')
  }

  return { preference, resolved, setTheme, toggle }
}
