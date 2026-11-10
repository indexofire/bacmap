<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import { api } from '../api'
import type { RunRow } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'

interface ToolVersionRow {
  name: string
  version: string
}

interface RefDatabaseRow {
  name: string
  version: string
  checksum: string
}

const route = useRoute()
const id = String(route.params.id)

const run = ref<RunRow | null>(null)
const otherRuns = ref<RunRow[]>([])
const otherRunsLoading = ref(false)
const otherRunsError = ref('')
const compareWith = ref('')
const compare = ref<Record<string, unknown> | null>(null)
const loading = ref(true)
const comparing = ref(false)
const error = ref('')
const compareError = ref('')

const sectionLabels: Record<string, string> = {
  resolved_config: '解析后配置',
  input_files: '输入文件哈希',
  seeds: '随机种子',
  nondeterministic_steps: '非确定性步骤',
  host: '主机信息',
}

function fmtDuration(started?: string | null, finished?: string | null): string {
  if (!started) return '—'
  if (!finished) return '运行中'
  const start = new Date(started).getTime()
  const end = new Date(finished).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '—'
  const total = Math.round((end - start) / 1000)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function toolVersionRows(value: unknown): ToolVersionRow[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>)
    .map(([name, version]) => ({
      name,
      version: typeof version === 'string' ? version : jsonText(version),
    }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

function refDatabaseRows(value: unknown): RefDatabaseRow[] {
  const items: unknown[] = Array.isArray(value) ? value : []
  return items
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      name: typeof item.name === 'string' ? item.name : '—',
      version: typeof item.version === 'string' ? item.version : String(item.version ?? '—'),
      checksum: typeof item.checksum === 'string' ? item.checksum : '',
    }))
}

const toolVersions = computed(() => toolVersionRows(run.value?.tool_versions))
const refDatabases = computed(() => refDatabaseRows(run.value?.ref_databases))

const sections = computed(() => {
  const current = run.value
  if (!current) return []
  const preferred = ['resolved_config', 'input_files', 'seeds', 'nondeterministic_steps', 'host']
  return preferred
    .filter((key) => key in current)
    .map((key) => ({ key, label: sectionLabels[key] ?? key, value: current[key] }))
})

function compareOption(other: RunRow): string {
  const task = other.task_id ? `任务 ${shortId(other.task_id)}` : '无任务'
  const strains = other.strain_ids.length ? other.strain_ids.join(', ') : '无样本'
  return `${shortId(other.run_id, 16)} · ${task} · ${strains}`
}

async function loadOtherRuns() {
  otherRunsLoading.value = true
  otherRunsError.value = ''
  try {
    const items = await api.listRuns(100)
    otherRuns.value = items.filter((item) => item.run_id !== id)
  } catch (err) {
    otherRunsError.value = err instanceof Error ? err.message : '加载其它运行记录失败'
  } finally {
    otherRunsLoading.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    run.value = await api.getRun(id)
    void loadOtherRuns()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载运行记录失败'
  } finally {
    loading.value = false
  }
}

