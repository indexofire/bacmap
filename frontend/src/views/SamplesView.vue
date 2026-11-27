<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { SampleRow, SpeciesSummary } from '../types'

const route = useRoute()
const router = useRouter()
const rows = ref<SampleRow[]>([])
const speciesOptions = ref<SpeciesSummary[]>([])
const loading = ref(true)
const error = ref('')
const query = ref(String(route.query.q ?? ''))
const species = ref(String(route.query.species ?? ''))
const serotype = ref(String(route.query.serotype ?? ''))
const st = ref(String(route.query.mlst_st ?? ''))
const gene = ref(String(route.query.amr_gene ?? ''))
const offset = ref(0)
const limit = ref(50)
const total = ref(0)
const indexed = ref(true)
let timer: ReturnType<typeof setTimeout> | undefined

type SortKey =
  | 'sample_id'
  | 'species'
  | 'genome_size'
  | 'contigs'
  | 'gc_pct'
  | 'st'
  | 'serovar'
  | 'n_card'
  | 'n_vfdb'
  | 'n_plasmid'
  | 'analysis_date'
const sort = ref<SortKey>('sample_id')
const order = ref<'asc' | 'desc'>('asc')

const columns: { key: SortKey; label: string }[] = [
  { key: 'sample_id', label: '测序数据' },
  { key: 'species', label: '物种' },
  { key: 'genome_size', label: '基因组大小' },
  { key: 'contigs', label: 'Contigs' },
  { key: 'gc_pct', label: 'GC 含量' },
  { key: 'st', label: 'MLST' },
  { key: 'serovar', label: '血清型' },
  { key: 'n_card', label: 'CARD' },
  { key: 'n_vfdb', label: 'VFDB' },
  { key: 'n_plasmid', label: '质粒' },
  { key: 'analysis_date', label: '分析时间' },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const page = await api.samplesPage({
      offset: offset.value,
      limit: limit.value,
      sort: sort.value,
      order: order.value,
      q: query.value.trim(),
      species: species.value,
      serotype: serotype.value.trim(),
      mlst_st: st.value.trim(),
      amr_gene: gene.value.trim(),
    })
    rows.value = page.items
    total.value = page.total
    indexed.value = page.indexed !== false
    if (offset.value >= page.total && page.total > 0) {
      offset.value = 0
      await load()
    }
    syncQuery()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本失败'
  } finally {
    loading.value = false
  }
}

function syncQuery() {
  const next: Record<string, string> = {}
  if (query.value.trim()) next.q = query.value.trim()
  if (species.value) next.species = species.value
  if (serotype.value.trim()) next.serotype = serotype.value.trim()
  if (st.value.trim()) next.mlst_st = st.value.trim()
  if (gene.value.trim()) next.amr_gene = gene.value.trim()
  void router.replace({ query: next })
}

function scheduleLoad() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    offset.value = 0
    void load()
  }, 250)
}

watch([query, species, serotype, st, gene], scheduleLoad)
watch(
  () => route.query.species,
  (value) => {
    const next = String(value ?? '')
    if (next !== species.value) {
      species.value = next
      offset.value = 0
    }
  },
)
watch([sort, order], () => {
  offset.value = 0
  void load()
})

async function loadSpecies() {
  try {
    const data = await api.speciesSummary()
    speciesOptions.value = data.items
  } catch {
    // 物种下拉是辅助；失败不影响列表。
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

function changeSort(key: SortKey) {
  if (sort.value === key) {
    order.value = order.value === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value = key
    order.value = 'asc'
  }
}

function ariaSort(key: SortKey): 'ascending' | 'descending' | 'none' {
  if (sort.value !== key) return 'none'
  return order.value === 'asc' ? 'ascending' : 'descending'
}

function sortArrow(key: SortKey): string {
  if (sort.value !== key) return '↕'
  return order.value === 'asc' ? '↑' : '↓'
}

function resetFilters() {
  query.value = ''
  species.value = ''
  serotype.value = ''
  st.value = ''
  gene.value = ''
}

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

function formatGc(value: number | null): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function formatDate(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toLocaleDateString('zh-CN')
}

onMounted(() => {
  void loadSpecies()
  void load()
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">测序数据（基因组）</h1>
        <p class="pagehead__sub">
          已完成分析的测序数据；按物种、型别、耐药基因检索，点击编号查看结果与报告。
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
        结果索引尚未回填，当前为兼容扫描模式。请在本机执行
        <code>bacmap results reindex</code> 以启用 SQL 分页与检索。
      </p>
    </div>

    <section class="card">
      <div class="filters" style="flex-wrap: wrap; gap: 8px">
        <label class="search-mini">
          <Icon name="search" />
          <input
            v-model="query"
            type="search"
            placeholder="搜索编号 / 物种 / ST / 血清型 / 基因…"
          />
        </label>
        <select v-model="species" class="input" style="max-width: 220px">
          <option value="">全部物种</option>
          <option v-for="item in speciesOptions" :key="item.species" :value="item.species">
            {{ displaySpecies(item.species) }}（{{ item.n_samples }}）
          </option>
        </select>
        <input v-model="st" class="input" style="max-width: 120px" placeholder="ST" />
        <input v-model="serotype" class="input" style="max-width: 150px" placeholder="血清型" />
        <input v-model="gene" class="input" style="max-width: 170px" placeholder="耐药基因" />
        <button class="btn btn--ghost" type="button" @click="resetFilters">清除</button>
        <span class="filter-spacer" />
        <span class="card__hint">{{ total }} 条</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="rows.length" class="table-wrap">
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
            <tr v-for="row in rows" :key="row.sample_id" class="row-click">
              <td data-label="测序数据">
                <RouterLink class="link-cell" :to="`/samples/${row.sample_id}`">
                  {{ row.sample_id }}
                </RouterLink>
                <span v-if="row.prelim" class="muted"> · 初步</span>
              </td>
              <td data-label="物种"><i>{{ displaySpecies(row.verdict) }}</i></td>
              <td data-label="基因组大小">
                <span class="mono" :title="row.genome_size ? `${row.genome_size} bp` : ''">
                  {{ formatBases(row.genome_size) }}
                </span>
              </td>
              <td data-label="Contigs">
                <span class="mono">{{ row.contigs ?? '—' }}</span>
              </td>
              <td data-label="GC 含量"><span class="mono">{{ formatGc(row.gc_pct) }}</span></td>
              <td data-label="MLST"><span class="mono">{{ displayOrDash(row.st) }}</span></td>
              <td data-label="血清型">{{ displayOrDash(row.serovar) }}</td>
              <td data-label="CARD"><span class="mono">{{ row.n_card }}</span></td>
              <td data-label="VFDB"><span class="mono">{{ row.n_vfdb }}</span></td>
              <td data-label="质粒"><span class="mono">{{ row.n_plasmid }}</span></td>
              <td data-label="分析时间">{{ formatDate(row.analysis_date) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="total === 0"
        title="没有匹配的测序数据"
        hint="调整筛选条件，或确认结果索引已回填。"
        icon="search"
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
