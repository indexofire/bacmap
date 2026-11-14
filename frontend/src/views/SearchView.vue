<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { IsolateRow, SampleRow, SpecimenRow } from '../types'

const route = useRoute()
const router = useRouter()

const query = ref(String(route.query.q ?? ''))
const serotype = ref(String(route.query.serotype ?? ''))
const mlst = ref(String(route.query.mlst_st ?? ''))
const gene = ref(String(route.query.amr_gene ?? ''))
const results = ref<SampleRow[]>([])
const specimens = ref<SpecimenRow[]>([])
const isolates = ref<IsolateRow[]>([])
const offset = ref(0)
const limit = ref(25)
const totalResults = ref(0)
const specimenOffset = ref(0)
const specimenLimit = ref(25)
const specimenTotal = ref(0)
const isolateOffset = ref(0)
const isolateLimit = ref(25)
const isolateTotal = ref(0)
const loading = ref(false)
const searched = ref(false)
const error = ref('')

const total = computed(
  () => totalResults.value + specimenTotal.value + isolateTotal.value,
)

async function loadIdentity() {
  const page = await api.searchIdentityPage({
    q: query.value.trim(),
    specimen_offset: specimenOffset.value,
    specimen_limit: specimenLimit.value,
    isolate_offset: isolateOffset.value,
    isolate_limit: isolateLimit.value,
  })
  specimens.value = page.specimens
  isolates.value = page.isolates
  specimenTotal.value = page.specimen_total
  isolateTotal.value = page.isolate_total
}

async function loadResults() {
  const page = await api.searchPage({
    q: query.value.trim(),
    serotype: serotype.value.trim(),
    mlst_st: mlst.value.trim(),
    amr_gene: gene.value.trim(),
    offset: offset.value,
    limit: limit.value,
  })
  results.value = page.items
  totalResults.value = page.total
}

