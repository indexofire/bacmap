<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from './Icon.vue'
import PlanBadge from './PlanBadge.vue'
import { shortId } from '../lib/format'
import { useChat } from '../composables/useChat'
import type { ChatPlanCard } from '../types'

const props = defineProps<{ card: ChatPlanCard }>()
const chat = useChat()
const rejecting = ref(false)
const rejectReason = ref('')
const busy = ref(false)

const canConfirm = computed(
  () => props.card.can_confirm !== false && props.card.state === 'awaiting_confirmation',
)

interface TaskRow {
  type: string
  summary: string[]
  detailKind: 'script' | 'draft' | ''
  detail: string
}

function taskRow(task: Record<string, unknown>): TaskRow {
  const type = String(task.task_type ?? '?')
  const summary: string[] = []
  const samples = task.samples
  if (Array.isArray(samples) && samples.length) {
    summary.push(`样本 ${samples.map((s) => String(s)).join(', ')}`)
  }
  for (const key of ['fasta_dir', 'fastq_dir', 'data_path'] as const) {
    if (typeof task[key] === 'string' && task[key]) summary.push(String(task[key]))
  }
  if (task.scope && typeof task.scope === 'object') {
    const keys = Object.keys(task.scope as Record<string, unknown>)
    if (keys.length) summary.push(`scope: ${keys.join(', ')}`)
  }
  if (typeof task.objective === 'string' && task.objective) {
    summary.push(task.objective.slice(0, 80))
  }
  let detailKind: TaskRow['detailKind'] = ''
  let detail = ''
  if (typeof task.script === 'string' && task.script) {
    detailKind = 'script'
    detail = task.script
  } else if (typeof task.draft === 'string' && task.draft) {
    detailKind = 'draft'
    detail = task.draft
  }
  return { type, summary, detailKind, detail }
}

const rows = computed(() => props.card.tasks.map(taskRow))

async function confirm() {
  if (busy.value) return
  busy.value = true
  try {
    await chat.confirmPlanCard(props.card)
  } finally {
    busy.value = false
  }
}

async function reject() {
  const reason = rejectReason.value.trim()
  if (!reason || busy.value) return
  busy.value = true
  try {
    await chat.rejectPlanCard(props.card, reason)
    rejecting.value = false
    rejectReason.value = ''
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="plan-card">
    <div class="plan-card__head">
      <span class="plan-card__title">
        计划 <span class="mono">{{ shortId(card.plan_id, 8) }}</span>
        <span class="mono muted">v{{ card.version }}</span>
      </span>
      <PlanBadge :state="card.state" />
      <span class="plan-card__hash mono" :title="card.plan_hash">{{ card.short_hash }}</span>
      <RouterLink class="plan-card__link" :to="`/plans/${card.plan_id}`">
        <Icon name="external-link" :size="12" />
      </RouterLink>
    </div>

    <p v-if="card.rationale" class="plan-card__rationale">{{ card.rationale }}</p>

    <ul class="plan-card__tasks">
      <li v-for="(row, i) in rows" :key="i" class="plan-card__task">
        <span class="plan-card__task-type mono">{{ row.type }}</span>
        <span v-for="(s, j) in row.summary" :key="j" class="plan-card__task-param">{{ s }}</span>
        <details v-if="row.detail" class="plan-card__detail">
          <summary>{{ row.detailKind === 'script' ? '审查脚本' : '审查草稿' }}（{{ row.detail.length }} 字符）</summary>
          <pre class="plan-card__pre">{{ row.detail }}</pre>
        </details>
      </li>
    </ul>

    <div v-if="card.task_ids?.length" class="plan-card__tasks-links">
      <RouterLink
        v-for="tid in card.task_ids"
        :key="tid"
        class="plan-card__task-link mono"
        :to="`/tasks/${tid}`"
      >
        {{ shortId(tid, 10) }}
      </RouterLink>
    </div>

    <div v-if="canConfirm" class="plan-card__actions">
      <button class="btn btn--primary btn--sm" type="button" :disabled="busy" @click="confirm">
        确认并提交
      </button>
      <button
        class="btn btn--ghost btn--sm"
        type="button"
        :disabled="busy"
        @click="rejecting = !rejecting"
      >
        拒绝
      </button>
      <div v-if="rejecting" class="plan-card__reject">
        <input
          v-model="rejectReason"
          class="input plan-card__reject-input"
          type="text"
          placeholder="拒绝原因（必填）"
          @keydown.enter.prevent="reject"
        />
        <button
          class="btn btn--danger btn--sm"
          type="button"
          :disabled="busy || !rejectReason.trim()"
          @click="reject"
        >
          确认拒绝
        </button>
      </div>
    </div>
    <p v-else-if="card.state === 'awaiting_confirmation'" class="plan-card__wait muted">
      等待分析员或管理员确认 ·
      <RouterLink :to="`/plans/${card.plan_id}`">在计划页查看</RouterLink>
    </p>
  </div>
</template>

<style scoped>
.plan-card {
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  border-radius: var(--r-card);
  padding: var(--sp-3) var(--sp-4);
  margin: var(--sp-2) 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.plan-card__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.plan-card__title {
  font-weight: 600;
  color: var(--text-1);
}
.plan-card__hash {
  font-size: var(--fs-caption);
  color: var(--text-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0 var(--sp-1);
}
.plan-card__link {
  color: var(--link);
  display: inline-flex;
}
.plan-card__rationale {
  margin: 0;
  color: var(--text-2);
  font-size: var(--fs-label);
}
.plan-card__tasks {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.plan-card__task {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  font-size: var(--fs-label);
  color: var(--text-2);
}
.plan-card__task-type {
  background: var(--surface-faint);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0 var(--sp-1);
  color: var(--text-1);
}
.plan-card__detail {
  width: 100%;
}
.plan-card__detail summary {
  cursor: pointer;
  color: var(--link);
  font-size: var(--fs-caption);
}
.plan-card__pre {
  max-height: 220px;
  overflow: auto;
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--r-ctl);
  padding: var(--sp-2);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
  white-space: pre-wrap;
  word-break: break-all;
}
.plan-card__tasks-links {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.plan-card__task-link {
  color: var(--link);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 0 var(--sp-1);
  font-size: var(--fs-caption);
}
.plan-card__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.plan-card__reject {
  display: flex;
  gap: var(--sp-2);
  flex: 1;
  min-width: 200px;
}
.plan-card__reject-input {
  flex: 1;
}
.plan-card__wait {
  margin: 0;
  font-size: var(--fs-caption);
}
</style>
