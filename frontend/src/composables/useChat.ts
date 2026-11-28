import { ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { api } from '../api'
import { streamChatRun } from '../lib/agui'
import { useToast } from './useToast'
import type {
  AgUiEvent,
  ChatCapabilities,
  ChatCard,
  ChatMessage,
  ChatPageContext,
  ChatPlanCard,
  ChatSession,
  ChatTaskRefCard,
} from '../types'

const config = ref<ChatCapabilities | null>(null)
const drawerOpen = ref(localStorage.getItem('bacmap-chat-drawer') === '1')
const sessions = ref<ChatSession[]>([])
const activeSessionId = ref('')
const messages = ref<ChatMessage[]>([])
const streaming = ref(false)
const queueWaiting = ref(false)
const runtimeMeta = ref<{
  endpoint?: string
  location?: string
  data_class_ceiling?: string
} | null>(null)
const selectedBackendId = ref('builtin')
const includePageContext = ref(true)
const error = ref('')
const loadingSession = ref(false)

let initialized = false
let controller: AbortController | null = null

function persistDrawer() {
  localStorage.setItem('bacmap-chat-drawer', drawerOpen.value ? '1' : '0')
}

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
  persistDrawer()
}

function setDrawer(open: boolean) {
  drawerOpen.value = open
  persistDrawer()
}

