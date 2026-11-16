<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import CopyButton from '../components/CopyButton.vue'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { ApiError, api } from '../api'
import type { DagArtifactRow, DagNodeRow, DagView } from '../types'
import { fmtBytes, fmtTime, jsonText, shortId } from '../lib/format'
import { useToast } from '../composables/useToast'

const route = useRoute()
const toast = useToast()
const id = String(route.params.id)

const view = ref<DagView | null>(null)
const loading = ref(true)
const error = ref('')
const busy = ref('')
const approver = ref('')
const signature = ref('')
const preview = ref<{ row: DagArtifactRow; type: string; value: unknown } | null>(null)

let timer: number | undefined

const run = computed(() => view.value?.run ?? null)
const nodes = computed(() => view.value?.nodes ?? [])
const artifacts = computed(() => view.value?.artifacts ?? [])
const cacheHits = computed(() => nodes.value.filter((row) => row.cache_hit === 1).length)
const canResume = computed(() => run.value?.state === 'paused')
const canApprove = computed(() => run.value?.state === 'awaiting_approval')
const canCancel = computed(
  () => !!run.value && ['pending', 'running', 'paused', 'awaiting_approval'].includes(run.value.state),
)

function nodeState(row: DagNodeRow): string {
  return row.state || 'pending'
}

