import { reactive } from 'vue'

export interface Toast {
  id: number
  kind: 'ok' | 'err' | 'info'
  message: string
}

const state = reactive<{ items: Toast[] }>({ items: [] })
let nextId = 1

function push(kind: Toast['kind'], message: string) {
  const id = nextId++
  state.items.push({ id, kind, message })
  window.setTimeout(() => dismiss(id), kind === 'err' ? 6000 : 4000)
}

export function dismiss(id: number) {
  const index = state.items.findIndex((t) => t.id === id)
  if (index >= 0) state.items.splice(index, 1)
}

export function useToast() {
  return {
    items: state.items,
    ok: (message: string) => push('ok', message),
    err: (message: string) => push('err', message),
    info: (message: string) => push('info', message),
    dismiss,
  }
}
