<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import CopyButton from '../components/CopyButton.vue'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { api } from '../api'
import type { RunRow, TaskEvent, TaskRow } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'
import { usePolling } from '../composables/usePolling'
import { useToast } from '../composables/useToast'

const route = useRoute()
const toast = useToast()
const id = String(route.params.id)

const task = ref<TaskRow | null>(null)
const events = ref<TaskEvent[]>([])
const run = ref<RunRow | null>(null)
const loading = ref(true)
const error = ref('')

const approver = ref('')
const decision = ref<'' | 'approve' | 'reject'>('')
const signature = ref('')
const comment = ref('')
const submitting = ref(false)
const actionError = ref('')

const terminal = ['succeeded', 'failed', 'cancelled']
const active = computed(() => !!task.value && !terminal.includes(task.value.state))

const stateLabels: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  awaiting_approval: '待审批',
  succeeded: '已完成',
  failed: '已失败',
  cancelled: '已取消',
}

const verdictLabels: Record<string, string> = {
  pass: '通过',
  reject: '拒绝',
  needs_human_review: '待定',
  approve: '通过',
  approved: '通过',
}

const gateLabels: Record<string, string> = {
  analysis_claims: '分析结论门',
  baseline_release: '基线发布门',
  mining: '挖掘门',
  citation: '引用门',
}

interface GateContext {
  raw: string
  gate: string
  verdict: string
  problems: string[]
  nArtifacts: number | null
  evaluatedAt: string
}

interface PlanRef {
  id: string
  version: number
}

const eventLabels: Record<string, string> = {
  'task.submitted': '任务已提交',
  'task.step': '步骤变更',
  'task.state': '状态变更',
  'task.approval': '审批签名',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseGateMessage(message: string | null | undefined): GateContext | null {
  const raw = message?.trim()
  if (!raw) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(parsed)) return null
  let candidate: Record<string, unknown> | null = null
  if (typeof parsed.gate === 'string') {
    candidate = parsed
  } else if (isRecord(parsed.gates)) {
    for (const value of Object.values(parsed.gates)) {
      if (isRecord(value) && typeof value.gate === 'string') {
        candidate = value
        break
      }
    }
  }
  if (!candidate) return null
  const details = isRecord(candidate.details) ? candidate.details : {}
  const rawProblems = details.problems
  const problems = Array.isArray(rawProblems)
    ? rawProblems.map((problem) => (typeof problem === 'string' ? problem : jsonText(problem)))
    : []
  const nArtifacts = typeof details.n_artifacts === 'number' ? details.n_artifacts : null
  return {
    raw,
    gate: String(candidate.gate),
    verdict: typeof candidate.verdict === 'string' ? candidate.verdict : '',
    problems,
    nArtifacts,
    evaluatedAt: typeof candidate.evaluated_at === 'string' ? candidate.evaluated_at : '',
  }
}

function gateLabel(gate: string): string {
  return gateLabels[gate] ?? (gate || '—')
}

function verdictLabel(verdict: string): string {
  return verdictLabels[verdict] ?? (verdict || '—')
}

function stateLabel(state: string): string {
  return stateLabels[state] ?? state
}

function verdictTone(verdict: string): string {
  if (verdict === 'pass' || verdict === 'approve') return 'succeeded'
  if (verdict === 'reject') return 'failed'
  return 'awaiting_approval'
}

function describeGate(context: GateContext): string {
  const problems = context.problems.length ? `（${context.problems.join('、')}）` : ''
  return `${gateLabel(context.gate)}：${verdictLabel(context.verdict)}${problems}`
}

function humanDetail(value: string): string {
  if (!value || value === '{}' || value === '[]') return '—'
  const gate = parseGateMessage(value)
  if (gate) return describeGate(gate)
  return stateLabels[value] ?? verdictLabels[value] ?? value
}

