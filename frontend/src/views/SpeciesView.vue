<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { SpeciesSummary } from '../types'

const items = ref<SpeciesSummary[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const indexed = ref(false)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return items.value
  return items.value.filter((item) => item.species.toLowerCase().includes(q))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.speciesSummary()
    items.value = data.items
    indexed.value = data.indexed
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载物种失败'
  } finally {
    loading.value = false
  }
}

function displaySpecies(value: string): string {
  return String(value ?? '').replaceAll('_', ' ') || 'Unknown'
}

function formatDate(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">物种</h1>
        <p class="pagehead__sub">
          按物种汇总的基因组与分析结果；点击进入该物种的测序数据列表。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="!loading && !indexed" class="card card--pad" style="margin-bottom: 16px">
      <p class="card__hint">
        结果索引尚未回填。请在本机执行
        <code>bacmap results reindex</code>，之后物种与基因组列表将走 SQL 索引。
      </p>
    </div>

    <section class="card">
      <div class="filters">
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索物种名…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ filtered.length }} 个物种</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="filtered.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">物种</th>
              <th scope="col">基因组</th>
              <th scope="col">样本</th>
              <th scope="col">菌株</th>
              <th scope="col">最近分析</th>
              <th scope="col">指标完整</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filtered" :key="row.species">
              <td data-label="物种">
                <RouterLink
                  class="link-cell"
                  :to="{ path: '/samples', query: { species: row.species } }"
                >
                  <i>{{ displaySpecies(row.species) }}</i>
                </RouterLink>
              </td>
              <td data-label="基因组"><span class="mono">{{ row.n_samples }}</span></td>
              <td data-label="样本"><span class="mono">{{ row.n_specimens }}</span></td>
              <td data-label="菌株"><span class="mono">{{ row.n_isolates }}</span></td>
              <td data-label="最近分析">{{ formatDate(row.last_analysis) }}</td>
              <td data-label="指标完整">
                <span class="mono">{{ row.n_with_metrics }} / {{ row.n_samples }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="!items.length"
        title="暂无物种数据"
        hint="完成分析并写入索引后，物种会出现在这里。"
        icon="chart"
      />
      <EmptyState v-else title="没有匹配的物种" hint="换个关键词试试。" icon="search" />
    </section>
  </div>
</template>
