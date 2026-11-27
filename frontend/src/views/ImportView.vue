<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import Icon from '../components/Icon.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { AuthStatus, ImportJob, MappingAdvice } from '../types'

const jobs = ref<ImportJob[]>([])
const loading = ref(true)
const uploading = ref(false)
const error = ref('')
const message = ref('')
const file = ref<File | null>(null)
const specimenSheet = ref('')
const isolateSheet = ref('')
const librarySheet = ref('')
const labSheet = ref('')
const labSubject = ref('auto')
const filter = ref('')
const offset = ref(0)
const limit = ref(25)
const total = ref(0)
const auth = ref<AuthStatus | null>(null)
const preview = ref<{ job: ImportJob; rows: Array<Record<string, unknown>> } | null>(null)
const advice = ref<MappingAdvice | null>(null)
const advising = ref(false)

const isReviewer = computed(
  () =>
    auth.value !== null &&
    (!auth.value.role ||
      auth.value.role === 'admin' ||
      auth.value.role === 'analyst'),
)
const isAdmin = computed(() => auth.value?.role === 'admin')

const statusLabel: Record<string, string> = {
  pending_review: '待审核',
  submitted: '已提交',
  rejected: '已拒绝',
  withdrawn: '已撤回',
  expired: '已过期',
}
const statusClass: Record<string, string> = {
  pending_review: 'badge--awaiting_approval',
  submitted: 'badge--succeeded',
  rejected: 'badge--failed',
  withdrawn: 'badge--cancelled',
  expired: 'badge--cancelled',
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const page = await api.listImports(offset.value, limit.value, filter.value)
    jobs.value = page.items
    total.value = page.total
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载导入提案失败'
  } finally {
    loading.value = false
  }
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  error.value = ''
  message.value = ''
  try {
    const job = await api.uploadImport(file.value, {
      specimen_sheet: specimenSheet.value.trim(),
      isolate_sheet: isolateSheet.value.trim(),
      library_sheet: librarySheet.value.trim(),
      lab_sheet: labSheet.value.trim(),
      lab_subject: labSubject.value,
    })
    message.value = `已上传 ${job.filename}，等待审核（${job.job_id}）`
    file.value = null
    offset.value = 0
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function approve(job: ImportJob) {
  const self = auth.value?.username === job.created_by
  const force = self && isAdmin.value
  if (self && !force) {
    error.value = '提交人不能审核自己的导入；请由其他 analyst/admin 审核。'
    return
  }
  if (!window.confirm(`审核通过 ${job.filename} 并写入湿实验数据？`)) return
  try {
    const updated = await api.approveImport(job.job_id, force)
    message.value = `已通过并提交任务 ${updated.task_id}`
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '审核失败'
  }
}

async function reject(job: ImportJob) {
  const note = window.prompt(`拒绝 ${job.filename} 的原因（可选）`) ?? ''
  try {
    await api.rejectImport(job.job_id, note)
    message.value = '已拒绝该导入'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '拒绝失败'
  }
}

async function withdraw(job: ImportJob) {
  if (!window.confirm(`撤回 ${job.filename}？`)) return
  try {
    await api.withdrawImport(job.job_id)
    message.value = '已撤回该导入'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '撤回失败'
  }
}

function changePage(value: number) {
  offset.value = value
  void load()
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
  void load()
}

async function openPreview(job: ImportJob) {
  advice.value = null
  try {
    const data = await api.previewImport(job.job_id, 20)
    preview.value = { job, rows: data.rows }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '预览失败'
  }
}

async function requestAdvice() {
  if (!preview.value) return
  advising.value = true
  error.value = ''
  try {
    advice.value = await api.adviseImport(preview.value.job.job_id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'AI 映射建议不可用'
  } finally {
    advising.value = false
  }
}

function closePreview() {
  preview.value = null
  advice.value = null
}

function summaryLine(job: ImportJob): string {
  const s = job.summary ?? {}
  if (job.kind === 'edit') {
    const targetType = job.target_type || s.target_type || ''
    const targetId = job.target_id || s.target_id || ''
    return `${s.operation ?? '修改'} · ${targetType} ${targetId}`.trim()
  }
  return [
    `菌株 ${s.isolate_rows ?? 0}`,
    `样本 ${s.specimen_rows ?? 0}`,
    `测序 ${s.library_rows ?? 0}`,
    `化验 ${s.lab_rows ?? 0}`,
  ].join(' · ')
}

function kindLabel(job: ImportJob): string {
  return job.kind === 'edit' ? '修改提案' : '文件导入'
}

onMounted(async () => {
  try {
    auth.value = await api.authStatus()
  } catch {
    // 旧服务端没有 auth/status 时按普通用户展示。
  }
  await load()
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">湿实验导入</h1>
        <p class="pagehead__sub">
          上传 XLSX/CSV/TSV 生成导入提案；用户只能看自己的提案，analyst/admin 审核后才会写入。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="message" class="card__hint" style="margin-bottom: 16px">{{ message }}</div>

    <section class="card card--pad" style="margin-bottom: 16px">
      <div class="card__head">
        <h2 class="card__title">上传文件</h2>
        <span class="card__hint">上传只生成 pending_review 提案，不写业务数据</span>
      </div>
      <form class="form" @submit.prevent="upload">
        <div class="field">
          <label class="field__label" for="import-file">文件</label>
          <input
            id="import-file"
            class="input"
            type="file"
            accept=".xlsx,.xlsm,.csv,.tsv,.txt"
            @change="file = ($event.target as HTMLInputElement).files?.[0] ?? null"
          />
          <p class="field__hint">最大 20 MB；不建议上传含宏的 xlsm。</p>
        </div>
        <div class="meta-grid">
          <div class="field">
            <label class="field__label" for="sheet-specimen">样本 sheet（可选）</label>
            <input id="sheet-specimen" v-model="specimenSheet" class="input" placeholder="自动识别" />
          </div>
          <div class="field">
            <label class="field__label" for="sheet-isolate">菌株 sheet（可选）</label>
            <input id="sheet-isolate" v-model="isolateSheet" class="input" placeholder="自动识别" />
          </div>
          <div class="field">
            <label class="field__label" for="sheet-library">测序数据 sheet（可选）</label>
            <input id="sheet-library" v-model="librarySheet" class="input" placeholder="自动识别" />
          </div>
          <div class="field">
            <label class="field__label" for="sheet-lab">化验 sheet（可选）</label>
            <input id="sheet-lab" v-model="labSheet" class="input" placeholder="自动识别" />
          </div>
          <div class="field">
            <label class="field__label" for="lab-subject">化验结果归属</label>
            <select id="lab-subject" v-model="labSubject" class="input">
              <option value="auto">自动</option>
              <option value="isolate">菌株</option>
              <option value="specimen">样本</option>
            </select>
          </div>
        </div>
        <div class="form__actions">
          <button class="btn btn--primary" type="submit" :disabled="uploading || !file">
            <span v-if="uploading" class="spinner" />
            <Icon v-else name="plus" />
            上传并生成提案
          </button>
        </div>
      </form>
    </section>

    <section class="card">
      <div class="filters">
        <span class="card__hint">状态</span>
        <select v-model="filter" class="input" style="max-width: 160px" @change="offset = 0; load()">
          <option value="">全部</option>
          <option value="pending_review">待审核</option>
          <option value="submitted">已提交</option>
          <option value="rejected">已拒绝</option>
          <option value="withdrawn">已撤回</option>
          <option value="expired">已过期</option>
        </select>
        <span class="filter-spacer" />
        <span class="card__hint">{{ total }} 个提案</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="jobs.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">类型 / 文件</th>
              <th scope="col">状态</th>
              <th scope="col">内容</th>
              <th scope="col">提交人</th>
              <th scope="col">审核人</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in jobs" :key="job.job_id">
              <td data-label="类型 / 文件">
                <span class="badge">{{ kindLabel(job) }}</span>
                <div class="mono" style="margin-top: 4px">{{ job.filename }}</div>
                <div class="muted" style="font-size: 11px">{{ job.job_id }}</div>
                <div v-if="job.errors?.length" class="form-error" style="margin-top: 6px">
                  {{ job.errors.slice(0, 2).join('；') }}
                </div>
              </td>
              <td data-label="状态">
                <span class="badge" :class="statusClass[job.status] ?? ''">{{ statusLabel[job.status] }}</span>
                <div v-if="job.task_id" style="margin-top: 6px">
                  <RouterLink class="link-cell" :to="`/tasks/${job.task_id}`">
                    {{ job.task_id.slice(0, 10) }}
                  </RouterLink>
                </div>
              </td>
              <td data-label="内容">{{ summaryLine(job) }}</td>
              <td data-label="提交人">{{ job.created_by }}</td>
              <td data-label="审核人">{{ job.reviewed_by || '—' }}</td>
              <td data-label="操作">
                <div class="inline-actions" style="flex-wrap: wrap; gap: 8px">
                  <button class="btn btn--ghost btn--sm" type="button" @click="openPreview(job)">
                    预览
                  </button>
                  <template v-if="job.status === 'pending_review' && isReviewer">
                    <button class="btn btn--primary btn--sm" type="button" @click="approve(job)">
                      通过并写入
                    </button>
                    <button class="btn btn--danger btn--sm" type="button" @click="reject(job)">
                      拒绝
                    </button>
                  </template>
                  <button
                    v-if="job.status === 'pending_review' && job.created_by === auth?.username"
                    class="btn btn--ghost btn--sm"
                    type="button"
                    @click="withdraw(job)"
                  >
                    撤回
                  </button>
                  <span v-if="job.review_note" class="muted">{{ job.review_note }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="暂无导入提案"
        hint="上传 XLSX/CSV/TSV 后，这里会显示待审核内容。"
        icon="file-text"
      />
      <Pager
        :offset="offset"
        :limit="limit"
        :total="total"
        :disabled="loading"
        @update:offset="changePage"
        @update:limit="changeLimit"
      />
    </section>

    <section v-if="preview" class="card card--pad" style="margin-top: 16px">
      <div class="card__head">
        <h2 class="card__title">预览：{{ preview.job.filename }}</h2>
        <div class="inline-actions">
          <button
            v-if="preview.job.status === 'pending_review' && preview.job.kind !== 'edit'"
            class="btn btn--ghost btn--sm"
            type="button"
            :disabled="advising"
            @click="requestAdvice"
          >
            <span v-if="advising" class="spinner" />
            <Icon v-else name="plus" />
            AI 映射建议
          </button>
          <button class="btn btn--ghost btn--sm" type="button" @click="closePreview">关闭</button>
        </div>
      </div>
      <p class="card__hint">仅显示前 20 行；D4 数据只在本地控制台可见。</p>
      <div v-if="advice" class="card__hint" style="margin: 8px 0">
        端点 {{ advice.endpoint }}（{{ advice.location }}）· 载荷 {{ advice.data_class }} ·
        {{ advice.included_values ? '含截断样例值' : '仅列名与聚合统计' }}
      </div>
      <div v-if="advice?.warnings?.length" class="form-error" style="margin: 8px 0">
        <div v-for="warning in advice.warnings" :key="warning">{{ warning }}</div>
      </div>
      <table v-if="advice?.columns?.length" class="table" style="margin: 8px 0">
        <thead>
          <tr>
            <th scope="col">层级</th>
            <th scope="col">原列</th>
            <th scope="col">建议</th>
            <th scope="col">置信度</th>
            <th scope="col">理由</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="column in advice.columns" :key="`${column.layer}:${column.source_column}`">
            <td data-label="层级">{{ column.layer }}</td>
            <td data-label="原列" class="mono">{{ column.source_column }}</td>
            <td data-label="建议">
              {{ column.action === 'map' ? column.suggested_field : column.action }}
            </td>
            <td data-label="置信度">{{ column.confidence }}</td>
            <td data-label="理由">{{ column.reason }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="advice?.notes" class="card__hint">{{ advice.notes }}</p>
      <p v-if="advice" class="card__hint">AI 只给建议；写入仍由审核通过后的 record 任务执行。</p>
      <pre class="code-block" style="max-height: 420px; overflow: auto">{{ JSON.stringify(preview.rows, null, 2) }}</pre>
    </section>
  </div>
</template>