function eventTone(type: string, payload: Record<string, unknown> | null | undefined): string {
  if (type === 'task.approval') return 'await'
  if (type === 'task.state') {
    const state = String(payload?.state ?? payload?.to ?? '')
    if (state === 'succeeded') return 'ok'
    if (state === 'failed' || state === 'cancelled') return 'fail'
    if (state === 'awaiting_approval') return 'await'
    if (state === 'running') return 'run'
  }
  return ''
}

function eventDetail(event: TaskEvent): string {
  const payload = event.payload
  if (!payload || Object.keys(payload).length === 0) return '—'
  const state = typeof payload.state === 'string' ? payload.state : ''
  if (state) {
    const message = typeof payload.message === 'string' ? payload.message.trim() : ''
    const gate = parseGateMessage(message)
    const suffix = gate ? describeGate(gate) : message ? humanDetail(message) : ''
    return suffix ? `${stateLabel(state)} · ${suffix}` : stateLabel(state)
  }
  const step = typeof payload.step === 'string' ? payload.step.trim() : ''
  if (step) return `步骤：${step}`
  const decision = typeof payload.decision === 'string' ? payload.decision : ''
  if (decision) return `决定：${verdictLabel(decision)}`
  const detail = typeof payload.detail === 'string' ? payload.detail.trim() : ''
  if (detail) return humanDetail(detail)
  const message = typeof payload.message === 'string' ? payload.message.trim() : ''
  if (message) return humanDetail(message)
  const taskType = typeof payload.task_type === 'string' ? payload.task_type : ''
  if (taskType) return `类型：${taskType}`
  return jsonText(payload)
}

const gateContext = computed(() => parseGateMessage(task.value?.message))
const messageText = computed(() => {
  const message = task.value?.message?.trim() ?? ''
  if (!message || message === '{}' || message === '[]' || message === 'null') return ''
  return message
})
const planRef = computed<PlanRef | null>(() => {
  const match = task.value?.submitted_by.match(/plan\s+([0-9a-f]{16})@v(\d+)/i)
  return match ? { id: match[1], version: Number(match[2]) } : null
})

async function loadRun(taskId: string) {
  try {
    const runs = await api.listRuns(100)
    run.value = runs.find((row) => row.task_id === taskId) ?? null
  } catch {
    run.value = null
  }
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [taskData, eventData] = await Promise.all([
      api.getTask(id),
      api.listEvents({ task_id: id, limit: 100 }),
    ])
    task.value = taskData
    events.value = eventData.events.slice().reverse()
    if (terminal.includes(taskData.state)) {
      await loadRun(taskData.task_id)
    } else {
      run.value = null
    }
    error.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载任务失败'
  } finally {
    if (!silent) loading.value = false
  }
}

usePolling(() => load(true), 2000, () => active.value)

async function approve() {
  if (!task.value) return
  if (!approver.value.trim() || !signature.value.trim()) {
    actionError.value = '审批人和签名不能为空'
    return
  }
  const choice = decision.value
  if (!choice) {
    actionError.value = '请选择审批决定'
    return
  }
  if (choice === 'reject' && !window.confirm('拒绝会终止该任务，结果不会发布。确定拒绝？')) {
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    task.value = await api.approveTask(id, {
      approver: approver.value.trim(),
      decision: choice,
      signature: signature.value,
      comment: comment.value.trim() || undefined,
    })
    toast.ok(choice === 'approve' ? '审批通过，任务继续执行' : '已拒绝该任务')
    await load(true)
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : '审批失败'
  } finally {
    submitting.value = false
  }
}

