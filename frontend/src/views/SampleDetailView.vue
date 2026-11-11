<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import { api } from '../api'
import type { GvixbLink, RunRow, SampleDetail } from '../types'
import { appUrl, fmtTime, jsonText, shortId } from '../lib/format'
import { useTheme } from '../composables/useTheme'

const MAX_GENE_CHIPS = 24

const route = useRoute()
const router = useRouter()
const { resolved: resolvedTheme } = useTheme()
const id = String(route.params.id)
const data = ref<SampleDetail | null>(null)
const latestRun = ref<RunRow | null>(null)
const runsLoaded = ref(false)
const loading = ref(true)
const error = ref('')
const activeTab = ref<'detail' | 'report'>(route.query.tab === 'report' ? 'report' : 'detail')
const expandedGeneGroups = ref<Record<string, boolean>>({})

const reportSrc = computed(
  () => appUrl(`/samples/${encodeURIComponent(id)}/report?embed=1&theme=${resolvedTheme.value}`),
)
const reportDownload = computed(
  () => appUrl(`/samples/${encodeURIComponent(id)}/report?download=1&theme=${resolvedTheme.value}`),
)

const digest = computed(() => data.value?.digest)
const hasAnyReport = computed(() => Boolean(digest.value?.has_report || digest.value?.has_prelim_report))
const isPrelim = computed(() => !digest.value?.has_report && Boolean(digest.value?.has_prelim_report))
const showReport = computed(() => activeTab.value === 'report' && hasAnyReport.value)
const gvixbLinks = computed<GvixbLink[]>(() => {
  const items = data.value?.gvixb
  return Array.isArray(items) ? items : []
})
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
const speciesText = computed(() => {
  const verdict = digest.value?.verdict
  return isNotApplicable(verdict) ? '' : String(verdict).replace(/_/g, ' ')
})
const stText = computed(() => {
  const value = digest.value?.st
  return isNotApplicable(value) ? '' : String(value)
})
const serovarText = computed(() => {
  const value = digest.value?.serovar
  return isNotApplicable(value) ? '' : String(value)
})
const serogroupText = computed(() => {
  const serotype = data.value?.steps?.serotype
  if (!serotype || typeof serotype !== 'object') return ''
  const value = (serotype as Record<string, unknown>).serogroup
  return isNotApplicable(value) ? '' : String(value)
})
const pathotypeText = computed(() => {
  const value = digest.value?.pathotype
  return isNotApplicable(value) ? '' : String(value)
})
const ipaHText = computed(() => {
  const value = digest.value?.ipaH
  return isNotApplicable(value) ? '' : String(value)
})
const decText = computed(() => {
  const parts: string[] = []
  if (pathotypeText.value) parts.push(pathotypeText.value)
  if (ipaHText.value) parts.push(`ipaH：${ipaHText.value}`)
  return parts.join(' · ')
})
const geneGroups = computed(() => {
  const row = digest.value
  if (!row) return []
  return [
    { key: 'card', label: '耐药基因 · CARD', genes: row.card_genes },
    { key: 'vfdb', label: '毒力基因 · VFDB', genes: row.vfdb_genes },
    { key: 'plasmid', label: '质粒 · PlasmidFinder', genes: row.plasmids },
  ]
})
const activeGeneGroups = computed(() => geneGroups.value.filter((group) => group.genes.length > 0))
const latestRunStartedAt = computed(() => {
  const value = latestRun.value?.started_at
  return typeof value === 'string' ? value : ''
})

function isNotApplicable(value: unknown): boolean {
  if (value === null || value === undefined) return true
  const text = String(value).trim()
  return text === '' || /^(n\/?a|none|null|-|unknown)$/i.test(text)
}

function runStrainIds(run: RunRow): string[] {
  const ids = run.strain_ids
  return Array.isArray(ids) ? ids.filter((value): value is string => typeof value === 'string') : []
}

function visibleGenes(key: string, genes: string[]): string[] {
  return expandedGeneGroups.value[key] ? genes : genes.slice(0, MAX_GENE_CHIPS)
}

