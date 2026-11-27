<script setup lang="ts">
import { ref } from 'vue'
import Icon from './Icon.vue'
import KeyValueEditor from './KeyValueEditor.vue'
import { api } from '../api'
import type { LabResultRow } from '../types'
import { requireSucceeded, waitForTask } from '../lib/tasks'

const props = defineProps<{
  subjectType: 'isolate' | 'specimen'
  subjectId: string
  initial?: LabResultRow | null
  proposal?: boolean
}>()
const emit = defineEmits<{ saved: [taskId: string]; cancel: [] }>()

const form = ref({
  category: props.initial?.category ?? '',
  test_name: props.initial?.test_name ?? '',
  result: props.initial?.result ?? '',
  unit: props.initial?.unit ?? '',
  method: props.initial?.method ?? '',
  interpretation: props.initial?.interpretation ?? '',
  standard: props.initial?.standard ?? '',
  tested_date: props.initial?.tested_date ?? '',
  tested_by: props.initial?.tested_by ?? '',
  lab: props.initial?.lab ?? '',
  notes: props.initial?.notes ?? '',
})
const extra = ref<Record<string, unknown>>(
  (props.initial?.extra as Record<string, unknown> | undefined) ?? {},
)
const busy = ref(false)
const error = ref('')

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const payload = {
      ...form.value,
      extra: extra.value,
      subject_type: props.subjectType,
      subject_id: props.subjectId,
    }
    if (props.proposal) {
      const params = props.initial?.id
        ? { kind: 'lab_result_update', result_id: props.initial.id, ...payload }
        : {
            kind: 'lab_result',
            strain_id: props.subjectId,
            ...payload,
          }
      await api.proposeWetlab(params)
      emit('saved', '')
      return
    }
    const result = props.initial?.id
      ? await api.updateLabResult(props.initial.id, payload)
      : await api.addLabResult({
          ...payload,
          strain_id: props.subjectType === 'isolate' ? props.subjectId : '',
        })
    requireSucceeded(await waitForTask(result.task_id))
    emit('saved', result.task_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存化验结果失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="card card--pad" @submit.prevent="submit">
    <div class="card__head">
      <h3 class="card__title">{{ initial?.id ? '编辑化验结果' : '新增化验结果' }}</h3>
      <span class="card__hint">{{ subjectType === 'isolate' ? '菌株' : '样本' }} {{ subjectId }}</span>
    </div>
    <div class="form">
      <div class="meta-grid">
        <div class="field">
          <label class="field__label">类别</label>
          <input v-model="form.category" class="input" required placeholder="mic / mngs / 药敏" />
        </div>
        <div class="field">
          <label class="field__label">检验项目</label>
          <input v-model="form.test_name" class="input" required placeholder="meropenem / blaCTX-M" />
        </div>
        <div class="field">
          <label class="field__label">结果</label>
          <input v-model="form.result" class="input" required placeholder="0.25 / positive" />
        </div>
        <div class="field">
          <label class="field__label">单位</label>
          <input v-model="form.unit" class="input" placeholder="mg/L" />
        </div>
        <div class="field">
          <label class="field__label">方法</label>
          <input v-model="form.method" class="input" />
        </div>
        <div class="field">
          <label class="field__label">判读</label>
          <input v-model="form.interpretation" class="input" placeholder="S / I / R" />
        </div>
        <div class="field">
          <label class="field__label">标准</label>
          <input v-model="form.standard" class="input" placeholder="CLSI 2026" />
        </div>
        <div class="field">
          <label class="field__label">检测日期</label>
          <input v-model="form.tested_date" class="input" placeholder="2026-11-27" />
        </div>
        <div class="field">
          <label class="field__label">检测人</label>
          <input v-model="form.tested_by" class="input" />
        </div>
        <div class="field">
          <label class="field__label">实验室</label>
          <input v-model="form.lab" class="input" />
        </div>
      </div>
      <div class="field">
        <label class="field__label">备注</label>
        <textarea v-model="form.notes" class="textarea" rows="2" />
      </div>
      <div class="field">
        <label class="field__label">扩展字段</label>
        <KeyValueEditor v-model="extra" :disabled="busy" />
      </div>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="form__actions">
        <button class="btn btn--primary" type="submit" :disabled="busy">
          <span v-if="busy" class="spinner" />
          <Icon v-else name="check" />
          {{ proposal ? '提交修改提案' : '保存化验结果' }}
        </button>
        <button class="btn btn--ghost" type="button" :disabled="busy" @click="emit('cancel')">
          取消
        </button>
      </div>
    </div>
  </form>
</template>
