<script setup lang="ts">
import { computed } from 'vue'
import type { PlanState } from '../types'

const props = defineProps<{ state: PlanState | string }>()

const labels: Record<string, string> = {
  awaiting_confirmation: '待确认',
  confirmed: '已确认',
  submitted: '已提交',
  rejected: '已拒绝',
  superseded: '已取代',
  failed: '失败',
}

const label = computed(() => labels[props.state] ?? props.state)
</script>

<template>
  <span class="badge" :class="`badge--${state}`">
    <span class="badge__dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>
