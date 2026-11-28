<script setup lang="ts">
import { computed } from 'vue'
import { STEP_ORDER, useTaskEvents, type StepEntry } from '../composables/useTaskEvents'

/**
 * 管线步级渐进结果面板：按样本分组渲染已完成步骤及其关键结果。
 * 数据源是 useTaskEvents 共享 store（SSE 实时流 + 页面轮询回填），
 * 因此任务运行中逐个点亮，不需要等整条 pipeline 结束。
 */
const props = defineProps<{ taskId: string; subject?: string }>()

const taskEvents = useTaskEvents()

const entries = computed(() => {
  const all = taskEvents.stepsFor(props.taskId)
  if (!props.subject) return all
  return all.filter((entry) => entry.subject === props.subject)
})

const grouped = computed(() => {
  const groups = new Map<string, StepEntry[]>()
  for (const entry of entries.value) {
    const key = entry.subject || '—'
    const list = groups.get(key) ?? []
    list.push(entry)
    groups.set(key, list)
  }
  return [...groups.entries()]
})

const multiSubject = computed(() => grouped.value.length > 1)

function label(step: string): string {
  return STEP_ORDER.find(([key]) => key === step)?.[1] ?? step
}

/** 从结果摘要提取最关键的一两行展示文本。 */
function headline(entry: StepEntry): string {
  const r = entry.result
  const parts: string[] = []
  if (typeof r.species === 'string' && r.species) parts.push(r.species)
  if (typeof r.serotype === 'string' && r.serotype) parts.push(r.serotype)
  if (r.st !== undefined && r.st !== '') parts.push(`ST-${r.st}`)
  if (typeof r.hits === 'number') parts.push(`${r.hits} 命中`)
  if (typeof r.contigs === 'number') {
    const contigBits = [`${r.contigs} contigs`]
    if (typeof r.n50 === 'number') contigBits.push(`N50 ${formatLen(r.n50)}`)
    if (typeof r.gc_pct === 'number') contigBits.push(`GC ${r.gc_pct}%`)
    parts.push(contigBits.join(' · '))
  }
  if (typeof r.amr_count === 'number') parts.push(`AMR ${r.amr_count}`)
  if (typeof r.n_samples === 'number') parts.push(`${r.n_samples} 样本`)
  if (typeof r.method === 'string' && entry.step === 'species') parts.push(`(${r.method})`)
  return parts.join('；')
}

function formatLen(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} Mb`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} kb`
  return `${n} bp`
}
</script>

<template>
  <div v-if="entries.length" class="step-progress">
    <div v-for="[subject, steps] in grouped" :key="subject" class="step-group">
      <div v-if="multiSubject" class="step-subject">{{ subject }}</div>
      <ul class="step-list">
        <li v-for="entry in steps" :key="`${entry.subject}:${entry.step}`" class="step-row">
          <span class="step-dot" aria-hidden="true"></span>
          <span class="step-label">{{ label(entry.step) }}</span>
          <span v-if="headline(entry)" class="step-result">{{ headline(entry) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.step-progress {
  margin: 4px 0 2px;
  padding: 6px 10px;
  border: 1px solid var(--border, rgba(127, 127, 127, 0.25));
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
}
.step-subject {
  font-weight: 600;
  margin: 2px 0;
  opacity: 0.85;
}
.step-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.step-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 1px 0;
}
.step-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok, #3a9d62);
  align-self: center;
}
.step-label {
  flex: none;
  opacity: 0.75;
  white-space: nowrap;
}
.step-result {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
