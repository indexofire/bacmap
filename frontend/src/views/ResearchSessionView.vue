<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import { api } from '../api'
import type { ResearchArtifact, ResearchLedgerEntry, ResearchSessionView } from '../types'
import { fmtBytes, fmtTime, jsonText } from '../lib/format'

const ARTIFACT_LABELS: Record<string, string> = {
  figure: '图',
  figure_custom: '自定义图',
  figure_manifest: '图清单',
  figure_spec: '图规格',
  manuscript: '论文草案',
  report: '报告',
}

type LedgerFields = ResearchLedgerEntry & {
  event?: unknown
  payload_json?: unknown
  at?: unknown
}

type ArtifactWithSize = ResearchArtifact & { size?: number | string; size_bytes?: number | string }

const route = useRoute()
const id = String(route.params.id)
const view = ref<ResearchSessionView | null>(null)
const ledger = ref<ResearchLedgerEntry[]>([])
const loading = ref(true)
const error = ref('')

const stat = computed(() => view.value?.stat)
const session = computed(() => view.value?.session)
const figureUrl = computed(() => `/api/v1/research/sessions/${encodeURIComponent(id)}/figure.svg`)
const hasFigure = computed(
  () => view.value?.artifacts.some((artifact) => artifact.kind === 'figure') ?? false,
)
const hasArtifactSize = computed(
  () => view.value?.artifacts.some((artifact) => artifactSizeBytes(artifact) !== null) ?? false,
)

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function clip(value: string, size = 72): string {
  return value.length > size ? `${value.slice(0, size)}…` : value
}

function parsePayload(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    return null
  }
}

function payloadSummary(value: unknown): string {
  const parsed = parsePayload(value)
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const parts: string[] = []
    for (const [key, item] of Object.entries(parsed as Record<string, unknown>)) {
      if (item === null || item === undefined || item === '') continue
      if (typeof item === 'object') continue
      parts.push(`${key}=${String(item)}`)
      if (parts.length >= 3) break
    }
    if (parts.length) return clip(parts.join(' · '))
    const serialized = JSON.stringify(parsed)
    return serialized && serialized !== '{}' ? clip(serialized) : '—'
  }
  if (typeof parsed === 'string' && parsed.trim()) return clip(parsed.trim())
  if (typeof value === 'string' && value.trim()) return clip(value.trim())
  return '—'
}

function ledgerObject(entry: ResearchLedgerEntry): string {
  const fields = entry as LedgerFields
  const objectType = text(fields.object_type)
  const objectId = text(fields.object_id)
  if (objectType && objectId) return `${objectType}:${objectId}`
  if (objectType) return objectType
  if (objectId) return objectId
  return payloadSummary(fields.payload_json)
}

function ledgerEvent(entry: ResearchLedgerEntry): string {
  return text((entry as LedgerFields).event) || '—'
}

function ledgerActor(entry: ResearchLedgerEntry): string {
  return text((entry as LedgerFields).actor) || '—'
}

function ledgerAt(entry: ResearchLedgerEntry): string {
  return text((entry as LedgerFields).at)
}

function artifactLabel(kind: string): string {
  return ARTIFACT_LABELS[kind] ?? kind
}

function artifactSizeBytes(artifact: ResearchArtifact): number | null {
  const field = artifact as ArtifactWithSize
  const value = field.size ?? field.size_bytes
  const bytes = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  return Number.isFinite(bytes) && bytes > 0 ? bytes : null
}

function artifactSize(artifact: ResearchArtifact): string {
  const bytes = artifactSizeBytes(artifact)
  return bytes === null ? '' : fmtBytes(bytes)
}

