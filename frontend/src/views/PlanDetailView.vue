<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import CopyButton from '../components/CopyButton.vue'
import Icon from '../components/Icon.vue'
import PlanBadge from '../components/PlanBadge.vue'
import { api } from '../api'
import type { PlanRecord, TaskEvent } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'
import { useToast } from '../composables/useToast'

const route = useRoute()
const toast = useToast()
const id = String(route.params.id)
const version = route.query.version ? Number(route.query.version) : undefined

const plan = ref<PlanRecord | null>(null)
const events = ref<TaskEvent[]>([])
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const submitting = ref(false)

const confirmer = ref('')
const hashInput = ref('')
const rejectReason = ref('')

const hashPrefix = computed(() => plan.value?.plan_hash.slice(0, 12) ?? '')

type ParamKind = 'text' | 'mono' | 'code' | 'samples' | 'run' | 'list' | 'nested'

interface ParamRow {
  key: string
  label: string
  kind: ParamKind
  text: string
  list: string[]
  value: unknown
}

interface TaskCard {
  index: number
  type: string
  raw: string
  rows: ParamRow[]
}

const paramLabels: Record<string, string> = {
  task_type: '类型',
  samples: '样本',
  fasta_dir: 'FASTA 目录',
  fastq_dir: 'FASTQ 目录',
  species: '物种',
  analysis: '分析',
  analysis_type: '分析类型',
  method: '方法',
  run_id: '运行 ID',
  sandbox_image: '沙箱镜像',
  image: '统计镜像',
  input_data_class: '输入数据级别',
  input_paths: '输入路径',
  input_files: '输入文件',
  objective: '目标',
  script: '脚本',
  draft: '成稿',
  known_citations: '已知引用',
  scope: '范围',
  gene: '基因',
  test_name: '检验',
  profile: '配置档',
  note: '备注',
  data_path: '数据路径',
  outcome: '结局',
  treatment: '处理',
  predictors: '预测变量',
  confounders: '混杂因素',
  group: '分组',
  time: '时间变量',
  event: '事件变量',
  alpha: '显著性水平',
}

const paramOrder = [
  'task_type',
  'samples',
  'fasta_dir',
  'fastq_dir',
  'species',
  'analysis',
  'analysis_type',
  'method',
  'run_id',
  'sandbox_image',
  'image',
  'input_data_class',
  'input_paths',
  'input_files',
  'objective',
  'script',
  'draft',
  'known_citations',
  'scope',
  'gene',
  'test_name',
  'profile',
  'note',
  'data_path',
  'outcome',
  'treatment',
  'predictors',
  'confounders',
  'group',
  'time',
  'event',
  'alpha',
]

function asText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return jsonText(value)
}

function asList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => asText(item))
  if (typeof value === 'string' && value.trim()) return [value.trim()]
  return []
}

function buildRow(key: string, value: unknown): ParamRow {
  const label = paramLabels[key] ?? key
  if (key === 'samples') {
    return { key, label, kind: 'samples', text: '', list: asList(value), value }
  }
  if (key === 'run_id') {
    return { key, label, kind: 'run', text: asText(value), list: [], value }
  }
  if (key === 'input_paths' || key === 'input_files' || key === 'known_citations') {
    return { key, label, kind: 'list', text: '', list: asList(value), value }
  }
  if (key === 'script' || key === 'draft') {
    return { key, label, kind: 'code', text: asText(value), list: [], value }
  }
  if (value !== null && typeof value === 'object') {
    return { key, label, kind: 'nested', text: '', list: [], value }
  }
  const mono =
    key === 'task_type' ||
    key === 'sandbox_image' ||
    key === 'image' ||
    key === 'input_data_class' ||
    key.endsWith('_dir') ||
    key.endsWith('_path')
  return { key, label, kind: mono ? 'mono' : 'text', text: asText(value), list: [], value }
}

const taskCards = computed<TaskCard[]>(() => {
  const tasks = plan.value?.tasks ?? []
  return tasks.map((task, index) => {
    const keys = Object.keys(task)
    const ordered = [
      ...paramOrder.filter((key) => keys.includes(key)),
      ...keys.filter((key) => !paramOrder.includes(key)),
    ]
    return {
      index,
      type: task.task_type,
      raw: jsonText(task),
      rows: ordered.map((key) => buildRow(key, task[key])),
    }
  })
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    plan.value = await api.getPlan(id, version)
    const eventData = await api.listEvents({ plan_id: id, limit: 100 })
    events.value = eventData.events.slice().reverse()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载计划失败'
  } finally {
    loading.value = false
  }
}

function useCurrentHash() {
  hashInput.value = hashPrefix.value
}

