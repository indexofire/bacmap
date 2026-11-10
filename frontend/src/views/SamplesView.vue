<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { SampleRow } from '../types'

const router = useRouter()
const rows = ref<SampleRow[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref('')
const query = ref('')

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) =>
    [row.sample_id, row.verdict, row.st, row.serovar, row.pathotype, ...row.card_genes, ...row.vfdb_genes]
      .join(' ')
      .toLowerCase()
      .includes(q),
  )
})

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const page = await api.listSamples(undefined, 100)
    rows.value = page.items
    nextCursor.value = page.next_cursor
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本失败'
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!nextCursor.value) return
  loadingMore.value = true
  try {
    const page = await api.listSamples(nextCursor.value, 100)
    rows.value = [...rows.value, ...page.items]
    nextCursor.value = page.next_cursor
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载更多失败'
  } finally {
    loadingMore.value = false
  }
}

onMounted(() => void load())

function displaySpecies(value: string): string {
  return String(value ?? '').replaceAll('_', ' ') || '—'
}

function displayOrDash(value: string): string {
  return !value || value === 'N/A' ? '—' : value
}
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">样本结果</h1>
        <p class="pagehead__sub">已完成分析的样本；点击样本号查看结果详情与 HTML 报告。</p>
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
          <input v-model="query" type="search" placeholder="搜索样本 / 物种 / ST / 基因…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ filtered.length }} / {{ rows.length }} 株</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="filtered.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">样本</th>
              <th scope="col">物种</th>
              <th scope="col">MLST</th>
              <th scope="col">血清型</th>
              <th scope="col">CARD</th>
              <th scope="col">VFDB</th>
              <th scope="col">质粒</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in filtered"
              :key="row.sample_id"
              class="row-click"
              @click="goRow($event, `/samples/${row.sample_id}`)"
            >
              <td data-label="样本">
                <RouterLink class="link-cell" :to="`/samples/${row.sample_id}`">
                  {{ row.sample_id }}
                </RouterLink>
              </td>
              <td data-label="物种"><i>{{ displaySpecies(row.verdict) }}</i></td>
              <td data-label="MLST"><span class="mono">{{ displayOrDash(row.st) }}</span></td>
              <td data-label="血清型">{{ displayOrDash(row.serovar) }}</td>
              <td data-label="CARD"><span class="mono">{{ row.n_card }}</span></td>
              <td data-label="VFDB"><span class="mono">{{ row.n_vfdb }}</span></td>
              <td data-label="质粒"><span class="mono">{{ row.n_plasmid }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="rows.length === 0"
        title="暂无已完成样本"
        hint="提交分析任务并完成后，结果会出现在这里。"
        icon="records"
      />
      <EmptyState v-else title="没有匹配的样本" hint="调整关键词。" icon="search" />

      <div v-if="nextCursor && !loading" class="card__foot" style="display: flex; justify-content: center">
        <button class="btn btn--ghost" type="button" :disabled="loadingMore" @click="loadMore">
          <span v-if="loadingMore" class="spinner" />
          <Icon v-else name="arrow-right" />
          {{ loadingMore ? '加载中…' : '加载更多' }}
        </button>
      </div>
    </section>
  </div>
</template>
