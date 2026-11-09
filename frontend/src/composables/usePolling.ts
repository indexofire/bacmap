import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

export function usePolling(
  fn: () => Promise<void> | void,
  intervalMs: number,
  active: () => boolean,
) {
  const busy = ref(false)
  let timer: number | undefined
  let stopped = false

  async function tick() {
    if (stopped) return
    if (active() && !busy.value) {
      busy.value = true
      try {
        await fn()
      } catch {
        // 页面自行展示错误；轮询不叠加 toast。
      } finally {
        busy.value = false
      }
    }
    if (!stopped) timer = window.setTimeout(tick, intervalMs)
  }

  onMounted(() => {
    stopped = false
    timer = window.setTimeout(tick, intervalMs)
  })

  onBeforeUnmount(() => {
    stopped = true
    if (timer) window.clearTimeout(timer)
  })

  watch(
    () => active(),
    (on) => {
      if (on && !timer && !stopped) timer = window.setTimeout(tick, intervalMs)
    },
  )

  return { busy }
}
