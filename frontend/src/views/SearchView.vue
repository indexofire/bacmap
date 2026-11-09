<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { SampleRow } from '../types'

const route = useRoute()
const router = useRouter()

const query = ref(String(route.query.q ?? ''))
const serotype = ref(String(route.query.serotype ?? ''))
const mlst = ref(String(route.query.mlst_st ?? ''))
const gene = ref(String(route.query.amr_gene ?? ''))
const results = ref<SampleRow[]>([])
const loading = ref(false)
const searched = ref(false)
const error = ref('')

async function runSearch() {
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    results.value = await api.search({
      q: query.value.trim(),
      serotype: serotype.value.trim(),
      mlst_st: mlst.value.trim(),
      amr_gene: gene.value.trim(),
    })
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
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">样本检索</h1>
        <p class="pagehead__sub">
          按物种、血清型、MLST 或耐药/毒力基因检索已完成分析的样本。
        </p>
      </div>
    </div>

    <section class="card card--pad" style="margin-bottom: 16px">
      <form class="form" @submit.prevent="runSearch">
        <div class="field">
          <label class="field__label" for="q">关键词</label>
          <input id="q" v-model="query" class="input" placeholder="物种、血清型、ST、基因…" />
        </div>
        <div class="meta-grid">
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
          <button class="btn btn--primary" type="submit" :disabled="loading">
            <span v-if="loading" class="spinner" />
            <Icon v-else name="search" />
            检索
          </button>
        </div>
      </form>
    </section>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="card__head">
        <h2 class="card__title">结果</h2>
        <span class="card__hint">{{ results.length }} 个样本</span>
      </div>
      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 160px" /></div>
      <div v-else-if="results.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">样本</th>
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
              <td data-label="样本"><span class="link-cell">{{ row.sample_id }}</span></td>
              <td data-label="物种">{{ row.verdict }}</td>
              <td data-label="ST" class="mono">{{ row.st }}</td>
              <td data-label="血清型">{{ row.serovar }}</td>
              <td data-label="CARD" class="mono">{{ row.n_card }}</td>
              <td data-label="VFDB" class="mono">{{ row.n_vfdb }}</td>
              <td data-label="">
                <RouterLink class="btn btn--ghost btn--sm" :to="`/samples/${row.sample_id}`">
                  <Icon name="eye" />
                  样本页
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else-if="searched"
        title="没有匹配的样本"
        hint="调整关键词或结构化过滤条件。"
        icon="search"
      />
      <EmptyState
        v-else
        title="开始检索"
        hint="输入关键词或使用血清型、ST、基因过滤。"
        icon="search"
      />
    </section>
  </div>
</template>