async function compareRuns() {
  if (!compareWith.value) return
  comparing.value = true
  compareError.value = ''
  try {
    compare.value = await api.compareRuns(id, compareWith.value)
  } catch (err) {
    compareError.value = err instanceof Error ? err.message : '比较失败'
    compare.value = null
  } finally {
    comparing.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink to="/runs" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回运行记录
          </RouterLink>
        </div>
        <h1 class="pagehead__title">
          {{ run ? shortId(run.run_id, 16) : '运行详情' }}
        </h1>
        <p class="pagehead__sub">不可变证据：工具版本、参考库、配置与输入指纹。</p>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
    </template>

    <template v-else-if="run">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <div>
                <div class="detail-head" style="margin: 0">
                  <code class="detail-id">{{ run.run_id }}</code>
                  <CopyButton :value="run.run_id" label="运行 ID" />
                </div>
                <p class="card__hint" style="margin-top: 4px">
                  {{ run.workflow || '—' }} · {{ fmtTime(run.started_at) }}
                </p>
              </div>
            </div>
            <div class="card__body">
              <dl class="statuslist">
                <div class="statuslist__row">
                  <dt>工作流</dt>
                  <dd><code>{{ run.workflow || '—' }}</code></dd>
                </div>
                <div class="statuslist__row">
                  <dt>任务</dt>
                  <dd>
                    <RouterLink v-if="run.task_id" class="link-cell" :to="`/tasks/${run.task_id}`">
                      {{ run.task_id }}
                    </RouterLink>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>样本</dt>
                  <dd>
                    <template v-if="run.strain_ids.length">
                      <RouterLink
                        v-for="(strain, index) in run.strain_ids"
                        :key="`${strain}-${index}`"
                        class="link-cell"
                        :to="`/samples/${strain}`"
                      >
                        {{ strain }}<span v-if="index < run.strain_ids.length - 1">, </span>
                      </RouterLink>
                    </template>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div class="statuslist__row">
                  <dt>开始时间</dt>
                  <dd class="mono">{{ fmtTime(run.started_at) }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>结束时间</dt>
                  <dd class="mono">{{ run.finished_at ? fmtTime(run.finished_at) : '运行中' }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>耗时</dt>
                  <dd class="mono">{{ fmtDuration(run.started_at, run.finished_at) }}</dd>
                </div>
                <div class="statuslist__row">
                  <dt>基线版本</dt>
                  <dd class="mono">{{ run.baseline_version || '—' }}</dd>
                </div>
              </dl>
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">工具版本</h2>
              <span class="card__hint">{{ toolVersions.length }} 项</span>
            </div>
            <div v-if="toolVersions.length" class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th scope="col">工具</th>
                      <th scope="col">版本</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in toolVersions" :key="item.name">
                      <td><code>{{ item.name }}</code></td>
                      <td class="mono">{{ item.version }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="card__body"><p class="muted">无工具版本记录。</p></div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">参考数据库</h2>
              <span class="card__hint">{{ refDatabases.length }} 项</span>
            </div>
            <div v-if="refDatabases.length" class="card__body">
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th scope="col">名称</th>
                      <th scope="col">版本</th>
                      <th scope="col">校验值</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="db in refDatabases" :key="db.name">
                      <td><code>{{ db.name }}</code></td>
                      <td class="mono">{{ db.version }}</td>
                      <td class="mono muted" :title="db.checksum || undefined">
                        {{ db.checksum ? shortId(db.checksum, 12) : '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="card__body"><p class="muted">无参考数据库记录。</p></div>
          </section>

          <section v-for="section in sections" :key="section.key" class="card">
            <div class="card__head">
              <h2 class="card__title">{{ section.label }}</h2>
            </div>
            <div class="card__body">
              <pre class="code-block">{{ jsonText(section.value) }}</pre>
            </div>
          </section>

          <details class="card card--pad">
            <summary class="card__title" style="cursor: pointer">原始记录（JSON）</summary>
            <pre class="code-block" style="margin-top: 14px">{{ jsonText(run) }}</pre>
          </details>
        </div>

        <div class="stack">
          <section class="card card--pad">
            <h2 class="card__title">与另一运行比较</h2>
            <p class="card__hint" style="margin: 4px 0 14px">
              选择另一条运行记录，比较来源字段差异。
            </p>
            <form class="form" @submit.prevent="compareRuns">
              <div class="field">
                <label class="field__label" for="other-run">另一个运行</label>
                <select
                  id="other-run"
                  v-model="compareWith"
                  class="select"
                  :disabled="comparing || otherRunsLoading || otherRuns.length === 0"
                >
                  <option value="">选择运行记录</option>
                  <option v-for="other in otherRuns" :key="other.run_id" :value="other.run_id">
                    {{ compareOption(other) }}
                  </option>
                </select>
              </div>
              <p v-if="otherRunsLoading" class="card__hint">正在加载其它运行记录…</p>
              <div v-else-if="otherRunsError" class="form-error" role="alert">{{ otherRunsError }}</div>
              <p v-else-if="otherRuns.length === 0" class="card__hint">
                没有可比较的其它运行记录。
              </p>
              <div v-if="compareError" class="form-error" role="alert">{{ compareError }}</div>
              <div class="form__actions">
                <button
                  class="btn btn--primary"
                  type="submit"
                  :disabled="comparing || !compareWith"
                >
                  <span v-if="comparing" class="spinner" />
                  <Icon v-else name="chart" />
                  比较
                </button>
              </div>
            </form>
            <div v-if="compare" style="margin-top: 16px">
              <pre class="code-block">{{ jsonText(compare) }}</pre>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>
