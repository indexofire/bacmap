<script setup lang="ts">
import { computed } from 'vue'
import Icon from './Icon.vue'

const props = withDefaults(
  defineProps<{
    offset: number
    limit: number
    total: number
    pageSizes?: number[]
    disabled?: boolean
  }>(),
  { pageSizes: () => [25, 50, 100, 200], disabled: false },
)

const emit = defineEmits<{
  'update:offset': [value: number]
  'update:limit': [value: number]
}>()

const pages = computed(() => Math.max(1, Math.ceil(props.total / Math.max(1, props.limit))))
const page = computed(() => Math.min(pages.value, Math.floor(props.offset / Math.max(1, props.limit)) + 1))

function go(target: number) {
  if (props.disabled) return
  const next = Math.min(pages.value, Math.max(1, target))
  emit('update:offset', (next - 1) * props.limit)
}

function changeLimit(event: Event) {
  const value = Number((event.target as HTMLSelectElement).value)
  if (!Number.isFinite(value) || value <= 0) return
  emit('update:limit', value)
}
</script>

<template>
  <div v-if="total > 0" class="pager">
    <span class="pager__summary">
      第 <strong class="mono">{{ page }}</strong> / {{ pages }} 页 ·
      共 <strong class="mono">{{ total }}</strong> 条
    </span>
    <div class="pager__controls">
      <button class="btn btn--ghost btn--sm" type="button" :disabled="disabled || page <= 1" title="第一页" @click="go(1)">
        <Icon name="arrow-left" />
        <Icon name="arrow-left" />
      </button>
      <button class="btn btn--ghost btn--sm" type="button" :disabled="disabled || page <= 1" @click="go(page - 1)">
        上一页
      </button>
      <button class="btn btn--ghost btn--sm" type="button" :disabled="disabled || page >= pages" @click="go(page + 1)">
        下一页
      </button>
      <button class="btn btn--ghost btn--sm" type="button" :disabled="disabled || page >= pages" title="最后一页" @click="go(pages)">
        <Icon name="arrow-right" />
        <Icon name="arrow-right" />
      </button>
      <select class="select pager__size" :value="limit" aria-label="每页条数" :disabled="disabled" @change="changeLimit">
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }} 条/页</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  color: var(--text-3);
  font-size: 12px;
}

.pager__controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pager__summary strong {
  color: var(--text-1);
  font-weight: 600;
}

.pager__size {
  width: 104px;
  height: 28px;
  padding: 0 24px 0 8px;
  font-size: 11px;
}

@media (max-width: 640px) {
  .pager {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
