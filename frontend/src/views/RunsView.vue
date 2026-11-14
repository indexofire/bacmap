<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { RunRow } from '../types'
import { fmtTime, shortId } from '../lib/format'

const router = useRouter()
const runs = ref<RunRow[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const offset = ref(0)
const limit = ref(50)
const total = ref(0)

function fmtDuration(started?: string | null, finished?: string | null): string {
  if (!started) return '—'
  if (!finished) return '运行中'
  const start = new Date(started).getTime()
  const end = new Date(finished).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '—'
  const total = Math.round((end - start) / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function strainText(ids: string[] | undefined): string {
  const text = (ids ?? []).join(', ')
  if (!text) return '—'
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

function strainTitle(ids: string[] | undefined): string | undefined {
  const text = (ids ?? []).join(', ')
  return text.length > 40 ? text : undefined
}

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load(initial = false) {
  if (initial) loading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    const page = await api.runsPage(offset.value, limit.value)
    runs.value = page.items
    total.value = page.total
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载运行记录失败'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function changePage(value: number) {
  offset.value = value
  void load()
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
  void load()
}

onMounted(() => void load(true))
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">运行记录</h1>
        <p class="pagehead__sub">
          ADR-18 证据链：每次分析的工具版本、参考库、配置、输入哈希与种子。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="refreshing" @click="load()">
          <span v-if="refreshing" class="spinner" />
          <Icon v-else name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="card__head">
        <h2 class="card__title">最近运行</h2>
        <span class="card__hint">{{ runs.length }} 条</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 200px" /></div>

      <div v-else-if="runs.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">运行 ID</th>
              <th scope="col">工作流</th>
              <th scope="col">样本</th>
              <th scope="col">任务</th>
              <th scope="col">开始时间</th>
              <th scope="col">耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.run_id"
              class="row-click"
              @click="goRow($event, `/runs/${run.run_id}`)"
            >
              <td data-label="运行 ID">
                <RouterLink class="link-cell" :to="`/runs/${run.run_id}`">
                  {{ shortId(run.run_id) }}
                </RouterLink>
              </td>
              <td data-label="工作流"><code>{{ run.workflow || '—' }}</code></td>
              <td data-label="样本">
                <span class="mono" :title="strainTitle(run.strain_ids)">{{ strainText(run.strain_ids) }}</span>
              </td>
              <td data-label="任务">
                <RouterLink v-if="run.task_id" class="link-cell" :to="`/tasks/${run.task_id}`">
                  {{ shortId(run.task_id) }}
                </RouterLink>
                <span v-else class="muted">—</span>
              </td>
              <td data-label="开始时间">
                <span class="mono muted">{{ fmtTime(run.started_at) }}</span>
              </td>
              <td data-label="耗时">
                <span class="mono muted">{{ fmtDuration(run.started_at, run.finished_at) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="还没有运行记录"
        hint="分析任务成功结束后，证据链记录会出现在这里。"
        icon="runs"
      />
      <Pager
        :offset="offset"
        :limit="limit"
        :total="total"
        :disabled="loading"
        @update:offset="changePage"
        @update:limit="changeLimit"
      />
    </section>
  </div>
</template>
