<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { SampleRow } from '../types'

const router = useRouter()
const rows = ref<SampleRow[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const offset = ref(0)
const limit = ref(50)

type SortKey =
  | 'sample_id'
  | 'verdict'
  | 'genome_size'
  | 'contigs'
  | 'gc_pct'
  | 'st'
  | 'serovar'
  | 'n_card'
  | 'n_vfdb'
  | 'n_plasmid'
const sort = ref<SortKey>('sample_id')
const order = ref<'asc' | 'desc'>('asc')

const columns: { key: SortKey; label: string }[] = [
  { key: 'sample_id', label: '测序数据' },
  { key: 'verdict', label: '物种' },
  { key: 'genome_size', label: '基因组大小' },
  { key: 'contigs', label: 'Contigs' },
  { key: 'gc_pct', label: 'GC 含量' },
  { key: 'st', label: 'MLST' },
  { key: 'serovar', label: '血清型' },
  { key: 'n_card', label: 'CARD' },
  { key: 'n_vfdb', label: 'VFDB' },
  { key: 'n_plasmid', label: '质粒' },
]

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

function isMissing(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'number') return !Number.isFinite(value)
  const text = String(value).trim()
  return text === '' || text === 'N/A'
}

/** 本地排序：空缺值恒排最后，数字按数值、其余按本地化字符串（含数字的自然序）。 */
const sorted = computed(() => {
  const key = sort.value
  return [...filtered.value].sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    const aMissing = isMissing(av)
    const bMissing = isMissing(bv)
    if (aMissing || bMissing) return aMissing === bMissing ? 0 : aMissing ? 1 : -1
    const cmp =
      typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
    return order.value === 'asc' ? cmp : -cmp
  })
})

const paged = computed(() => sorted.value.slice(offset.value, offset.value + limit.value))

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

/** 一次取全量行（分批 500）；之后的筛选、排序、翻页都在浏览器内完成，不再发请求。 */
const FETCH_PAGE = 500

async function load() {
  loading.value = true
  error.value = ''
  try {
    const all: SampleRow[] = []
    let next = 0
    for (;;) {
      const page = await api.samplesPage(next, FETCH_PAGE)
      all.push(...page.items)
      next += page.items.length
      if (page.items.length === 0 || all.length >= page.total) break
    }
    rows.value = all
    if (offset.value >= all.length) offset.value = 0
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本失败'
  } finally {
    loading.value = false
  }
}

function changePage(value: number) {
  offset.value = value
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
}

function changeSort(key: SortKey) {
  if (sort.value === key) {
    order.value = order.value === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value = key
    order.value = 'asc'
  }
  offset.value = 0
}

function ariaSort(key: SortKey): 'ascending' | 'descending' | 'none' {
  if (sort.value !== key) return 'none'
  return order.value === 'asc' ? 'ascending' : 'descending'
}

function sortArrow(key: SortKey): string {
  if (sort.value !== key) return '↕'
  return order.value === 'asc' ? '↑' : '↓'
}

watch(query, () => {
  offset.value = 0
})

onMounted(() => void load())

function displaySpecies(value: string): string {
  return String(value ?? '').replaceAll('_', ' ') || '—'
}

function displayOrDash(value: string): string {
  return !value || value === 'N/A' ? '—' : value
}

function formatBases(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} Mb`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)} kb`
  return `${value} bp`
}

function formatContigs(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : String(value)
}

function formatGc(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">测序数据结果</h1>
        <p class="pagehead__sub">已完成分析的测序数据（library）；点击编号查看结果详情与 HTML 报告。</p>
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
          <input v-model="query" type="search" placeholder="搜索测序数据 / 物种 / ST / 基因…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ filtered.length }} / {{ rows.length }} 株</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="sorted.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th v-for="col in columns" :key="col.key" scope="col" :aria-sort="ariaSort(col.key)">
                <button
                  type="button"
                  class="th-sort"
                  :class="{ 'is-active': sort === col.key }"
                  @click="changeSort(col.key)"
                >
                  {{ col.label }} <span class="th-sort__arrow">{{ sortArrow(col.key) }}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in paged"
              :key="row.sample_id"
              class="row-click"
              @click="goRow($event, `/samples/${row.sample_id}`)"
            >
              <td data-label="测序数据">
                <RouterLink class="link-cell" :to="`/samples/${row.sample_id}`">
                  {{ row.sample_id }}
                </RouterLink>
              </td>
              <td data-label="物种"><i>{{ displaySpecies(row.verdict) }}</i></td>
              <td data-label="基因组大小">
                <span class="mono" :title="row.genome_size ? `${row.genome_size} bp` : ''">
                  {{ formatBases(row.genome_size) }}
                </span>
              </td>
              <td data-label="Contigs"><span class="mono">{{ formatContigs(row.contigs) }}</span></td>
              <td data-label="GC 含量"><span class="mono">{{ formatGc(row.gc_pct) }}</span></td>
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

      <Pager
        :offset="offset"
        :limit="limit"
        :total="sorted.length"
        :disabled="loading"
        @update:offset="changePage"
        @update:limit="changeLimit"
      />
    </section>
  </div>
</template>