function parseOutputs(row: DagNodeRow): Record<string, string> {
  try {
    const parsed = JSON.parse(row.outputs_json || '{}')
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

function artifactById(artifactId: string): DagArtifactRow | undefined {
  return artifacts.value.find((row) => row.artifact_id === artifactId)
}

function nodeArtifacts(row: DagNodeRow): DagArtifactRow[] {
  const outputs = parseOutputs(row)
  return Object.values(outputs)
    .map((artifactId) => artifactById(artifactId))
    .filter((item): item is DagArtifactRow => !!item)
}

function duration(row: DagNodeRow): string {
  if (!row.started_at || !row.finished_at) return ''
  const start = Date.parse(row.started_at)
  const end = Date.parse(row.finished_at)
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return ''
  const seconds = Math.round((end - start) / 1000)
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function transportError(exc: unknown): string {
  if (exc instanceof ApiError) return exc.message
  return exc instanceof Error ? exc.message : String(exc)
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    view.value = await api.researchDag(id)
    error.value = ''
  } catch (exc) {
    error.value = transportError(exc)
  } finally {
    loading.value = false
    schedule()
  }
}

function schedule() {
  if (timer) window.clearTimeout(timer)
  timer = undefined
  const state = run.value?.state ?? ''
  if (state === 'running' || state === 'pending') {
    timer = window.setTimeout(() => load(true), 3000)
  }
}

async function act(action: 'resume' | 'cancel' | 'approve' | 'reject') {
  busy.value = action
  try {
    if (action === 'resume') {
      await api.resumeTask(id)
      toast.info('已请求恢复')
    } else if (action === 'cancel') {
      await api.cancelTask(id)
      toast.info('已请求取消')
    } else {
      await api.approveTask(id, {
        approver: approver.value.trim() || 'web',
        decision: action,
        signature: signature.value.trim(),
      })
      toast.ok(action === 'approve' ? '已批准代码' : '已拒绝')
    }
    await load()
    if (action === 'resume' || action === 'approve') {
      // 工作流重启有一小段延迟：补一次静默刷新，避免页面停在旧状态
      window.setTimeout(() => load(true), 1500)
    }
  } catch (exc) {
    toast.err(transportError(exc))
  } finally {
    busy.value = ''
  }
}

async function openArtifact(row: DagArtifactRow) {
  try {
    const payload = await api.researchDagArtifact(id, row.artifact_id)
    preview.value = {
      row,
      type: String(payload.type ?? row.type),
      value: payload.value,
    }
  } catch (exc) {
    toast.err(transportError(exc))
  }
}

function closePreview() {
  preview.value = null
}

const previewMarkdown = computed(() => {
  const value = preview.value?.value
  if (value && typeof value === 'object' && 'markdown' in value) {
    return String((value as Record<string, unknown>).markdown ?? '')
  }
  return ''
})

const previewSvg = computed(() => {
  const value = preview.value?.value
  if (value && typeof value === 'object' && 'data' in value) {
    const svg = String((value as Record<string, unknown>).data ?? '')
    if (svg.trimStart().startsWith('<svg')) {
      return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
    }
  }
  return ''
})

const previewJson = computed(() => {
  if (!preview.value) return ''
  return jsonText(preview.value.value)
})

onMounted(() => load())
onBeforeUnmount(() => {
  if (timer) window.clearTimeout(timer)
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <div class="inline-actions" style="margin-bottom: 8px">
          <RouterLink :to="`/tasks/${id}`" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回任务
          </RouterLink>
          <RouterLink :to="`/plans`" class="btn btn--ghost btn--sm">
            <Icon name="plans" />
            计划
          </RouterLink>
        </div>
        <h1 class="pagehead__title">
          <span class="inline-actions" style="gap: 10px">
            <span class="mono" :title="id">{{ shortId(id, 20) }}</span>
            <CopyButton :value="id" label="任务 ID" />
            <StatusBadge v-if="run" :state="run.state" />
          </span>
        </h1>
        <p class="pagehead__sub">
          研究 DAG 时间线：节点状态、缓存命中、产物与检查点。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load()">
          <Icon name="refresh" />
          刷新
        </button>
        <button
          v-if="canResume"
          class="btn"
          type="button"
          :disabled="!!busy"
          @click="act('resume')"
        >
          <Icon name="play" />
          恢复
        </button>
        <button
          v-if="canCancel"
          class="btn btn--ghost"
          type="button"
          :disabled="!!busy"
          @click="act('cancel')"
        >
          取消
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <div v-if="loading" class="card card--pad">
      <div class="skeleton" style="height: 180px" />
    </div>

    <template v-else-if="run">
      <div v-if="canApprove" class="card card--pad" style="margin-bottom: 16px">
        <div class="card__title" style="margin-bottom: 8px">代码审核</div>
        <p class="muted" style="margin-top: 0">
          本计划包含自写脚本或镜像构建节点。批准后工作流会从暂停处继续。
        </p>
        <div class="inline-actions" style="flex-wrap: wrap">
          <input v-model="approver" class="input" placeholder="审核人" style="max-width: 180px" />
          <input
            v-model="signature"
            class="input"
            placeholder="签名（可选）"
            style="max-width: 240px"
          />
          <button class="btn" type="button" :disabled="!!busy" @click="act('approve')">
            批准
          </button>
          <button
            class="btn btn--ghost"
            type="button"
            :disabled="!!busy"
            @click="act('reject')"
          >
            拒绝
          </button>
        </div>
      </div>

      <div class="card card--pad" style="margin-bottom: 16px">
        <div class="dag-summary">
          <div>
            <div class="muted">DAG 哈希</div>
            <div class="mono">{{ run.dag_hash }}</div>
          </div>
          <div>
            <div class="muted">数据级别</div>
            <div>D{{ run.data_class }}</div>
          </div>
          <div>
            <div class="muted">节点</div>
            <div>{{ nodes.length }}（缓存命中 {{ cacheHits }}）</div>
          </div>
          <div>
            <div class="muted">创建</div>
            <div>{{ fmtTime(run.created_at) }}</div>
          </div>
          <div>
            <div class="muted">更新</div>
            <div>{{ fmtTime(run.updated_at) }}</div>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom: 16px">
        <div class="card__head">
          <div class="card__title">节点时间线</div>
          <div class="card__hint">按执行顺序</div>
        </div>
        <div class="card__body">
          <ol v-if="nodes.length" class="timeline">
            <li v-for="node in nodes" :key="node.node_id" class="timeline__item">
              <span class="timeline__dot" :class="`timeline__dot--${nodeState(node)}`" />
              <div class="timeline__body">
                <div class="inline-actions" style="gap: 8px; flex-wrap: wrap">
                  <span class="mono timeline__id">{{ node.node_id }}</span>
                  <span class="muted mono">{{ node.op }}</span>
                  <StatusBadge :state="nodeState(node)" />
                  <span v-if="node.cache_hit === 1" class="badge badge--succeeded">缓存命中</span>
                  <span v-if="duration(node)" class="muted">{{ duration(node) }}</span>
                </div>
                <div v-if="node.error" class="timeline__error">{{ node.error }}</div>
                <div v-if="nodeArtifacts(node).length" class="inline-actions" style="margin-top: 6px">
                  <button
                    v-for="artifact in nodeArtifacts(node)"
                    :key="artifact.artifact_id"
                    class="chip"
                    type="button"
                    @click="openArtifact(artifact)"
                  >
                    {{ artifact.type }} · {{ shortId(artifact.sha256, 8) }}
                  </button>
                </div>
              </div>
            </li>
          </ol>
          <p v-else class="muted">尚未开始执行。</p>
        </div>
      </div>

      <div class="card">
        <div class="card__head">
          <div class="card__title">产物</div>
          <div class="card__hint">内容寻址 · 点击查看</div>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>类型</th>
                <th>产物 ID</th>
                <th>产出节点</th>
                <th class="num">大小</th>
                <th>时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr v-for="artifact in artifacts" :key="artifact.artifact_id">
                <td>{{ artifact.type }}</td>
                <td class="mono" :title="artifact.artifact_id">
                  {{ shortId(artifact.sha256, 12) }}
                </td>
                <td class="mono">{{ artifact.producer_node || '—' }}</td>
                <td class="num">{{ fmtBytes(artifact.size_bytes) }}</td>
                <td>{{ fmtTime(artifact.created_at) }}</td>
                <td>
                  <button class="btn btn--ghost btn--sm" type="button" @click="openArtifact(artifact)">
                    查看
                  </button>
                </td>
              </tr>
              <tr v-if="!artifacts.length">
                <td colspan="6" class="muted">暂无产物</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-if="preview" class="dag-preview">
      <div class="card">
        <div class="card__head">
          <div class="card__title">
            {{ preview.type }} · <span class="mono">{{ shortId(preview.row.sha256, 12) }}</span>
          </div>
          <button class="btn btn--ghost btn--sm" type="button" @click="closePreview">关闭</button>
        </div>
        <div class="card__body">
          <pre v-if="preview.type === 'Text'" class="dag-preview__text">{{ previewMarkdown }}</pre>
          <img
            v-else-if="preview.type === 'Figure' && previewSvg"
            :src="previewSvg"
            alt="figure"
            class="dag-preview__figure"
          />
          <pre v-else class="dag-preview__text">{{ previewJson }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dag-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}

.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}

.timeline__item {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 10px 0 10px 4px;
}

.timeline__item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 26px;
  bottom: -2px;
  width: 1px;
  background: var(--border);
}

.timeline__dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-top: 7px;
  flex: none;
  background: var(--muted);
}

.timeline__dot--succeeded {
  background: var(--st-ok-dot);
}

.timeline__dot--failed {
  background: var(--st-fail-dot);
}

.timeline__dot--running {
  background: var(--st-running-dot);
  box-shadow: 0 0 0 3px var(--st-running-bg);
}

.muted {
  color: var(--text-3);
}

.timeline__body {
  min-width: 0;
  flex: 1;
}

.timeline__id {
  font-weight: 600;
}

.timeline__error {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--st-fail-bg);
  color: var(--st-fail-text);
  font-family: var(--font-mono);
  font-size: 12px;
  white-space: pre-wrap;
}

.chip {
  border: 1px solid var(--border);
  background: var(--surface-2, transparent);
  color: var(--text);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
}

.chip:hover {
  border-color: var(--accent);
}

.dag-preview {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: color-mix(in srgb, #000 55%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.dag-preview .card {
  width: min(920px, 100%);
  max-height: 82vh;
  overflow: auto;
}

.dag-preview__text {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  max-height: 60vh;
  overflow: auto;
}

.dag-preview__figure {
  max-width: 100%;
  background: #fff;
  border-radius: 8px;
}
</style>
