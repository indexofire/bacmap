<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { api } from '../api'
import type { TaskEvent, TaskRow } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'
import { usePolling } from '../composables/usePolling'
import { useToast } from '../composables/useToast'

const route = useRoute()
const toast = useToast()
const id = String(route.params.id)

const task = ref<TaskRow | null>(null)
const events = ref<TaskEvent[]>([])
const loading = ref(true)
const error = ref('')

const approver = ref('')
const decision = ref<'approve' | 'reject'>('approve')
const signature = ref('')
const comment = ref('')
const submitting = ref(false)
const actionError = ref('')

const terminal = ['succeeded', 'failed', 'cancelled']
const active = computed(() => !!task.value && !terminal.includes(task.value.state))

const eventLabels: Record<string, string> = {
  'task.submitted': '任务已提交',
  'task.step': '步骤变更',
  'task.state': '状态变更',
  'task.approval': '审批签名',
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
  const payload = event.payload ?? {}
  const detail = payload.detail ?? payload.message ?? payload.step ?? payload.state ?? payload.decision
  if (detail !== undefined) return String(detail)
  return jsonText(payload)
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
  if (decision.value === 'reject' && !window.confirm('拒绝会终止该任务，结果不会发布。确定拒绝？')) {
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    task.value = await api.approveTask(id, {
      approver: approver.value.trim(),
      decision: decision.value,
      signature: signature.value,
      comment: comment.value.trim() || undefined,
    })
    toast.ok(decision.value === 'approve' ? '审批通过，任务继续执行' : '已拒绝该任务')
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
        <h1 class="pagehead__title">任务详情</h1>
        <p class="pagehead__sub">状态、审批门与领域事件时间线。</p>
      </div>
      <div class="pagehead__actions">
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
                  <dt>消息</dt>
                  <dd>{{ task.message || '—' }}</dd>
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
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">任务信息</h2>
            <div class="meta-grid">
              <div class="meta-item">
                <dt>任务 ID</dt>
                <dd class="mono">{{ shortId(task.task_id, 20) }}</dd>
              </div>
              <div class="meta-item">
                <dt>类型</dt>
                <dd><code>{{ task.task_type }}</code></dd>
              </div>
              <div class="meta-item">
                <dt>提交人</dt>
                <dd>{{ task.submitted_by }}</dd>
              </div>
              <div class="meta-item">
                <dt>状态</dt>
                <dd><StatusBadge :state="task.state" /></dd>
              </div>
            </div>
          </section>

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
                <select id="decision" v-model="decision" class="select">
                  <option value="approve">approve · 通过并发布</option>
                  <option value="reject">reject · 拒绝</option>
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
              状态：{{ task.state }}。运行记录可在「运行记录」页查看。
            </p>
            <RouterLink to="/runs" class="btn btn--ghost btn--sm" style="margin-top: 14px">
              <Icon name="runs" />
              查看运行记录
            </RouterLink>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
