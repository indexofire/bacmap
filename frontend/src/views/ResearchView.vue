<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type {
  ResearchClaim,
  ResearchCohort,
  ResearchPlan,
  ResearchSession,
  ResearchStudy,
  RunRow,
} from '../types'
import { fmtTime, shortId } from '../lib/format'
import { useToast } from '../composables/useToast'

const toast = useToast()
const router = useRouter()
const tabs = [
  { key: 'sessions', label: '会话' },
  { key: 'studies', label: 'Studies' },
  { key: 'cohorts', label: 'Cohorts' },
  { key: 'plans', label: 'Plans' },
  { key: 'claims', label: 'Claims' },
] as const
const active = ref<(typeof tabs)[number]['key']>('sessions')

const sessions = ref<ResearchSession[]>([])
const studies = ref<ResearchStudy[]>([])
const cohorts = ref<ResearchCohort[]>([])
const plans = ref<ResearchPlan[]>([])
const claims = ref<ResearchClaim[]>([])
const runs = ref<RunRow[]>([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')

const form = ref({
  run_id: '',
  gene: '',
  test_name: '',
  profile: 'research',
  study_id: '',
  note: '',
})

const counts = computed(() => ({
  sessions: sessions.value.length,
  studies: studies.value.length,
  cohorts: cohorts.value.length,
  plans: plans.value.length,
  claims: claims.value.length,
}))

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, st, co, pl, cl, rn] = await Promise.all([
      api.listResearchSessions(100),
      api.listResearchStudies(100),
      api.listResearchCohorts(undefined, 100),
      api.listResearchPlans(undefined, 100),
      api.listResearchClaims(undefined, 100),
      api.listRuns(100),
    ])
    sessions.value = s
    studies.value = st
    cohorts.value = co
    plans.value = pl
    claims.value = cl
    runs.value = rn
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载研究数据失败'
  } finally {
    loading.value = false
  }
}

