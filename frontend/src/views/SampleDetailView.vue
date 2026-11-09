<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { SampleDetail } from '../types'
import { jsonText } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)
const data = ref<SampleDetail | null>(null)
const loading = ref(true)
const error = ref('')

const digest = computed(() => data.value?.digest)
const annotation = computed(() => {
  const steps = data.value?.steps ?? {}
  const ann = steps.annotation
  return ann && typeof ann === 'object' ? (ann as Record<string, unknown>) : null
})
const quast = computed(() => {
  const value = data.value?.steps?.assembly_quast
  return typeof value === 'string' ? value : ''
})
const topGenes = computed(() => {
  const list = annotation.value?.top_genes
  return Array.isArray(list) ? list : []
})
const annotationRate = computed(() => {
  const raw = Number(annotation.value?.annotation_rate ?? 0)
  return (raw <= 1 ? raw * 100 : raw).toFixed(1)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getSample(id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本详情失败'
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
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/samples" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回样本
          </RouterLink>
        </div>
        <h1 class="pagehead__title">{{ id }}</h1>
        <p class="pagehead__sub">分析结果详情、耐药/毒力基因与注释摘要。</p>
      </div>
      <div class="pagehead__actions">
        <a v-if="digest?.has_report" class="btn btn--ghost" :href="`/samples/${id}/report`" target="_blank" rel="noopener">
          <Icon name="file-text" />
          HTML 报告
        </a>
        <a v-if="digest?.has_report" class="btn btn--ghost" :href="`/samples/${id}/report?download=1`">
          <Icon name="arrow-right" />
          下载
        </a>
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="digest">
      <div class="detail-grid">
        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">结果概要</h2>
            <dl class="statuslist">
              <div class="statuslist__row"><dt>物种判定</dt><dd>{{ digest.verdict }}</dd></div>
              <div class="statuslist__row"><dt>MLST ST</dt><dd class="mono">{{ digest.st }}</dd></div>
              <div class="statuslist__row"><dt>血清型</dt><dd>{{ digest.serovar }}</dd></div>
              <div class="statuslist__row"><dt>DEC 判定</dt><dd>{{ digest.pathotype }}（ipaH：{{ digest.ipaH }}）</dd></div>
              <div class="statuslist__row"><dt>耐药基因（CARD）</dt><dd class="mono">{{ digest.n_card }}</dd></div>
              <div class="statuslist__row"><dt>毒力基因（VFDB）</dt><dd class="mono">{{ digest.n_vfdb }}</dd></div>
              <div class="statuslist__row"><dt>质粒（PlasmidFinder）</dt><dd class="mono">{{ digest.n_plasmid }}</dd></div>
            </dl>
          </section>

          <section v-if="digest.card_genes.length || digest.vfdb_genes.length || digest.plasmids.length" class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">检出基因</h2>
            <div v-if="digest.card_genes.length" class="stack" style="margin-bottom: 14px">
              <div class="kv__k">耐药（CARD）</div>
              <div class="inline-actions">
                <code v-for="gene in digest.card_genes" :key="`card-${gene}`">{{ gene }}</code>
              </div>
            </div>
            <div v-if="digest.vfdb_genes.length" class="stack" style="margin-bottom: 14px">
              <div class="kv__k">毒力（VFDB）</div>
              <div class="inline-actions">
                <code v-for="gene in digest.vfdb_genes" :key="`vf-${gene}`">{{ gene }}</code>
              </div>
            </div>
            <div v-if="digest.plasmids.length" class="stack">
              <div class="kv__k">质粒（PlasmidFinder）</div>
              <div class="inline-actions">
                <code v-for="gene in digest.plasmids" :key="`pl-${gene}`">{{ gene }}</code>
              </div>
            </div>
          </section>

          <section v-if="annotation" class="card">
            <div class="card__head">
              <h2 class="card__title">基因组注释</h2>
              <span class="card__hint">{{ annotation.status ?? '—' }}</span>
            </div>
            <div class="card__body">
              <div class="meta-grid">
                <div class="meta-item"><dt>CDS 总数</dt><dd class="mono">{{ annotation.total_CDS ?? '—' }}</dd></div>
                <div class="meta-item"><dt>已注释 CDS</dt><dd class="mono">{{ annotation.annotated_CDS ?? '—' }}</dd></div>
                <div class="meta-item">
                  <dt>注释率</dt>
                  <dd class="mono">{{ annotationRate }}%</dd>
                </div>
                <div class="meta-item">
                  <dt>eggNOG 已注释</dt>
                  <dd class="mono">{{ (annotation.eggnog as Record<string, unknown>)?.annotated ?? '—' }}</dd>
                </div>
              </div>
              <div v-if="topGenes.length" style="margin-top: 16px">
                <div class="kv__k" style="margin-bottom: 8px">重点基因</div>
                <div class="table-wrap">
                  <table class="table">
                    <thead><tr><th>基因</th><th>产物</th><th>来源</th></tr></thead>
                    <tbody>
                      <tr v-for="gene in topGenes" :key="String((gene as Record<string, unknown>).gene)">
                        <td><code>{{ (gene as Record<string, unknown>).gene }}</code></td>
                        <td>{{ (gene as Record<string, unknown>).product }}</td>
                        <td class="muted">{{ (gene as Record<string, unknown>).source }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div class="stack">
          <section v-if="quast" class="card">
            <div class="card__head"><h2 class="card__title">QUAST 组装质控</h2></div>
            <div class="card__body"><pre class="code-block">{{ quast }}</pre></div>
          </section>

          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">原始 summary</h2>
            <pre class="code-block">{{ jsonText(data?.summary) }}</pre>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
