<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { RunRow } from '../types'
import { fmtTime, shortId } from '../lib/format'

const runs = ref<RunRow[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')

async function load(initial = false) {
  if (initial) loading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    runs.value = await api.listRuns(100)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载运行记录失败'
  } finally {
    loading.value = false
    refreshing.value = false
  }
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
              <th scope="col">样本</th>
              <th scope="col">任务</th>
              <th scope="col">工具版本</th>
              <th scope="col">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.run_id" class="row-click">
              <td data-label="运行 ID">
                <RouterLink class="link-cell" :to="`/runs/${run.run_id}`">
                  {{ shortId(run.run_id) }}
                </RouterLink>
              </td>
              <td data-label="样本">{{ run.sample_id ?? '—' }}</td>
              <td data-label="任务">
                <RouterLink v-if="run.task_id" class="link-cell" :to="`/tasks/${run.task_id}`">
                  {{ shortId(String(run.task_id)) }}
                </RouterLink>
                <span v-else class="muted">—</span>
              </td>
              <td data-label="工具版本">
                <span class="mono">{{ Object.keys((run.tool_versions as object) ?? {}).length }}</span>
              </td>
              <td data-label="创建时间">
                <span class="mono muted">{{ fmtTime(String(run.created_at ?? '')) }}</span>
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
    </section>
  </div>
</template>