async function createSession() {
  busy.value = true
  error.value = ''
  try {
    const view = await api.createResearchSession({
      ...form.value,
      study_id: form.value.study_id || '',
      note: form.value.note,
    })
    toast.ok(`研究会话已创建：${view.session.session_id}`)
    form.value = {
      run_id: '',
      gene: '',
      test_name: '',
      profile: 'research',
      study_id: '',
      note: '',
    }
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建会话失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">研究</h1>
        <p class="pagehead__sub">
          AMR 关联会话、Study/Cohort/Plan/Claim 与证据链。P1 薄链路：不做因果/机制推断。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
        <RouterLink class="btn btn--ghost" to="/research/workbench">
          <Icon name="external-link" />
          高级研究工作台
        </RouterLink>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <div class="detail-grid">
      <section class="card">
        <div class="filters">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            class="chip"
            :class="{ 'is-active': active === tab.key }"
            @click="active = tab.key"
          >
            {{ tab.label }} · {{ counts[tab.key] }}
          </button>
        </div>

        <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

        <template v-else>
          <div v-if="active === 'sessions'">
            <div v-if="sessions.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>session</th><th>run</th><th>gene × test</th><th>profile</th><th>status</th><th>created</th></tr></thead>
                <tbody>
                  <tr
                    v-for="s in sessions"
                    :key="s.session_id"
                    class="row-click"
                    @click="goRow($event, `/research/sessions/${s.session_id}`)"
                  >
                    <td data-label="session">
                      <RouterLink class="link-cell" :to="`/research/sessions/${s.session_id}`">
                        {{ shortId(s.session_id) }}
                      </RouterLink>
                    </td>
                    <td data-label="run"><span class="mono muted">{{ shortId(s.run_id, 16) }}</span></td>
                    <td data-label="gene × test">{{ s.gene }} × {{ s.test_name }}</td>
                    <td data-label="profile"><code>{{ s.profile }}</code></td>
                    <td data-label="status"><code>{{ s.status }}</code><span v-if="s.label" class="muted"> · {{ s.label }}</span></td>
                    <td data-label="created"><span class="mono muted">{{ fmtTime(s.created_at) }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else title="暂无研究会话" hint="在右侧创建第一个 AMR 关联会话。" icon="chart" />
          </div>

          <div v-else-if="active === 'studies'">
            <div v-if="studies.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>study</th><th>question</th><th>status</th><th>D</th></tr></thead>
                <tbody>
                  <tr
                    v-for="s in studies"
                    :key="s.study_id"
                    class="row-click"
                    @click="goRow($event, `/research/studies/${s.study_id}`)"
                  >
                    <td data-label="study"><RouterLink class="link-cell" :to="`/research/studies/${s.study_id}`">{{ shortId(s.study_id) }}</RouterLink></td>
                    <td data-label="question">{{ s.question }}</td>
                    <td data-label="status"><code>{{ s.status }}</code></td>
                    <td data-label="D"><span class="mono">D{{ s.data_class }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else title="暂无 Study" hint="Study 由 MCP 研究请求或旧版研究页创建。" icon="plans" />
          </div>

          <div v-else-if="active === 'cohorts'">
            <div v-if="cohorts.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>cohort</th><th>study</th><th>status</th><th>members</th></tr></thead>
                <tbody>
                  <tr v-for="c in cohorts" :key="c.cohort_id">
                    <td data-label="cohort"><span class="mono">{{ shortId(c.cohort_id) }}</span></td>
                    <td data-label="study"><span class="mono muted">{{ shortId(c.study_id) }}</span></td>
                    <td data-label="status"><code>{{ c.status }}</code></td>
                    <td data-label="members"><span class="mono">{{ c.n_members ?? '—' }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else title="暂无 Cohort" hint="在 Study 页面创建并冻结队列。" icon="records" />
          </div>

          <div v-else-if="active === 'plans'">
            <div v-if="plans.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>plan</th><th>study</th><th>status</th></tr></thead>
                <tbody>
                  <tr v-for="p in plans" :key="p.plan_id">
                    <td data-label="plan"><span class="mono">{{ shortId(p.plan_id) }}</span></td>
                    <td data-label="study"><span class="mono muted">{{ shortId(p.study_id) }}</span></td>
                    <td data-label="status"><code>{{ p.status }}</code></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else title="暂无 AnalysisPlan" hint="在 Study 页面创建并冻结分析计划。" icon="plans" />
          </div>

          <div v-else>
            <div v-if="claims.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>claim</th><th>type</th><th>level</th><th>status</th><th>wording</th></tr></thead>
                <tbody>
                  <tr v-for="c in claims" :key="c.claim_id">
                    <td data-label="claim"><span class="mono">{{ shortId(c.claim_id) }}</span></td>
                    <td data-label="type">{{ c.claim_type }}</td>
                    <td data-label="level">{{ c.evidence_level }}</td>
                    <td data-label="status"><code>{{ c.status }}</code></td>
                    <td data-label="wording">{{ c.wording }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else title="暂无 Claim" hint="Claim 需要 Study 与证据链支持。" icon="check-circle" />
          </div>
        </template>
      </section>

      <aside class="stack">
        <section class="card card--pad">
          <h2 class="card__title">新建研究会话</h2>
          <p class="card__hint" style="margin: 4px 0 14px">
            从既有 run 生成确定性 AMR 关联统计、图、报告与论文草案。
          </p>
          <form class="form" @submit.prevent="createSession">
            <div class="field">
              <label class="field__label" for="r-run">运行记录</label>
              <select id="r-run" v-model="form.run_id" class="select" required>
                <option value="">请选择 run</option>
                <option v-for="run in runs" :key="run.run_id" :value="run.run_id">
                  {{ shortId(run.run_id, 16) }} · {{ run.strain_ids.join(', ') || '无样本' }}
                </option>
              </select>
              <p v-if="!runs.length" class="field__hint">暂无可用运行记录，请先完成一次分析。</p>
            </div>
            <div class="field">
              <label class="field__label" for="r-gene">基因</label>
              <input id="r-gene" v-model="form.gene" class="input" required placeholder="例如 blaKPC-33" />
            </div>
            <div class="field">
              <label class="field__label" for="r-test">表型检测</label>
              <input id="r-test" v-model="form.test_name" class="input" required placeholder="例如 meropenem" />
            </div>
            <div class="field">
              <label class="field__label" for="r-profile">治理 Profile</label>
              <select id="r-profile" v-model="form.profile" class="select">
                <option value="open-test">open-test</option>
                <option value="research">research</option>
                <option value="publication">publication</option>
              </select>
            </div>
            <div class="field">
              <label class="field__label" for="r-study">关联 Study <span class="field__optional">可选</span></label>
              <select id="r-study" v-model="form.study_id" class="select">
                <option value="">不关联</option>
                <option v-for="s in studies" :key="s.study_id" :value="s.study_id">{{ s.study_id }} · {{ s.question }}</option>
              </select>
            </div>
            <div class="field">
              <label class="field__label" for="r-note">研究说明 <span class="field__optional">可选</span></label>
              <textarea id="r-note" v-model="form.note" class="textarea" rows="3" />
            </div>
            <div class="form__actions">
              <button class="btn btn--primary" type="submit" :disabled="busy">
                <span v-if="busy" class="spinner" />
                <Icon v-else name="plus" />
                生成草案
              </button>
            </div>
          </form>
        </section>

        <section class="card card--pad">
          <h2 class="card__title" style="margin-bottom: 12px">高级研究工具</h2>
          <p class="card__hint" style="margin-bottom: 12px">
            系统发育与多变量 logistic 回归仍在旧版研究页；迁移到 SPA 的下一批。
          </p>
          <div class="inline-actions">
            <RouterLink class="btn btn--ghost btn--sm" to="/research/phylo"><Icon name="plans" /> 系统发育</RouterLink>
            <RouterLink class="btn btn--ghost btn--sm" to="/research/stats"><Icon name="chart" /> Logistic</RouterLink>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