function toggleGeneGroup(key: string) {
  expandedGeneGroups.value = {
    ...expandedGeneGroups.value,
    [key]: !expandedGeneGroups.value[key],
  }
}

async function load() {
  loading.value = true
  error.value = ''
  runsLoaded.value = false
  try {
    const [sample, runs] = await Promise.all([
      api.getSample(id),
      api.listRuns(100).catch(() => [] as RunRow[]),
    ])
    data.value = sample
    latestRun.value = runs.find((run) => runStrainIds(run).includes(id)) ?? null
    runsLoaded.value = true
    if (activeTab.value === 'report' && !data.value.digest.has_report && !data.value.digest.has_prelim_report) activeTab.value = 'detail'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本详情失败'
  } finally {
    loading.value = false
  }
}

function openReport() {
  if (!hasAnyReport.value) return
  activeTab.value = 'report'
  void router.replace({ query: { ...route.query, tab: 'report' } })
}

function openDetail() {
  activeTab.value = 'detail'
  const query = { ...route.query }
  delete query.tab
  void router.replace({ query })
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
        <h1 class="pagehead__title inline-actions">
          <span>{{ id }}</span>
          <CopyButton :value="id" label="样本 ID" />
        </h1>
        <p class="pagehead__sub">分析结果详情、耐药/毒力基因、注释摘要与完整 HTML 报告。</p>
      </div>
      <div class="pagehead__actions">
        <button v-if="hasAnyReport" class="btn btn--primary" type="button" @click="openReport">
          <Icon name="file-text" />
          查看报告
        </button>
        <a v-if="digest?.has_report" class="btn btn--ghost" :href="reportDownload">
          <Icon name="arrow-right" />
          下载报告
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
      <div class="filters" style="margin-bottom: 14px">
        <button
          type="button"
          class="chip"
          :class="{ 'is-active': activeTab === 'detail' }"
          @click="openDetail"
        >
          概览
        </button>
        <button
          v-if="hasAnyReport"
          type="button"
          class="chip"
          :class="{ 'is-active': showReport }"
          @click="openReport"
        >
          完整报告
        </button>
      </div>

      <section v-if="showReport" class="card report-embed">
        <div class="card__head">
          <h2 class="card__title">完整分析报告 <span v-if="isPrelim" class="badge badge--running">初步 · 注释进行中</span></h2>
          <span class="card__hint">{{ resolvedTheme === 'light' ? '浅色主题' : resolvedTheme === 'gray' ? '灰色主题' : '暗色主题' }} · 自包含 HTML</span>
          <a class="btn btn--ghost btn--sm" :href="reportDownload">下载 HTML</a>
        </div>
        <iframe class="report-frame" :src="reportSrc" title="样本完整分析报告" />
      </section>

      <div v-else class="stack">
        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">结果概要</h2>
            <dl class="statuslist summary-list">
              <div class="statuslist__row">
                <dt>物种判定</dt>
                <dd>
                  <em v-if="speciesText">{{ speciesText }}</em>
                  <span v-else class="muted">不适用</span>
                </dd>
              </div>
              <div class="statuslist__row"><dt>MLST ST</dt><dd class="mono">{{ stText || '未分型' }}</dd></div>
              <div v-if="serovarText" class="statuslist__row"><dt>血清型</dt><dd>{{ serovarText }}</dd></div>
              <div v-if="serogroupText" class="statuslist__row"><dt>血清群</dt><dd>{{ serogroupText }}</dd></div>
              <div v-if="decText" class="statuslist__row"><dt>DEC 判定</dt><dd>{{ decText }}</dd></div>
              <div class="statuslist__row"><dt>耐药基因（CARD）</dt><dd class="mono">{{ digest.n_card }}</dd></div>
              <div class="statuslist__row"><dt>毒力基因（VFDB）</dt><dd class="mono">{{ digest.n_vfdb }}</dd></div>
              <div class="statuslist__row"><dt>质粒（PlasmidFinder）</dt><dd class="mono">{{ digest.n_plasmid }}</dd></div>
              <div v-if="runsLoaded" class="statuslist__row">
                <dt>最近运行</dt>
                <dd v-if="latestRun">
                  <RouterLink
                    class="link-cell"
                    :to="`/runs/${encodeURIComponent(latestRun.run_id)}`"
                    :title="latestRun.run_id"
                  >
                    {{ shortId(latestRun.run_id, 18) }}
                  </RouterLink>
                  <span v-if="latestRunStartedAt" class="muted"> · {{ fmtTime(latestRunStartedAt) }}</span>
                </dd>
                <dd v-else class="muted">未找到关联运行记录</dd>
              </div>
              <div v-if="latestRun?.task_id" class="statuslist__row">
                <dt>关联任务</dt>
                <dd>
                  <RouterLink
                    class="link-cell"
                    :to="`/tasks/${encodeURIComponent(latestRun.task_id)}`"
                    :title="latestRun.task_id"
                  >
                    {{ shortId(latestRun.task_id, 18) }}
                  </RouterLink>
                </dd>
              </div>
              <div v-if="gvixbLinks.length" class="statuslist__row">
                <dt>3D 可视化</dt>
                <dd>
                  <a
                    v-for="view in gvixbLinks"
                    :key="view.id"
                    class="link-cell"
                    :href="view.url"
                    style="margin-right: 12px"
                  >
                    {{ view.label.replace('使用 gvixb ', '') }}
                  </a>
                </dd>
              </div>
            </dl>
          </section>

          <section v-if="activeGeneGroups.length" class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">检出基因</h2>
            <div v-for="group in activeGeneGroups" :key="group.key" class="gene-group">
              <div class="gene-group__head">
                <span class="kv__k">{{ group.label }}（{{ group.genes.length }}）</span>
                <button
                  v-if="group.genes.length > MAX_GENE_CHIPS"
                  class="btn btn--ghost btn--sm"
                  type="button"
                  @click="toggleGeneGroup(group.key)"
                >
                  {{ expandedGeneGroups[group.key] ? '收起' : `显示全部 (${group.genes.length})` }}
                </button>
              </div>
              <div class="inline-actions gene-chips">
                <code v-for="gene in visibleGenes(group.key, group.genes)" :key="`${group.key}-${gene}`">{{ gene }}</code>
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
        </div>
      </div>

      <details class="card dev-details">
        <summary class="dev-details__summary">
          <span class="dev-details__label">
            <Icon name="chevron-right" class="dev-details__chevron" :size="14" />
            开发者数据（原始 summary JSON）
          </span>
          <span class="card__hint">默认折叠</span>
        </summary>
        <div class="card__body">
          <pre class="code-block">{{ jsonText(data?.summary) }}</pre>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.report-embed {
  overflow: hidden;
}

.report-frame {
  display: block;
  width: 100%;
  height: max(760px, calc(100vh - 250px));
  border: 0;
  background: var(--bg);
  color-scheme: dark;
}

.summary-list :deep(.statuslist__row) {
  grid-template-columns: 148px minmax(0, 1fr);
}

.gene-group + .gene-group {
  margin-top: 16px;
}

.gene-group__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.dev-details {
  margin-top: var(--sp-4);
}

.dev-details__summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: 16px var(--sp-5);
  color: var(--text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.dev-details__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dev-details__chevron {
  color: var(--text-3);
  transition: transform var(--t-micro) var(--ease-out);
}

.dev-details[open] .dev-details__summary {
  border-bottom: 1px solid var(--border-subtle);
}

.dev-details[open] .dev-details__chevron {
  transform: rotate(90deg);
}

@media (max-width: 720px) {
  .report-frame {
    height: max(640px, calc(100vh - 220px));
  }

  .summary-list :deep(.statuslist__row) {
    grid-template-columns: 120px minmax(0, 1fr);
  }
}
</style>
