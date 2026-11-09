<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from './Icon.vue'
import { api } from '../api'
import { useToast } from '../composables/useToast'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; created: [id: string] }>()

const taskType = ref('analyze')
const samples = ref('')
const scope = ref('')
const busy = ref(false)
const error = ref('')
const firstField = ref<HTMLSelectElement>()
const toast = useToast()
let previousFocus: HTMLElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement as HTMLElement | null
      taskType.value = 'analyze'
      samples.value = ''
      scope.value = ''
      error.value = ''
      await nextTick()
      firstField.value?.focus()
    } else {
      previousFocus?.focus()
    }
  },
)

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && props.open && !busy.value) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const task = await api.submitTask({
      task_type: taskType.value,
      samples: samples.value,
      scope: scope.value,
    })
    toast.ok(`任务已提交：${task.task_id.slice(0, 12)}…`)
    emit('created', task.task_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '提交失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <template v-if="open">
      <div class="overlay" @click="!busy && emit('close')" />
      <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="task-drawer-title">
        <div class="drawer__head">
          <div>
            <h2 id="task-drawer-title" class="drawer__title">提交任务</h2>
            <p class="card__hint" style="margin-top: 2px">写入只经任务层；提交后进入运行队列。</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" :disabled="busy" @click="emit('close')">
            <Icon name="x" />
          </button>
        </div>

        <form class="drawer__body form" @submit.prevent="submit">
          <div class="field">
            <label class="field__label" for="task-type">任务类型</label>
            <select id="task-type" ref="firstField" v-model="taskType" class="select">
              <option value="analyze">analyze · 基因组分析</option>
              <option value="curate">curate · 本地流行特征库构建</option>
            </select>
            <p class="field__hint">analyze 逐样本走分析管线；curate 构建本地流行特征库。</p>
          </div>

          <div v-if="taskType === 'analyze'" class="field">
            <label class="field__label" for="task-samples">
              样本列表
              <span class="field__optional">逗号或换行分隔</span>
            </label>
            <textarea
              id="task-samples"
              v-model="samples"
              class="textarea textarea--mono"
              rows="5"
              placeholder="SAM-TYP-001, SAM-TYP-002"
            />
            <p class="field__hint">样本必须已在 samples.tsv 登记；目录直入请使用 CLI/MCP。</p>
          </div>

          <div v-if="taskType === 'curate'" class="field">
            <label class="field__label" for="task-scope">
              scope
              <span class="field__optional">JSON 对象，可选</span>
            </label>
            <textarea
              id="task-scope"
              v-model="scope"
              class="textarea textarea--mono"
              rows="5"
              placeholder='{"pathogen": "Salmonella"}'
              spellcheck="false"
            />
            <p class="field__hint">用于筛选构建范围；留空表示全部已登记病原。</p>
          </div>

          <div v-if="error" class="form-error" role="alert">{{ error }}</div>
        </form>

        <div class="drawer__foot">
          <button class="btn btn--ghost" type="button" :disabled="busy" @click="emit('close')">
            取消
          </button>
          <button class="btn btn--primary" type="button" :disabled="busy" @click="submit">
            <span v-if="busy" class="spinner" />
            <Icon v-else name="plus" />
            {{ busy ? '提交中…' : '提交任务' }}
          </button>
        </div>
      </aside>
    </template>
  </Teleport>
</template>