function artifactLink(kind: string): string | null {
  if (kind === 'figure') return `/api/v1/research/sessions/${encodeURIComponent(id)}/figure.svg`
  if (kind === 'report') return `/api/v1/research/sessions/${encodeURIComponent(id)}/report.md`
  if (kind === 'manuscript') {
    return `/api/v1/research/sessions/${encodeURIComponent(id)}/manuscript.md`
  }
  return null
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [sessionView, ledgerItems] = await Promise.all([
      api.getResearchSession(id),
      api.getResearchLedger(id),
    ])
    view.value = sessionView
    ledger.value = ledgerItems
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载研究会话失败'
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
          <RouterLink to="/research" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回研究
          </RouterLink>
        </div>
        <h1 class="pagehead__title">
          {{ session ? `${session.gene} × ${session.test_name}` : '研究会话' }}
        </h1>
        <p class="pagehead__sub">确定性 AMR 关联统计、图、报告与论文草案。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="view && session">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <div class="inline-actions">
                  <code class="detail-id">{{ session.session_id }}</code>
                  <CopyButton :value="session.session_id" label="会话 ID" />
                </div>
                <p class="card__hint" style="margin-top: 4px">
                  <RouterLink
                    v-if="session.run_id"
                    class="link-cell"
                    :to="`/runs/${encodeURIComponent(session.run_id)}`"
                  >
                    run {{ session.run_id }}
                  </RouterLink>
                  <span v-else>run —</span>
                  · {{ session.status }} · profile {{ session.profile }} · D{{ session.data_class }}
                </p>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row"><dt>标签</dt><dd>{{ session.label || '—' }}</dd></div>
                <div class="statuslist__row"><dt>创建者</dt><dd>{{ session.created_by }}</dd></div>
                <div class="statuslist__row"><dt>创建时间</dt><dd class="mono">{{ fmtTime(session.created_at) }}</dd></div>
                <div v-if="session.study_id" class="statuslist__row">
                  <dt>Study</dt>
                  <dd>
                    <RouterLink
                      class="link-cell"
                      :to="`/research/studies/${encodeURIComponent(session.study_id)}`"
                    >
                      {{ session.study_id }}
                    </RouterLink>
                  </dd>
                </div>
                <div v-if="session.cohort_id" class="statuslist__row">
                  <dt>Cohort</dt>
                  <dd><code>{{ session.cohort_id }}</code></dd>
                </div>
                <div v-if="session.plan_id" class="statuslist__row">
                  <dt>Plan</dt>
                  <dd>
                    <RouterLink class="link-cell" :to="`/plans/${encodeURIComponent(session.plan_id)}`">
                      {{ session.plan_id }}
                    </RouterLink>
                  </dd>
                </div>
                <div v-if="session.note" class="statuslist__row"><dt>说明</dt><dd>{{ session.note }}</dd></div>
              </dl>
            </div>
          </section>

          <section v-if="stat" class="card">
            <div class="card__head"><h2 class="card__title">统计结果</h2></div>
            <div class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead><tr><th>组</th><th>计数</th></tr></thead>
                  <tbody>
                    <tr><td>gene+ / resistant</td><td class="mono">{{ stat.table.gene_pos_resistant }}</td></tr>
                    <tr><td>gene+ / susceptible</td><td class="mono">{{ stat.table.gene_pos_susceptible }}</td></tr>
                    <tr><td>gene- / resistant</td><td class="mono">{{ stat.table.gene_neg_resistant }}</td></tr>
                    <tr><td>gene- / susceptible</td><td class="mono">{{ stat.table.gene_neg_susceptible }}</td></tr>
                  </tbody>
                </table>
              </div>
              <p class="card__hint" style="margin-top: 12px">
                n={{ stat.n }} ·
                OR={{ stat.odds_ratio ?? 'NA' }}
                <template v-if="stat.ci_low !== null && stat.ci_high !== null">（95% CI {{ stat.ci_low }}–{{ stat.ci_high }}）</template>
                · p={{ stat.p_value ?? 'NA' }}
              </p>
              <p v-if="stat.diagnostics.length" class="card__hint">诊断：{{ stat.diagnostics.join('; ') }}</p>
            </div>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">证据链</h2><span class="card__hint">{{ ledger.length }} 条</span></div>
            <div v-if="ledger.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>事件</th><th>对象</th><th>操作者</th><th>时间</th></tr></thead>
                <tbody>
                  <tr v-for="(entry, index) in ledger" :key="entry.seq ?? index">
                    <td>{{ ledgerEvent(entry) }}</td>
                    <td class="mono">{{ ledgerObject(entry) }}</td>
                    <td>{{ ledgerActor(entry) }}</td>
                    <td class="mono muted">{{ fmtTime(ledgerAt(entry)) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted" style="padding: 20px">暂无 ledger 记录。</p>
          </section>
        </div>

        <div class="stack">
          <section class="card">
            <div class="card__head"><h2 class="card__title">图与产物</h2></div>
            <div class="card__body">
              <figure v-if="hasFigure" class="figure-block">
                <div class="figure-canvas">
                  <img :src="figureUrl" alt="标准关联图" class="figure-canvas__img" loading="lazy" />
                </div>
                <figcaption class="figure-caption">
                  <div>
                    <div class="figure-caption__title">图 · 标准关联图</div>
                    <div class="card__hint">白底 SVG，保留原始配色与宽高比；标签较小时请在新窗口打开查看。</div>
                  </div>
                  <a class="btn btn--ghost btn--sm" :href="figureUrl" target="_blank" rel="noopener">
                    <Icon name="external-link" />
                    在新窗口打开
                  </a>
                </figcaption>
              </figure>
              <p v-else class="muted">暂无标准图。</p>
              <div class="inline-actions" style="margin-top: 14px">
                <a class="btn btn--ghost btn--sm" :href="`/api/v1/research/sessions/${encodeURIComponent(id)}/report.md`" target="_blank" rel="noopener">
                  <Icon name="file-text" /> 报告 Markdown
                </a>
                <a class="btn btn--ghost btn--sm" :href="`/api/v1/research/sessions/${encodeURIComponent(id)}/manuscript.md`" target="_blank" rel="noopener">
                  <Icon name="file-text" /> 论文草案
                </a>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">全部产物</h2><span class="card__hint">{{ view.artifacts.length }} 项</span></div>
            <div v-if="view.artifacts.length" class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>类型</th>
                    <th>sha256</th>
                    <th v-if="hasArtifactSize">大小</th>
                    <th>打开</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="art in view.artifacts" :key="`${art.kind}-${art.sha256}`">
                    <td :title="art.kind">{{ artifactLabel(art.kind) }}</td>
                    <td class="mono muted" style="font-size: 10.5px" :title="art.sha256">{{ art.sha256.slice(0, 16) }}…</td>
                    <td v-if="hasArtifactSize" class="mono muted">{{ artifactSize(art) || '—' }}</td>
                    <td>
                      <a v-if="artifactLink(art.kind)" :href="artifactLink(art.kind)!" target="_blank" rel="noopener">打开</a>
                      <span v-else class="muted">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty" style="padding: 24px"><p class="empty__hint">暂无产物。</p></div>
          </section>
        </div>
      </div>

      <details class="card dev-details">
        <summary class="dev-details__summary">
          <span class="dev-details__label">
            <Icon name="chevron-right" class="dev-details__chevron" :size="14" />
            原始会话 JSON
          </span>
          <span class="card__hint">默认折叠</span>
        </summary>
        <div class="card__body">
          <pre class="code-block">{{ jsonText(view) }}</pre>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.figure-block {
  margin: 0;
}

.figure-canvas {
  padding: 14px;
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-ctl);
  background: #f6f7f8;
}

.figure-canvas__img {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
}

.figure-caption {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-top: 10px;
}

.figure-caption__title {
  margin-bottom: 2px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 600;
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
</style>
