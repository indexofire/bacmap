<script setup lang="ts">
import { ref } from 'vue'
import Icon from './Icon.vue'

interface Row {
  id: number
  key: string
  value: string
  original: unknown
}

const props = defineProps<{
  modelValue: Record<string, unknown>
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [Record<string, unknown>] }>()

let nextId = 1

function fromRecord(value: Record<string, unknown>): Row[] {
  return Object.entries(value ?? {}).map(([key, item]) => ({
    id: nextId++,
    key,
    value: item === null || item === undefined ? '' : String(item),
    original: item,
  }))
}

const rows = ref<Row[]>(fromRecord(props.modelValue ?? {}))

function coerce(row: Row): unknown {
  if (typeof row.original === 'number') {
    const parsed = Number(row.value)
    return row.value.trim() !== '' && Number.isFinite(parsed) ? parsed : row.value
  }
  if (typeof row.original === 'boolean') {
    return row.value.trim().toLowerCase() === 'true'
  }
  return row.value
}

function emitValue() {
  const out: Record<string, unknown> = {}
  for (const row of rows.value) {
    const key = row.key.trim()
    if (key) out[key] = coerce(row)
  }
  emit('update:modelValue', out)
}

function addRow() {
  rows.value.push({ id: nextId++, key: '', value: '', original: undefined })
}

function removeRow(index: number) {
  rows.value.splice(index, 1)
  emitValue()
}
</script>

<template>
  <div class="stack" style="gap: 8px">
    <div v-for="(row, index) in rows" :key="row.id" class="inline-actions" style="gap: 8px">
      <input
        v-model="row.key"
        class="input"
        style="flex: 1; min-width: 140px"
        placeholder="字段名"
        :disabled="disabled"
        @input="emitValue"
      />
      <input
        v-model="row.value"
        class="input"
        style="flex: 2; min-width: 180px"
        placeholder="值"
        :disabled="disabled"
        @input="emitValue"
      />
      <button
        class="btn btn--ghost btn--sm"
        type="button"
        :disabled="disabled"
        title="删除该字段"
        @click="removeRow(index)"
      >
        <Icon name="trash" />
      </button>
    </div>
    <div>
      <button class="btn btn--ghost btn--sm" type="button" :disabled="disabled" @click="addRow">
        <Icon name="plus" />
        添加字段
      </button>
    </div>
  </div>
</template>
