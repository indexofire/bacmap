<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { ResearchLedgerEntry, ResearchSessionView } from '../types'
import { fmtTime, jsonText } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)
const view = ref<ResearchSessionView | null>(null)
const ledger = ref<ResearchLedgerEntry[]>([])
const loading = ref(true)
const error = ref('')

const stat = computed(() => view.value?.stat)
const session = computed(() => view.value?.session)
const hasFigure = computed(() =>
  view.value?.artifacts.some((artifact) => artifact.kind === 'figure'),
)

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

function artifactLink(kind: string): string | null {
  if (kind === 'figure') return `/api/v1/research/sessions/${id}/figure.svg`
  if (kind === 'report') return `/api/v1/research/sessions/${id}/report.md`
  if (kind === 'manuscript') return `/api/v1/research/sessions/${id}/manuscript.md`
  return null
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
                <code class="detail-id">{{ session.session_id }}</code>
                <p class="card__hint" style="margin-top: 4px">
                  run {{ session.run_id }} · {{ session.status }} · profile {{ session.profile }} · D{{ session.data_class }}
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
                  <dd><RouterLink class="link-cell" :to="`/research/studies/${session.study_id}`">{{ session.study_id }}</RouterLink></dd>
                </div>
                <div v-if="session.cohort_id" class="statuslist__row"><dt>Cohort</dt><dd class="mono">{{ session.cohort_id }}</dd></div>
                <div v-if="session.plan_id" class="statuslist__row"><dt>Plan</dt><dd class="mono">{{ session.plan_id }}</dd></div>
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
                <thead><tr><th>object</th><th>action</th><th>actor</th><th>time</th></tr></thead>
                <tbody>
                  <tr v-for="(entry, index) in ledger" :key="index">
                    <td class="mono">{{ entry.object_type }}:{{ entry.object_id }}</td>
                    <td>{{ entry.action }}</td>
                    <td>{{ entry.actor }}</td>
                    <td class="mono muted">{{ fmtTime(String(entry.created_at ?? '')) }}</td>
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
              <figure v-if="hasFigure" style="margin: 0">
                <img
                  :src="`/api/v1/research/sessions/${id}/figure.svg`"
                  alt="标准关联图"
                  style="width: 100%; border: 1px solid var(--border-subtle); border-radius: var(--r-ctl); background: #fff"
                />
                <figcaption class="card__hint" style="margin-top: 8px">标准关联图</figcaption>
              </figure>
              <p v-else class="muted">暂无标准图。</p>
              <div class="inline-actions" style="margin-top: 14px">
                <a class="btn btn--ghost btn--sm" :href="`/api/v1/research/sessions/${id}/report.md`" target="_blank" rel="noopener">
                  <Icon name="file-text" /> 报告 Markdown
                </a>
                <a class="btn btn--ghost btn--sm" :href="`/api/v1/research/sessions/${id}/manuscript.md`" target="_blank" rel="noopener">
                  <Icon name="file-text" /> 论文草案
                </a>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">全部产物</h2><span class="card__hint">{{ view.artifacts.length }} 项</span></div>
            <div v-if="view.artifacts.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>kind</th><th>sha256</th><th>下载</th></tr></thead>
                <tbody>
                  <tr v-for="art in view.artifacts" :key="art.kind">
                    <td>{{ art.kind }}</td>
                    <td class="mono muted" style="font-size: 10.5px">{{ art.sha256.slice(0, 16) }}…</td>
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

          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 12px">原始会话</h2>
            <pre class="code-block">{{ jsonText(view) }}</pre>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
