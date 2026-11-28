import { ApiError, csrfToken } from '../api'
import { appUrl } from './format'
import type { AgUiEvent, ChatPageContext } from '../types'

/**
 * 以 SSE 流式消费一次对话运行（AG-UI 事件逐条回调）。
 * 与 api.ts 同纪律：401 跳登录页；非 2xx 抛 ApiError；跨 chunk 拼帧。
 */
export async function streamChatRun(opts: {
  sessionId: string
  message: string
  backendId?: string
  pageContext?: ChatPageContext | null
  signal?: AbortSignal
  onEvent: (ev: AgUiEvent) => void
}): Promise<void> {
  const body: Record<string, unknown> = { message: opts.message }
  if (opts.backendId) body.backend_id = opts.backendId
  if (opts.pageContext) body.page_context = opts.pageContext

  const response = await fetch(
    appUrl(`/api/v1/chat/sessions/${encodeURIComponent(opts.sessionId)}/run`),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-CSRF-Token': csrfToken(),
      },
      credentials: 'same-origin',
      body: JSON.stringify(body),
      signal: opts.signal ?? null,
    },
  )
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.assign(appUrl(`/console/login?next=${next}`))
    throw new ApiError(401, 'unauthorized', '需要登录')
  }
  if (!response.ok) {
    let message = response.statusText
    let code = 'http_error'
    try {
      const record = (await response.json()) as Record<string, unknown>
      code = String(record.code ?? 'http_error')
      message = String(record.error ?? record.detail ?? message)
    } catch {
      // 非 JSON 错误体：保留 statusText。
    }
    throw new ApiError(response.status, code, message)
  }
  if (!response.body) {
    throw new ApiError(response.status, 'http_error', '响应不含流式正文')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = drainFrames(buffer, opts.onEvent)
  }
  buffer += decoder.decode()
  drainFrames(buffer, opts.onEvent, true)
}

function drainFrames(
  buffer: string,
  onEvent: (ev: AgUiEvent) => void,
  flush = false,
): string {
  // SSE 帧以空行分隔（\n\n 或 \r\n\r\n）。
  const normalized = buffer.replace(/\r\n/g, '\n')
  let rest = normalized
  for (;;) {
    const idx = rest.indexOf('\n\n')
    if (idx < 0) break
    const frame = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    emitFrame(frame, onEvent)
  }
  if (flush && rest.trim()) {
    emitFrame(rest, onEvent)
    return ''
  }
  // 保留与原文一致的尾部（未完成的帧）；换行已在解析时归一化。
  return rest
}

function emitFrame(frame: string, onEvent: (ev: AgUiEvent) => void) {
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }
  if (!dataLines.length) return
  try {
    onEvent(JSON.parse(dataLines.join('\n')) as AgUiEvent)
  } catch {
    // 非 JSON/未知帧：忽略，连接保持。
  }
}