const ENTITY_ROUTES: Array<[RegExp, string]> = [
  [/^\/samples\/([^/?#]+)/, 'sample'],
  [/^\/specimens\/([^/?#]+)/, 'specimen'],
  [/^\/isolates\/([^/?#]+)/, 'isolate'],
  [/^\/runs\/([^/?#]+)/, 'run'],
  [/^\/tasks\/([^/?#]+)/, 'task'],
  [/^\/plans\/([^/?#]+)/, 'plan'],
  [/^\/research\/studies\/([^/?#]+)/, 'study'],
  [/^\/research\/sessions\/([^/?#]+)/, 'research_session'],
]

function pageContextFromRoute(
  route: Pick<RouteLocationNormalizedLoaded, 'fullPath' | 'path' | 'meta'>,
): ChatPageContext | null {
  const path = route.path
  for (const [pattern, entityType] of ENTITY_ROUTES) {
    const match = path.match(pattern)
    if (match) {
      return {
        route: route.fullPath,
        entity_type: entityType,
        entity_id: decodeURIComponent(match[1]),
        title: String(route.meta.title ?? ''),
      }
    }
  }
  return null
}

async function init(cap?: ChatCapabilities) {
  if (cap) config.value = cap
  if (!config.value) {
    try {
      config.value = await api.chatConfig()
    } catch {
      return
    }
  }
  if (!config.value?.enabled) return
  if (!config.value.backends.some((b) => b.id === selectedBackendId.value)) {
    const preferred =
      config.value.backends.find(
        (b) => b.id === config.value?.default_backend && b.available,
      ) ?? config.value.backends.find((b) => b.available)
    if (preferred) selectedBackendId.value = preferred.id
  }
  if (initialized) return
  initialized = true
  await refreshSessions()
}

async function refreshSessions() {
  if (!config.value?.enabled) return
  try {
    const body = await api.listChatSessions()
    sessions.value = body.items
  } catch {
    // 会话列表失败不打断控制台。
  }
}

async function selectSession(id: string) {
  if (!id || loadingSession.value) return
  activeSessionId.value = id
  loadingSession.value = true
  error.value = ''
  try {
    const body = await api.getChatSession(id)
    messages.value = body.messages
    if (body.session.backend_id) selectedBackendId.value = body.session.backend_id
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
    messages.value = []
  } finally {
    loadingSession.value = false
  }
}

function newSession() {
  activeSessionId.value = ''
  messages.value = []
  error.value = ''
}

async function renameSession(id: string, title: string) {
  try {
    const updated = await api.updateChatSession(id, { title })
    const row = sessions.value.find((s) => s.session_id === id)
    if (row) row.title = updated.title
  } catch (exc) {
    useToast().err(exc instanceof Error ? exc.message : String(exc))
  }
}

async function removeSession(id: string) {
  try {
    await api.deleteChatSession(id)
    sessions.value = sessions.value.filter((s) => s.session_id !== id)
    if (activeSessionId.value === id) newSession()
  } catch (exc) {
    useToast().err(exc instanceof Error ? exc.message : String(exc))
  }
}

async function setBackend(id: string) {
  selectedBackendId.value = id
  if (!activeSessionId.value) return
  try {
    await api.updateChatSession(activeSessionId.value, { backend_id: id })
  } catch {
    // 后端偏好写失败不影响对话。
  }
}

function localMessage(role: ChatMessage['role'], content: string): ChatMessage {
  return {
    message_id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    session_id: activeSessionId.value,
    role,
    content,
    thinking: '',
    tool_calls: [],
    cards: [],
    backend_id: '',
    created_at: new Date().toISOString(),
  }
}

function upsertCard(cards: ChatCard[], card: ChatCard): void {
  if (card.kind === 'bacmap.plan_card') {
    const plan = card as ChatPlanCard
    // 同一 plan 的 revise/get 只保留最新版本的卡片。
    const idx = cards.findIndex(
      (c) => c.kind === 'bacmap.plan_card' && (c as ChatPlanCard).plan_id === plan.plan_id,
    )
    if (idx >= 0) cards.splice(idx, 1, card)
    else cards.push(card)
    return
  }
  if (card.kind === 'bacmap.task_ref') {
    const ref = card as ChatTaskRefCard
    const idx = cards.findIndex(
      (c) => c.kind === 'bacmap.task_ref' && (c as ChatTaskRefCard).task_id === ref.task_id,
    )
    if (idx >= 0) cards.splice(idx, 1, card)
    else cards.push(card)
    return
  }
  cards.push(card)
}

function applyEvent(ev: AgUiEvent, draft: ChatMessage): void {
  switch (ev.type) {
    case 'STATE_SNAPSHOT': {
      const snap = ev.snapshot as Record<string, unknown>
      runtimeMeta.value = {
        endpoint: typeof snap.endpoint === 'string' ? snap.endpoint : undefined,
        location: typeof snap.location === 'string' ? snap.location : undefined,
        data_class_ceiling:
          typeof snap.data_class_ceiling === 'string' ? snap.data_class_ceiling : undefined,
      }
      break
    }
    case 'THINKING_TEXT_MESSAGE_CONTENT':
      draft.thinking += ev.delta
      break
    case 'TEXT_MESSAGE_CONTENT':
      draft.content += ev.delta
      break
    case 'TOOL_CALL_START':
      draft.tool_calls.push({
        id: ev.toolCallId,
        name: ev.toolCallName,
        args: '',
        result: '',
        done: false,
      })
      break
    case 'TOOL_CALL_ARGS': {
      const call = draft.tool_calls.find((c) => c.id === ev.toolCallId)
      if (call) call.args += ev.delta
      break
    }
    case 'TOOL_CALL_END': {
      const call = draft.tool_calls.find((c) => c.id === ev.toolCallId)
      if (call) call.done = true
      break
    }
    case 'TOOL_CALL_RESULT': {
      const call = draft.tool_calls.find((c) => c.id === ev.toolCallId)
      if (call) {
        call.result = ev.content
        call.done = true
      }
      break
    }
    case 'CUSTOM': {
      if (ev.name === 'bacmap.queue_status') {
        const value = ev.value as { queued?: boolean }
        queueWaiting.value = value.queued === true
      } else if (ev.name === 'bacmap.plan_card' || ev.name === 'bacmap.task_ref') {
        const value = ev.value as Record<string, unknown>
        upsertCard(draft.cards, { kind: ev.name, ...value } as ChatCard)
      }
      break
    }
    case 'RUN_ERROR':
      error.value = ev.message
      break
    default:
      break
  }
}

async function sendMessage(text: string, pageContext: ChatPageContext | null) {
  const content = text.trim()
  if (!content || streaming.value) return
  error.value = ''
  if (!activeSessionId.value) {
    try {
      const session = await api.createChatSession({ backend_id: selectedBackendId.value })
      activeSessionId.value = session.session_id
      await refreshSessions()
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : String(exc)
      return
    }
  }
  messages.value.push(localMessage('user', content))
  const draft = localMessage('assistant', '')
  draft.streaming = true
  draft.backend_id = selectedBackendId.value
  messages.value.push(draft)

  streaming.value = true
  queueWaiting.value = false
  controller = new AbortController()
  let aborted = false
  try {
    await streamChatRun({
      sessionId: activeSessionId.value,
      message: content,
      backendId: selectedBackendId.value,
      pageContext: includePageContext.value ? pageContext : null,
      signal: controller.signal,
      onEvent: (ev) => applyEvent(ev, draft),
    })
  } catch (exc) {
    if (exc instanceof DOMException && exc.name === 'AbortError') {
      aborted = true
    } else {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    streaming.value = false
    queueWaiting.value = false
    controller = null
    draft.streaming = false
    void refreshSessions()
    if (!aborted && activeSessionId.value) {
      // 与服务端持久化对齐（真实 message_id / tool_calls / cards）。
      try {
        const body = await api.getChatSession(activeSessionId.value)
        messages.value = body.messages
      } catch {
        // 保留本地草稿，不打断。
      }
    }
  }
}

function stopStreaming() {
  controller?.abort()
}

async function confirmPlanCard(card: ChatPlanCard) {
  const toast = useToast()
  try {
    const rec = await api.confirmPlan(card.plan_id, {
      version: card.version,
      plan_hash: card.plan_hash,
      confirmer: 'web',
    })
    card.state = rec.state
    card.task_ids = rec.task_ids ?? []
    toast.ok(`计划 ${card.plan_id.slice(0, 8)} 已确认提交`)
  } catch (exc) {
    toast.err(exc instanceof Error ? exc.message : String(exc))
  }
}

async function rejectPlanCard(card: ChatPlanCard, reason: string) {
  const toast = useToast()
  try {
    const rec = await api.rejectPlan(card.plan_id, { version: card.version, reason })
    card.state = rec.state
    toast.info(`计划 ${card.plan_id.slice(0, 8)} 已拒绝`)
  } catch (exc) {
    toast.err(exc instanceof Error ? exc.message : String(exc))
  }
}

export function useChat() {
  return {
    config,
    drawerOpen,
    sessions,
    activeSessionId,
    messages,
    streaming,
    queueWaiting,
    runtimeMeta,
    selectedBackendId,
    includePageContext,
    error,
    loadingSession,
    toggleDrawer,
    setDrawer,
    pageContextFromRoute,
    init,
    refreshSessions,
    selectSession,
    newSession,
    renameSession,
    removeSession,
    setBackend,
    sendMessage,
    stopStreaming,
    confirmPlanCard,
    rejectPlanCard,
  }
}
