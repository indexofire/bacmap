<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { IsolateRow } from '../types'

const rows = ref<IsolateRow[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) =>
    [row.isolate_id, row.specimen_id, row.lineage_id].join(' ').toLowerCase().includes(q),
  )
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.listIsolates(2000)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载菌株失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">菌株</h1>
        <p class="pagehead__sub">菌株（isolate）实体与所属样本；测序数据在样本详情中查看。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="filters">
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索菌株 / 样本 / 谱系…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ filtered.length }} / {{ rows.length }} 株</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="filtered.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">菌株</th>
              <th scope="col">样本</th>
              <th scope="col">谱系</th>
              <th scope="col">传代</th>
              <th scope="col">测序数据</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filtered" :key="row.isolate_id">
              <td data-label="菌株">
                <RouterLink class="link-cell" :to="`/isolates/${row.isolate_id}`">
                  <code>{{ row.isolate_id }}</code>
                </RouterLink>
              </td>
              <td data-label="样本">
                <RouterLink
                  v-if="row.specimen_id"
                  class="link-cell"
                  :to="`/specimens/${row.specimen_id}`"
                >
                  {{ row.specimen_id }}
                </RouterLink>
                <span v-else class="muted">未关联</span>
              </td>
              <td data-label="谱系">{{ row.lineage_id || '—' }}</td>
              <td data-label="传代"><span class="mono">{{ row.passage ?? '—' }}</span></td>
              <td data-label="测序数据"><span class="mono">{{ row.n_libraries ?? 0 }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="rows.length === 0"
        title="暂无菌株"
        hint="登记分析数据或导入样本关联后，菌株会出现在这里。"
      />
      <EmptyState v-else title="没有匹配的菌株" hint="换个关键词试试。" />
    </section>
  </div>
</template>