async function confirmPlan() {
  if (!plan.value) return
  if (!confirmer.value.trim()) {
    actionError.value = '确认人不能为空'
    return
  }
  if (hashInput.value.trim().length < 12) {
    actionError.value = '请输入计划哈希前 12 位以确认版本'
    return
  }
  submitting.value = true
  actionError.value = ''
  try {
    plan.value = await api.confirmPlan(plan.value.plan_id, {
      version: plan.value.version,
      plan_hash: hashInput.value.trim().toLowerCase(),
      confirmer: confirmer.value.trim(),
    })
    toast.ok('计划已确认并提交')
    await load()
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : '确认失败'
  } finally {
    submitting.value = false
  }
}

async function rejectPlan() {
  if (!plan.value) return
  if (!rejectReason.value.trim()) {
    actionError.value = '拒绝理由不能为空'
    return
  }
  if (!window.confirm('拒绝后该计划版本不会执行。确定拒绝？')) return
  submitting.value = true
  actionError.value = ''
  try {
    plan.value = await api.rejectPlan(plan.value.plan_id, {
      version: plan.value.version,
      reason: rejectReason.value.trim(),
    })
    toast.ok('计划已拒绝')
    await load()
  } catch (err) {
    actionError.value = err instanceof Error ? err.message : '拒绝失败'
  } finally {
    submitting.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/plans" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回计划
          </RouterLink>
        </div>
        <h1 class="pagehead__title">
          <span class="inline-actions" style="gap: 10px">
            <span class="mono" :title="plan?.plan_id ?? ''">
              {{ plan ? shortId(plan.plan_id, 16) : '计划详情' }}
            </span>
            <CopyButton v-if="plan" :value="plan.plan_id" label="计划 ID" />
          </span>
        </h1>
        <p class="pagehead__sub">计划详情 · 确认只对当前版本与哈希生效；修订后需要重新确认。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
    </template>

    <template v-else-if="plan">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <div class="detail-head" style="margin: 0">
                  <PlanBadge :state="plan.state" />
                  <span class="card__hint">
                    v{{ plan.version }} · hash {{ plan.plan_hash.slice(0, 16) }}… · {{ plan.created_by }}
                  </span>
                </div>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row">
                  <dt>完整哈希</dt>
                  <dd>
                    <span class="inline-actions" style="gap: 6px">
                      <span class="mono">{{ plan.plan_hash }}</span>
                      <CopyButton :value="plan.plan_hash" label="计划哈希" />
                    </span>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>创建时间</dt>
                  <dd class="mono">{{ fmtTime(plan.created_at) }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>理由</dt>
                  <dd>{{ plan.rationale || '—' }}</dd>
                </div>
                <div v-if="plan.confirmed_by" class="statuslist__row">
                  <dt>确认人</dt>
                  <dd>{{ plan.confirmed_by }} · {{ fmtTime(plan.confirmed_at) }}</dd>
                </div>
                <div v-if="plan.message" class="statuslist__row">
                  <dt>消息</dt>
                  <dd>{{ plan.message }}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">任务参数</h2>
              <span class="card__hint">{{ plan.tasks.length }} 个任务</span>
            </div>
            <div class="card__body stack">
              <div
                v-for="card in taskCards"
                :key="card.index"
                class="card card--pad"
                style="background: var(--surface-inset)"
              >
                <div class="inline-actions" style="margin-bottom: 8px">
                  <span class="badge badge--pending"><span class="badge__dot" /></span>
                  <span class="card__hint">任务 {{ card.index + 1 }}</span>
                  <code>{{ card.type }}</code>
                </div>
                <dl class="statuslist">
                  <div v-for="row in card.rows" :key="row.key" class="statuslist__row">
                    <dt>{{ row.label }}</dt>
                    <dd>
                      <template v-if="row.kind === 'samples'">
                        <span v-if="row.list.length === 0">—</span>
                        <span v-else class="inline-actions" style="gap: 8px">
                          <RouterLink
                            v-for="(sample, index) in row.list"
                            :key="index"
                            :to="`/samples/${sample}`"
                            class="link-cell"
                          >
                            {{ sample }}
                          </RouterLink>
                        </span>
                      </template>
                      <template v-else-if="row.kind === 'run'">
                        <RouterLink v-if="row.text" :to="`/runs/${row.text}`" class="link-cell">
                          {{ row.text }}
                        </RouterLink>
                        <span v-else>—</span>
                      </template>
                      <template v-else-if="row.kind === 'list'">
                        <span v-if="row.list.length === 0">—</span>
                        <ul v-else style="margin: 0; padding-left: 18px">
                          <li v-for="(item, index) in row.list" :key="index">
                            <code>{{ item }}</code>
                          </li>
                        </ul>
                      </template>
                      <pre
                        v-else-if="row.kind === 'nested'"
                        class="code-block"
                        style="max-height: 220px"
                      >{{ jsonText(row.value) }}</pre>
                      <pre
                        v-else-if="row.kind === 'code'"
                        class="code-block"
                        style="max-height: 220px"
                      >{{ row.text || '—' }}</pre>
                      <span v-else-if="row.kind === 'mono'" class="mono">{{ row.text || '—' }}</span>
                      <span v-else>{{ row.text || '—' }}</span>
                    </dd>
                  </div>
                </dl>
                <details style="margin-top: 12px">
                  <summary class="card__hint" style="cursor: pointer">原始参数（JSON）</summary>
                  <pre class="code-block" style="margin-top: 8px; max-height: 260px">{{ card.raw }}</pre>
                </details>
              </div>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">输入目录指纹</h2>
            </div>
            <div class="card__body">
              <div v-if="Object.keys(plan.inputs).length" class="stack">
                <div v-for="(fp, path) in plan.inputs" :key="path" class="kv">
                  <span class="kv__k">{{ path }}</span>
                  <span class="kv__v mono">{{ fp }}</span>
                </div>
              </div>
              <p v-else class="muted">无目录输入（仅已登记样本）。</p>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">计划事件</h2>
              <span class="card__hint">{{ events.length }} 条</span>
            </div>
            <div v-if="events.length" class="timeline">
              <div v-for="event in events" :key="event.seq" class="timeline__item">
                <span class="timeline__dot" aria-hidden="true" />
                <div>
                  <div class="timeline__top">
                    <span class="timeline__type">{{ event.type }}</span>
                    <span class="muted" style="font-size: 11.5px">{{ event.actor }}</span>
                    <span class="timeline__time">{{ fmtTime(event.occurred_at) }}</span>
                  </div>
                  <div class="timeline__body">{{ event.payload ? jsonText(event.payload) : '—' }}</div>
                </div>
              </div>
            </div>
            <div v-else class="empty" style="padding: 32px">
              <p class="empty__hint">暂无事件。</p>
            </div>
          </section>
        </div>

        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title" style="margin-bottom: 14px">版本信息</h2>
            <div class="meta-grid">
              <div class="meta-item">
                <dt>计划 ID</dt>
                <dd class="mono">{{ plan.plan_id }}</dd>
              </div>
              <div class="meta-item">
                <dt>版本</dt>
                <dd class="mono">v{{ plan.version }}</dd>
              </div>
              <div class="meta-item">
                <dt>创建者</dt>
                <dd>{{ plan.created_by }}</dd>
              </div>
              <div class="meta-item">
                <dt>状态</dt>
                <dd><PlanBadge :state="plan.state" /></dd>
              </div>
            </div>
            <div v-if="plan.task_ids.length" class="divider" style="margin: 16px 0" />
            <div v-if="plan.task_ids.length" class="stack">
              <div class="kv__k">已提交任务</div>
              <RouterLink
                v-for="tid in plan.task_ids"
                :key="tid"
                :to="`/tasks/${tid}`"
                class="link-cell"
                style="font-size: 11.5px"
              >
                {{ tid }}
              </RouterLink>
            </div>
          </section>

          <section
            v-if="plan.state === 'awaiting_confirmation'"
            class="card card--pad"
            style="border-top: 2px solid var(--st-await-dot)"
          >
            <h2 class="card__title">确认计划</h2>
            <p class="card__hint" style="margin: 4px 0 16px">
              核对参数与哈希后确认。确认事实由服务端记录，外部 Harness 不能代替。
            </p>
            <form class="form" @submit.prevent="confirmPlan">
              <div class="field">
                <label class="field__label" for="confirmer">确认人</label>
                <input id="confirmer" v-model="confirmer" class="input" required autocomplete="off" />
              </div>
              <div class="field">
                <label class="field__label" for="hash">
                  哈希前 12 位
                  <button type="button" class="btn btn--ghost btn--sm" style="margin-left: auto" @click="useCurrentHash">
                    填入当前
                  </button>
                </label>
                <input
                  id="hash"
                  v-model="hashInput"
                  class="input input--mono"
                  :placeholder="hashPrefix"
                  required
                  autocomplete="off"
                />
                <p class="field__hint">当前版本：{{ hashPrefix }}…</p>
              </div>
              <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>
              <div class="form__actions">
                <button class="btn btn--primary" type="submit" :disabled="submitting">
                  <span v-if="submitting" class="spinner" />
                  <Icon v-else name="check" />
                  确认并提交
                </button>
              </div>
            </form>

            <div class="divider" style="margin: 20px 0" />

            <form class="form" @submit.prevent="rejectPlan">
              <div class="field">
                <label class="field__label" for="reason">拒绝理由</label>
                <input id="reason" v-model="rejectReason" class="input" required autocomplete="off" />
              </div>
              <div class="form__actions">
                <button class="btn btn--danger" type="submit" :disabled="submitting">
                  <Icon name="ban" />
                  拒绝计划
                </button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
