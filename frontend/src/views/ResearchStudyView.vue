<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import { api } from '../api'
import type { ResearchClaim, ResearchCohort, ResearchPlan, ResearchStudy } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)
const study = ref<ResearchStudy | null>(null)
const cohorts = ref<ResearchCohort[]>([])
const plans = ref<ResearchPlan[]>([])
const claims = ref<ResearchClaim[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, co, pl, cl] = await Promise.all([
      api.getResearchStudy(id),
      api.listResearchCohorts(id, 100),
      api.listResearchPlans(id, 100),
      api.listResearchClaims(id, 100),
    ])
    study.value = s
    cohorts.value = co
    plans.value = pl
    claims.value = cl
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 Study 失败'
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
        <h1 class="pagehead__title">Study</h1>
        <p class="pagehead__sub">研究问题、Cohort、AnalysisPlan 与 Claim 的只读视图。</p>
      </div>
      <div class="pagehead__actions">
        <RouterLink class="btn btn--ghost" :to="`/research/studies/${id}/package`">
          <Icon name="file-text" />
          打包
        </RouterLink>
        <RouterLink class="btn btn--ghost" :to="`/research/studies/${id}/workbench`">
          <Icon name="external-link" />
          高级操作
        </RouterLink>
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="study">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <code class="detail-id">{{ study.study_id }}</code>
                <p class="card__hint" style="margin-top: 4px">
                  {{ study.status }} · D{{ study.data_class }} · {{ study.pathogen_scope || 'all pathogens' }}
                </p>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row"><dt>研究问题</dt><dd>{{ study.question }}</dd></div>
                <div class="statuslist__row"><dt>病原范围</dt><dd>{{ study.pathogen_scope || '—' }}</dd></div>
                <div class="statuslist__row"><dt>数据级别</dt><dd class="mono">D{{ study.data_class }}</dd></div>
                <div class="statuslist__row"><dt>状态</dt><dd><code>{{ study.status }}</code></dd></div>
                <div v-if="study.created_at" class="statuslist__row"><dt>创建时间</dt><dd class="mono">{{ fmtTime(String(study.created_at)) }}</dd></div>
              </dl>
            </div>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">Cohorts</h2><span class="card__hint">{{ cohorts.length }} 个</span></div>
            <div v-if="cohorts.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>cohort</th><th>status</th><th>members</th></tr></thead>
                <tbody>
                  <tr v-for="c in cohorts" :key="c.cohort_id">
                    <td class="mono">{{ shortId(c.cohort_id) }}</td>
                    <td><code>{{ c.status }}</code></td>
                    <td class="mono">{{ c.n_members ?? '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted" style="padding: 20px">暂无 Cohort。</p>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">AnalysisPlans</h2><span class="card__hint">{{ plans.length }} 个</span></div>
            <div v-if="plans.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>plan</th><th>status</th></tr></thead>
                <tbody>
                  <tr v-for="p in plans" :key="p.plan_id">
                    <td class="mono">{{ shortId(p.plan_id) }}</td>
                    <td><code>{{ p.status }}</code></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted" style="padding: 20px">暂无 AnalysisPlan。</p>
          </section>

          <section class="card">
            <div class="card__head"><h2 class="card__title">Claims</h2><span class="card__hint">{{ claims.length }} 个</span></div>
            <div v-if="claims.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>claim</th><th>type</th><th>level</th><th>status</th><th>wording</th></tr></thead>
                <tbody>
                  <tr v-for="c in claims" :key="c.claim_id">
                    <td class="mono">{{ shortId(c.claim_id) }}</td>
                    <td>{{ c.claim_type }}</td>
                    <td>{{ c.evidence_level }}</td>
                    <td><code>{{ c.status }}</code></td>
                    <td>{{ c.wording }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted" style="padding: 20px">暂无 Claim。</p>
          </section>
        </div>

        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 12px">原始 Study</h2>
            <pre class="code-block">{{ jsonText(study) }}</pre>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