async function cancelTask() {
  if (!task.value) return
  if (!window.confirm('取消后任务会停止，且不能恢复。确定取消？')) return
  submitting.value = true
  actionError.value = ''
  try {
    task.value = await api.cancelTask(id)
    toast.ok('任务已取消')
    await load(true)
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : '取消失败'
  } finally {
    submitting.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/tasks" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回任务
          </RouterLink>
        </div>
        <h1 class="pagehead__title">
          <span class="inline-actions" style="gap: 10px">
            <span class="mono" :title="task?.task_id ?? ''">
              {{ task ? shortId(task.task_id, 20) : '任务详情' }}
            </span>
            <CopyButton v-if="task" :value="task.task_id" label="任务 ID" />
          </span>
        </h1>
        <p class="pagehead__sub">状态、审批门与领域事件时间线。</p>
      </div>
      <div class="pagehead__actions">
        <RouterLink
          v-if="planRef"
          :to="`/plans/${planRef.id}?version=${planRef.version}`"
          class="btn btn--ghost"
        >
          <Icon name="plans" />
          查看计划
        </RouterLink>
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load()">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
    </template>

    <template v-else-if="task">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <div class="detail-head" style="margin: 0">
                  <code class="detail-id">{{ task.task_id }}</code>
                  <StatusBadge :state="task.state" />
                </div>
                <p class="card__hint" style="margin-top: 4px">
                  {{ task.task_type }} · 提交人 {{ task.submitted_by }}
                </p>
              </div>
              <span v-if="active" class="badge badge--running">
                <span class="badge__dot" aria-hidden="true" />
                每 2 秒刷新
              </span>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row">
                  <dt>状态</dt>
                  <dd><StatusBadge :state="task.state" /></dd>
                </div>
                <div class="statuslist__row">
                  <dt>当前步骤</dt>
                  <dd>{{ task.current_step || '—' }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>创建时间</dt>
                  <dd class="mono">{{ fmtTime(task.created_at) }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>更新时间</dt>
                  <dd class="mono">{{ fmtTime(task.updated_at) }}</dd>
                </div>
              </dl>

              <div class="divider" style="margin: 16px 0" />

              <div class="inline-actions" style="justify-content: space-between; margin-bottom: 6px">
                <h3 class="card__title" style="font-size: 13px">
                  {{ gateContext ? '审批上下文' : '消息' }}
                </h3>
                <span
                  v-if="gateContext"
                  class="badge"
                  :class="`badge--${verdictTone(gateContext.verdict)}`"
                >
                  <span class="badge__dot" aria-hidden="true" />
                  {{ verdictLabel(gateContext.verdict) }}
                </span>
              </div>

              <dl v-if="gateContext" class="statuslist">
                <div class="statuslist__row">
                  <dt>门</dt>
                  <dd>
                    {{ gateLabel(gateContext.gate) }}
                    <code>{{ gateContext.gate }}</code>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>判定</dt>
                  <dd>
                    {{ verdictLabel(gateContext.verdict) }}
                    <span class="muted">（{{ gateContext.verdict || '—' }}）</span>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>问题</dt>
                  <dd>
                    <ul v-if="gateContext.problems.length" style="margin: 0; padding-left: 18px">
                      <li v-for="(problem, index) in gateContext.problems" :key="index">
                        <code>{{ problem }}</code>
                      </li>
                    </ul>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div v-if="gateContext.nArtifacts !== null" class="statuslist__row">
                  <dt>产物数量</dt>
                  <dd class="mono">{{ gateContext.nArtifacts }}</dd>
                </div>
                <div v-if="gateContext.evaluatedAt" class="statuslist__row">
                  <dt>评估时间</dt>
                  <dd class="mono">{{ fmtTime(gateContext.evaluatedAt) }}</dd>
                </div>
              </dl>
              <details v-if="gateContext" style="margin-top: 10px">
                <summary class="card__hint" style="cursor: pointer">原始消息（JSON）</summary>
                <pre class="code-block" style="margin-top: 8px; max-height: 180px">{{ gateContext.raw }}</pre>
              </details>
              <pre v-else-if="messageText" class="code-block" style="max-height: 180px">{{ messageText }}</pre>
              <p v-else class="muted">—</p>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">事件时间线</h2>
              <span class="card__hint">{{ events.length }} 条</span>
            </div>
            <div v-if="events.length" class="timeline">
              <div
                v-for="event in events"
                :key="event.seq"
                class="timeline__item"
                :class="eventTone(event.type, event.payload) && `timeline__item--${eventTone(event.type, event.payload)}`"
              >
                <span class="timeline__dot" aria-hidden="true" />
                <div>
                  <div class="timeline__top">
                    <span class="timeline__type">{{ eventLabels[event.type] ?? event.type }}</span>
                    <span v-if="event.actor" class="muted" style="font-size: 11.5px">{{ event.actor }}</span>
                    <span class="timeline__time">{{ fmtTime(event.occurred_at) }}</span>
                  </div>
                  <div class="timeline__body">{{ eventDetail(event) }}</div>
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding: 32px">
              <p class="empty__hint">暂无事件记录。</p>
            </div>
          </section>
        </div>

        <div class="stack">
          <section v-if="task.state === 'awaiting_approval'" class="card card--pad" style="border-top: 2px solid var(--st-await-dot)">
            <h2 class="card__title">审批签名</h2>
            <p class="card__hint" style="margin: 4px 0 16px">
              该任务已到达审批门；签名提交后才会继续发布或终止。
            </p>
            <form class="form" @submit.prevent="approve">
              <div class="field">
                <label class="field__label" for="approver">审批人</label>
                <input id="approver" v-model="approver" class="input" required autocomplete="off" />
              </div>
              <div class="field">
                <label class="field__label" for="decision">决定</label>
                <select id="decision" v-model="decision" class="select" required>
                  <option value="" disabled>请选择决定</option>
                  <option value="approve">通过并发布</option>
                  <option value="reject">拒绝</option>
                </select>
              </div>
              <div class="field">
                <label class="field__label" for="signature">
                  签名
                  <span class="field__optional">口令 / 凭证</span>
                </label>
                <input
                  id="signature"
                  v-model="signature"
                  class="input"
                  type="password"
                  required
                  autocomplete="off"
                />
              </div>
              <div class="field">
                <label class="field__label" for="comment">
                  备注
                  <span class="field__optional">可选</span>
                </label>
                <input id="comment" v-model="comment" class="input" autocomplete="off" />
              </div>
              <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>
              <div class="form__actions">
                <button class="btn btn--primary" type="submit" :disabled="submitting">
                  <span v-if="submitting" class="spinner" />
                  <Icon v-else name="check" />
                  提交审批
                </button>
              </div>
            </form>
          </section>

          <section v-else-if="active" class="card card--pad">
            <h2 class="card__title">运行操作</h2>
            <p class="card__hint" style="margin: 4px 0 16px">任务仍在执行，可取消。</p>
            <div v-if="actionError" class="form-error" style="margin-bottom: 12px">{{ actionError }}</div>
            <button class="btn btn--danger" type="button" :disabled="submitting" @click="cancelTask">
              <Icon name="ban" />
              取消任务
            </button>
          </section>

          <section v-else class="card card--pad">
            <h2 class="card__title">任务已结束</h2>
            <p class="card__hint" style="margin-top: 6px">
              状态：{{ stateLabel(task.state) }}。运行记录可在「运行记录」页查看。
            </p>
            <div class="inline-actions" style="margin-top: 14px">
              <RouterLink v-if="run" :to="`/runs/${run.run_id}`" class="btn btn--ghost btn--sm">
                <Icon name="runs" />
                查看运行记录
              </RouterLink>
              <RouterLink v-else to="/runs" class="btn btn--ghost btn--sm">
                <Icon name="runs" />
                查看运行记录
              </RouterLink>
              <RouterLink
                v-if="planRef"
                :to="`/plans/${planRef.id}?version=${planRef.version}`"
                class="btn btn--ghost btn--sm"
              >
                <Icon name="plans" />
                查看计划
              </RouterLink>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
