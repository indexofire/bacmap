<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './Icon.vue'
import ChatPlanCard from './ChatPlanCard.vue'
import TaskProgressSteps from './TaskProgressSteps.vue'
import { renderSafeMarkdown } from '../lib/markdown'
import { useChat } from '../composables/useChat'
import { useTaskEvents } from '../composables/useTaskEvents'
import type { ChatPlanCard as PlanCardT, ChatTaskRefCard } from '../types'
import { shortId } from '../lib/format'

const props = defineProps<{ mode: 'drawer' | 'page' }>()
const emit = defineEmits<{ close: []; expand: []; dock: [] }>()

const chat = useChat()
const taskEvents = useTaskEvents()
const route = useRoute()
const router = useRouter()
const input = ref('')
const feed = ref<HTMLElement | null>(null)
const pinnedBottom = ref(true)

// 步级实时推送：订阅全局事件流，并回填对话中出现的任务引用卡。
void taskEvents.ensureStream()
watch(
  () =>
    chat.messages.value
      .flatMap((m) => m.cards)
      .filter((c) => c.kind === 'bacmap.task_ref')
      .map((c) => (c as ChatTaskRefCard).task_id)
      .join(','),
  (ids) => {
    for (const id of ids.split(',').filter(Boolean)) void taskEvents.backfill(id)
  },
  { immediate: true },
)

function taskState(taskId: string, fallback: string): string {
  return taskEvents.states[taskId] ?? fallback
}

const backends = computed(() => chat.config.value?.backends ?? [])
const pageContext = computed(() => chat.pageContextFromRoute(route))

const starters = [
  '查看最近的分析任务状态',
  '列出已登记的参考基因组',
  '帮我规划一次基因组分析',
]

function isPlanCard(card: { kind: string }): card is PlanCardT {
  return card.kind === 'bacmap.plan_card'
}
function isTaskRef(card: { kind: string }): card is ChatTaskRefCard {
  return card.kind === 'bacmap.task_ref'
}
function md(text: string): string {
  return renderSafeMarkdown(text)
}