function changeSpecimenPage(value: number) {
  specimenOffset.value = value
  void loadIdentity().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

function changeSpecimenLimit(value: number) {
  specimenLimit.value = value
  specimenOffset.value = 0
  void loadIdentity().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

function changeIsolatePage(value: number) {
  isolateOffset.value = value
  void loadIdentity().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

function changeIsolateLimit(value: number) {
  isolateLimit.value = value
  isolateOffset.value = 0
  void loadIdentity().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

function changePage(value: number) {
  offset.value = value
  void loadResults().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
  void loadResults().catch((err) => {
    error.value = err instanceof Error ? err.message : '检索失败'
  })
}

async function runSearch() {
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    offset.value = 0
    specimenOffset.value = 0
    isolateOffset.value = 0
    await Promise.all([loadResults(), loadIdentity()])
    const next: Record<string, string> = {}
    if (query.value.trim()) next.q = query.value.trim()
    if (serotype.value.trim()) next.serotype = serotype.value.trim()
    if (mlst.value.trim()) next.mlst_st = mlst.value.trim()
    if (gene.value.trim()) next.amr_gene = gene.value.trim()
    router.replace({ query: next })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '检索失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (query.value || serotype.value || mlst.value || gene.value) void runSearch()
})

function displaySpecies(value: string): string {
  return String(value ?? '').replaceAll('_', ' ') || '—'
}

function displayOrDash(value: string): string {
  return !value || value === 'N/A' ? '—' : value
}

function reset() {
  query.value = ''
  serotype.value = ''
  mlst.value = ''
  gene.value = ''
  results.value = []
  specimens.value = []
  isolates.value = []
  offset.value = 0
  totalResults.value = 0
  specimenOffset.value = 0
  specimenTotal.value = 0
  isolateOffset.value = 0
  isolateTotal.value = 0
  searched.value = false
  error.value = ''
  void router.replace({ query: {} })
}
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">检索</h1>
        <p class="pagehead__sub">
          统一检索样本（背景信息）、菌株（湿实验元数据）与测序数据（分析结果）。
        </p>
      </div>
    </div>

    <section class="card card--pad" style="margin-bottom: 16px">
      <form class="form" @submit.prevent="runSearch">
        <div class="field">
          <label class="field__label" for="q">关键词</label>
          <input
            id="q"
            v-model="query"
            class="input"
            placeholder="样本编号、菌株、谱系、物种、血清型、ST、基因…"
          />
        </div>
        <div class="search-fields">
          <div class="field">
            <label class="field__label" for="serotype">血清型</label>
            <input id="serotype" v-model="serotype" class="input" placeholder="例如 Enteritidis" />
          </div>
          <div class="field">
            <label class="field__label" for="mlst">MLST ST</label>
            <input id="mlst" v-model="mlst" class="input input--mono" placeholder="例如 11" />
          </div>
          <div class="field">
            <label class="field__label" for="gene">AMR / 毒力基因</label>
            <input id="gene" v-model="gene" class="input input--mono" placeholder="例如 blaCTX-M-15" />
          </div>
        </div>
        <div class="form__actions">
          <button
            v-if="searched"
            class="btn btn--ghost"
            type="button"
            :disabled="loading"
            @click="reset"
          >
            清空条件
          </button>
          <button class="btn btn--primary" type="submit" :disabled="loading">
            <span v-if="loading" class="spinner" />
            <Icon v-else name="search" />
            检索
          </button>
        </div>
      </form>
    </section>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <div v-if="loading" class="card card--pad">
      <div class="skeleton" style="height: 160px" />
    </div>

    <template v-else-if="searched">
      <section v-if="specimens.length" class="card" style="margin-bottom: 16px">
        <div class="card__head">
          <h2 class="card__title">样本</h2>
          <span class="card__hint">{{ specimenTotal }} 份</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">样本</th>
                <th scope="col">菌株数</th>
                <th scope="col">来源</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in specimens" :key="row.specimen_id">
                <td data-label="样本"><code>{{ row.specimen_id }}</code></td>
                <td data-label="菌株数" class="mono">{{ row.n_isolates ?? 0 }}</td>
                <td data-label="来源">{{ row.origin || '—' }}</td>
                <td data-label="">
                  <RouterLink class="btn btn--ghost btn--sm" :to="`/specimens/${row.specimen_id}`">
                    <Icon name="eye" />
                    样本页
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <Pager
          :offset="specimenOffset"
          :limit="specimenLimit"
          :total="specimenTotal"
          :disabled="loading"
          @update:offset="changeSpecimenPage"
          @update:limit="changeSpecimenLimit"
        />
      </section>

      <section v-if="isolates.length" class="card" style="margin-bottom: 16px">
        <div class="card__head">
          <h2 class="card__title">菌株</h2>
          <span class="card__hint">{{ isolateTotal }} 株</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">菌株</th>
                <th scope="col">样本</th>
                <th scope="col">谱系</th>
                <th scope="col">测序数据</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in isolates" :key="row.isolate_id">
                <td data-label="菌株"><code>{{ row.isolate_id }}</code></td>
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
                <td data-label="测序数据" class="mono">{{ row.n_libraries ?? 0 }}</td>
                <td data-label="">
                  <RouterLink class="btn btn--ghost btn--sm" :to="`/isolates/${row.isolate_id}`">
                    <Icon name="eye" />
                    菌株页
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <Pager
          :offset="isolateOffset"
          :limit="isolateLimit"
          :total="isolateTotal"
          :disabled="loading"
          @update:offset="changeIsolatePage"
          @update:limit="changeIsolateLimit"
        />
      </section>

      <section v-if="results.length" class="card">
        <div class="card__head">
          <h2 class="card__title">测序数据（分析结果）</h2>
          <span class="card__hint">{{ totalResults }} 份</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th scope="col">测序数据</th>
                <th scope="col">物种</th>
                <th scope="col">ST</th>
                <th scope="col">血清型</th>
                <th scope="col">CARD</th>
                <th scope="col">VFDB</th>
                <th scope="col"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in results" :key="row.sample_id">
                <td data-label="测序数据"><span class="link-cell">{{ row.sample_id }}</span></td>
                <td data-label="物种"><i>{{ displaySpecies(row.verdict) }}</i></td>
                <td data-label="ST" class="mono">{{ displayOrDash(row.st) }}</td>
                <td data-label="血清型">{{ displayOrDash(row.serovar) }}</td>
                <td data-label="CARD" class="mono">{{ row.n_card }}</td>
                <td data-label="VFDB" class="mono">{{ row.n_vfdb }}</td>
                <td data-label="">
                  <RouterLink class="btn btn--ghost btn--sm" :to="`/samples/${row.sample_id}`">
                    <Icon name="eye" />
                    结果页
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <Pager
          :offset="offset"
          :limit="limit"
          :total="totalResults"
          :disabled="loading"
          @update:offset="changePage"
          @update:limit="changeLimit"
        />
      </section>

      <EmptyState
        v-if="total === 0"
        title="没有匹配结果"
        hint="调整关键词或结构化过滤条件；样本、菌株与测序数据会一起检索。"
        icon="search"
      />
    </template>

    <EmptyState
      v-else
      title="开始检索"
      hint="输入关键词或使用血清型、ST、基因过滤；样本、菌株与测序数据会一起检索。"
      icon="search"
    />
  </div>
</template>

<style scoped>
.search-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 240px));
  gap: 16px 20px;
  align-items: start;
  margin: 4px 0 8px;
}
.search-fields .field {
  min-width: 0;
  margin: 0;
}
.search-fields :deep(.input) {
  width: 100%;
  box-sizing: border-box;
}
</style>
