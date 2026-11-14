<script setup lang="ts">
import { computed } from 'vue'
import type { TaskState } from '../types'

const props = defineProps<{ state: TaskState | string }>()

const labels: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  paused: '已暂停',
  awaiting_approval: '待审批',
  succeeded: '已完成',
  failed: '已失败',
  cancelled: '已取消',
}

const label = computed(() => labels[props.state] ?? props.state)
</script>

<template>
  <span class="badge" :class="`badge--${state}`">
    <span class="badge__dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>