function onScroll() {
  const el = feed.value
  if (!el) return
  pinnedBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

watch(
  () => chat.messages.value.map((m) => m.content.length + m.thinking.length).join(','),
  async () => {
    if (!pinnedBottom.value) return
    await nextTick()
    const el = feed.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

watch(
  () => chat.activeSessionId.value,
  async () => {
    await nextTick()
    const el = feed.value
    if (el) el.scrollTop = el.scrollHeight
    pinnedBottom.value = true
  },
)

function submit() {
  const text = input.value
  if (!text.trim() || chat.streaming.value) return
  input.value = ''
  void chat.sendMessage(text, pageContext.value)
}

function onEnter(event: KeyboardEvent) {
  if (event.shiftKey || event.isComposing) return
  event.preventDefault()
  submit()
}

function switchMode() {
  if (props.mode === 'drawer') {
    emit('expand')
    chat.setDrawer(false)
    void router.push('/chat')
  } else {
    emit('dock')
    chat.setDrawer(true)
    void router.push('/')
  }
}

function onSessionPick(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  if (id) void chat.selectSession(id)
  else chat.newSession()
}

function backendLabel(id: string): string {
  const b = backends.value.find((x) => x.id === id)
  if (!b) return id
  return b.available ? b.name : `${b.name}（不可用）`
}
</script>

<template>
  <div class="ws" :class="`ws--${mode}`">
    <div class="ws__bar">
      <select
        v-if="mode === 'drawer' && chat.sessions.value.length"
        class="input ws__sessions"
        :value="chat.activeSessionId.value"
        title="切换会话"
        aria-label="切换会话"
        @change="onSessionPick"
      >
        <option value="">新对话</option>
        <option v-for="s in chat.sessions.value" :key="s.session_id" :value="s.session_id">
          {{ s.title || '未命名会话' }}
        </option>
      </select>
      <select
        v-if="backends.length"
        class="input ws__backend"
        :value="chat.selectedBackendId.value"
        title="对话后端"
        @change="chat.setBackend(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="b in backends" :key="b.id" :value="b.id" :disabled="!b.available" :title="b.reason">
          {{ backendLabel(b.id) }}
        </option>
      </select>
      <span v-if="chat.runtimeMeta.value?.endpoint" class="ws__runtime mono" title="当前端点与数据级别上限">
        {{ chat.runtimeMeta.value.endpoint }} · {{ chat.runtimeMeta.value.data_class_ceiling }}
      </span>
      <span class="ws__spacer" />
      <button class="icon-btn" type="button" title="新对话" aria-label="新对话" @click="chat.newSession()">
        <Icon name="plus" />
      </button>
      <button
        class="icon-btn"
        type="button"
        :title="mode === 'drawer' ? '独立页面' : '右侧抽屉'"
        :aria-label="mode === 'drawer' ? '独立页面' : '右侧抽屉'"
        @click="switchMode"
      >
        <Icon :name="mode === 'drawer' ? 'maximize' : 'minimize'" />
      </button>
      <button
        v-if="mode === 'drawer'"
        class="icon-btn"
        type="button"
        title="关闭"
        aria-label="关闭"
        @click="emit('close')"
      >
        <Icon name="x" />
      </button>
    </div>

    <div ref="feed" class="ws__feed" @scroll="onScroll">
      <div v-if="!chat.messages.value.length" class="ws__empty">
        <Icon name="message-square" :size="28" />
        <p class="muted">bacmap 内置助手：问数据、查任务、规划分析。</p>
        <div class="ws__starters">
          <button
            v-for="s in starters"
            :key="s"
            class="ws__starter"
            type="button"
            @click="input = s"
          >
            {{ s }}
          </button>
        </div>
      </div>

      <div
        v-for="msg in chat.messages.value"
        :key="msg.message_id"
        class="ws__msg"
        :class="`ws__msg--${msg.role}`"
      >
        <template v-if="msg.role === 'user'">
          <div class="ws__bubble ws__bubble--user">{{ msg.content }}</div>
        </template>
        <template v-else>
          <details v-if="msg.thinking" class="ws__thinking" :open="msg.streaming">
            <summary>思考过程（{{ msg.thinking.length }} 字符）</summary>
            <div class="ws__thinking-body">{{ msg.thinking }}</div>
          </details>

          <div v-if="msg.tool_calls.length" class="ws__tools">
            <details v-for="call in msg.tool_calls" :key="call.id" class="ws__tool">
              <summary>
                <span class="mono">{{ call.name }}</span>
                <span v-if="!call.done" class="ws__tool-running">执行中…</span>
              </summary>
              <pre v-if="call.args" class="ws__tool-pre">{{ call.args }}</pre>
              <pre v-if="call.result" class="ws__tool-pre ws__tool-pre--result">{{ call.result.slice(0, 2000) }}</pre>
            </details>
          </div>

          <div
            v-if="msg.content"
            class="ws__bubble ws__bubble--assistant ws__md"
            v-html="md(msg.content)"
          />
          <div v-else-if="msg.streaming" class="ws__bubble ws__bubble--assistant muted">…</div>

          <template v-for="(card, ci) in msg.cards" :key="ci">
            <ChatPlanCard v-if="isPlanCard(card)" :card="card" />
            <template v-else-if="isTaskRef(card)">
              <RouterLink class="ws__taskref mono" :to="`/tasks/${card.task_id}`">
                <Icon name="tasks" :size="12" />
                任务 {{ shortId(card.task_id, 10) }}
                <span v-if="taskState(card.task_id, card.state ?? '')" class="muted">
                  {{ taskState(card.task_id, card.state ?? '') }}
                </span>
              </RouterLink>
              <TaskProgressSteps :task-id="card.task_id" />
            </template>
          </template>
        </template>
      </div>

      <div v-if="chat.loadingSession.value" class="muted ws__loading">加载会话…</div>
    </div>

    <div class="ws__composer">
      <div v-if="chat.queueWaiting.value" class="ws__queue">
        <span class="ws__queue-dot" /> 模型槽位排队中…
      </div>
      <button
        v-if="pageContext"
        class="ws__ctx"
        :class="{ 'ws__ctx--on': chat.includePageContext.value }"
        type="button"
        :title="chat.includePageContext.value ? '点击不再附带页面上下文' : '点击附带页面上下文'"
        @click="chat.includePageContext.value = !chat.includePageContext.value"
      >
        附带上下文: {{ pageContext.entity_type }} {{ pageContext.entity_id }}
        <span v-if="!chat.includePageContext.value" class="muted">(已停用)</span>
      </button>
      <div v-if="chat.error.value" class="ws__error" role="alert">
        {{ chat.error.value }}
        <button class="icon-btn" type="button" aria-label="关闭错误" @click="chat.error.value = ''">
          <Icon name="x" :size="12" />
        </button>
      </div>
      <div class="ws__inputrow">
        <textarea
          v-model="input"
          class="input ws__input"
          rows="2"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          @keydown.enter="onEnter"
        />
        <button
          v-if="chat.streaming.value"
          class="btn btn--danger ws__send"
          type="button"
          title="停止"
          @click="chat.stopStreaming()"
        >
          <Icon name="square" :size="14" />
        </button>
        <button
          v-else
          class="btn btn--primary ws__send"
          type="button"
          title="发送"
          :disabled="!input.trim()"
          @click="submit"
        >
          <Icon name="send" :size="14" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ws {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--panel);
  color: var(--text-1);
}
.ws__bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
}
.ws__backend {
  max-width: 180px;
  font-size: var(--fs-caption);
  padding: 2px var(--sp-2);
}
.ws__sessions {
  max-width: 150px;
  font-size: var(--fs-caption);
  padding: 2px var(--sp-2);
}
.ws__runtime {
  font-size: var(--fs-caption);
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0 var(--sp-1);
}
.ws__spacer {
  flex: 1;
}
.ws__feed {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  scroll-behavior: smooth;
}
.ws__empty {
  margin: auto;
  text-align: center;
  color: var(--text-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
}
.ws__starters {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}
.ws__starter {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  border-radius: var(--r-ctl);
  padding: var(--sp-2) var(--sp-3);
  cursor: pointer;
  font-size: var(--fs-label);
}
.ws__starter:hover {
  border-color: var(--control-border-hover);
  background: var(--surface-hover);
}
.ws__msg {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.ws__msg--user {
  align-items: flex-end;
}
.ws__bubble {
  max-width: 88%;
  border-radius: var(--r-card);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-body);
  line-height: 1.55;
  word-break: break-word;
}
.ws__bubble--user {
  background: var(--accent);
  color: #fff;
  white-space: pre-wrap;
}
.ws__bubble--assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  align-self: flex-start;
  max-width: 100%;
}
.ws__md :deep(p) {
  margin: 0 0 var(--sp-2);
}
.ws__md :deep(p:last-child) {
  margin-bottom: 0;
}
.ws__md :deep(pre) {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  padding: var(--sp-2);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
}
.ws__md :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--code-bg);
  border-radius: var(--r-sm);
  padding: 0 3px;
}
.ws__md :deep(pre code) {
  background: none;
  padding: 0;
}
.ws__md :deep(table) {
  border-collapse: collapse;
  font-size: var(--fs-caption);
}
.ws__md :deep(th),
.ws__md :deep(td) {
  border: 1px solid var(--border);
  padding: 2px var(--sp-2);
}
.ws__md :deep(a) {
  color: var(--link);
}
.ws__md :deep(h3),
.ws__md :deep(h4),
.ws__md :deep(h5) {
  margin: var(--sp-2) 0 var(--sp-1);
  font-size: var(--fs-body);
}
.ws__md :deep(ul),
.ws__md :deep(ol) {
  margin: 0 0 var(--sp-2);
  padding-left: var(--sp-5);
}
.ws__thinking summary,
.ws__tool summary {
  cursor: pointer;
  color: var(--text-3);
  font-size: var(--fs-caption);
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}
.ws__thinking-body {
  color: var(--text-3);
  font-size: var(--fs-caption);
  white-space: pre-wrap;
  border-left: 2px solid var(--border);
  padding-left: var(--sp-2);
  margin-top: var(--sp-1);
}
.ws__tools {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.ws__tool-running {
  color: var(--st-running-text);
  font-size: var(--fs-caption);
}
.ws__tool-pre {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  padding: var(--sp-2);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 180px;
  overflow: auto;
}
.ws__taskref {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--link);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 1px var(--sp-2);
  font-size: var(--fs-caption);
  align-self: flex-start;
}
.ws__composer {
  border-top: 1px solid var(--border);
  padding: var(--sp-2) var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ws__queue {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--st-await-text);
  font-size: var(--fs-caption);
}
.ws__queue-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--st-await-dot);
  animation: ws-pulse 1.2s infinite;
}
@keyframes ws-pulse {
  50% {
    opacity: 0.3;
  }
}
.ws__ctx {
  align-self: flex-start;
  border: 1px solid var(--border);
  background: var(--surface-faint);
  color: var(--text-3);
  border-radius: 999px;
  padding: 1px var(--sp-2);
  font-size: var(--fs-caption);
  cursor: pointer;
}
.ws__ctx--on {
  color: var(--accent);
  border-color: var(--accent-line);
}
.ws__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  background: var(--st-fail-bg);
  border: 1px solid var(--st-fail-line);
  color: var(--st-fail-text);
  border-radius: var(--r-ctl);
  padding: var(--sp-1) var(--sp-2);
  font-size: var(--fs-caption);
}
.ws__inputrow {
  display: flex;
  gap: var(--sp-2);
  align-items: flex-end;
}
.ws__input {
  flex: 1;
  resize: none;
  font-size: var(--fs-body);
}
.ws__send {
  flex-shrink: 0;
}
.ws__loading {
  text-align: center;
  font-size: var(--fs-caption);
}
</style>
