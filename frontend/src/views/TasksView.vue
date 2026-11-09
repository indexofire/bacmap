<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import TaskDrawer from '../components/TaskDrawer.vue'
import { api } from '../api'
import type { TaskRow, TaskState } from '../types'
import { fmtTime, shortId } from '../lib/format'

const route = useRoute()
const router = useRouter()

const tasks = ref<TaskRow[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const drawerOpen = ref(false)
const stateFilter = ref<'all' | TaskState>('all')
const typeFilter = ref('all')
const query = ref('')

const stateChips: Array<{ value: 'all' | TaskState; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'running', label: '运行中' },
  { value: 'awaiting_approval', label: '待审批' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const types = computed(() => Array.from(new Set(tasks.value.map((t) => t.task_type))).sort())

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    if (stateFilter.value !== 'all' && task.state !== stateFilter.value) return false
    if (typeFilter.value !== 'all' && task.task_type !== typeFilter.value) return false
    if (!q) return true
    return (
      task.task_id.toLowerCase().includes(q) ||
      task.submitted_by.toLowerCase().includes(q) ||
      task.task_type.toLowerCase().includes(q) ||
      (task.current_step ?? '').toLowerCase().includes(q) ||
      (task.message ?? '').toLowerCase().includes(q)
    )
  })
})

async function load(initial = false) {
  if (initial) loading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    tasks.value = await api.listTasks(200)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载任务失败'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function openDrawer() {
  drawerOpen.value = true
  if (route.query.new) {
    const rest = { ...route.query }
    delete rest.new
    router.replace({ query: rest })
  }
}

function onCreated(id: string) {
  drawerOpen.value = false
  router.push(`/tasks/${id}`)
}

watch(
  () => route.query.new,
  (value) => {
    if (value) openDrawer()
  },
)

onMounted(() => {
  void load(true)
  if (route.query.new) openDrawer()
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">任务</h1>
        <p class="pagehead__sub">提交分析任务、跟踪运行状态，并在审批门完成签名。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="refreshing" @click="load()">
          <span v-if="refreshing" class="spinner" />
          <Icon v-else name="refresh" />
          刷新
        </button>
        <button class="btn btn--primary" type="button" @click="openDrawer">
          <Icon name="plus" />
          提交任务
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="filters">
        <button
          v-for="chip in stateChips"
          :key="chip.value"
          type="button"
          class="chip"
          :class="{ 'is-active': stateFilter === chip.value }"
          @click="stateFilter = chip.value"
        >
          {{ chip.label }}
        </button>
        <span class="filter-spacer" />
        <select v-model="typeFilter" class="select" style="width: 150px; height: 28px; padding: 0 28px 0 9px; font-size: 11.5px">
          <option value="all">全部类型</option>
          <option v-for="type in types" :key="type" :value="type">{{ type }}</option>
        </select>
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索 ID / 提交人 / 步骤…" />
        </label>
      </div>

      <div v-if="loading" class="card__body">
        <div class="skeleton" style="height: 220px" />
      </div>

      <div v-else-if="filtered.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">任务 ID</th>
              <th scope="col">类型</th>
              <th scope="col">状态</th>
              <th scope="col">当前步骤</th>
              <th scope="col">提交人</th>
              <th scope="col">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in filtered" :key="task.task_id" class="row-click">
              <td data-label="任务 ID">
                <RouterLink class="link-cell" :to="`/tasks/${task.task_id}`">
                  {{ shortId(task.task_id) }}
                </RouterLink>
              </td>
              <td data-label="类型"><code>{{ task.task_type }}</code></td>
              <td data-label="状态"><StatusBadge :state="task.state" /></td>
              <td data-label="当前步骤">
                <span v-if="task.current_step" class="mono" style="font-size: 11.5px">{{ task.current_step }}</span>
                <span v-else class="muted">—</span>
              </td>
              <td data-label="提交人">{{ task.submitted_by }}</td>
              <td data-label="创建时间"><span class="mono muted">{{ fmtTime(task.created_at) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="tasks.length === 0"
        title="还没有任务"
        hint="提交第一个分析任务；任务会经过运行、审批门与证据归档。"
        icon="tasks"
      >
        <button class="btn btn--primary btn--sm" type="button" @click="openDrawer">
          <Icon name="plus" />
          提交任务
        </button>
      </EmptyState>

      <EmptyState
        v-else
        title="没有匹配的任务"
        hint="调整状态、类型或关键词筛选。"
        icon="search"
      />
    </section>

    <TaskDrawer :open="drawerOpen" @close="drawerOpen = false" @created="onCreated" />
  </div>
</template>
