<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'
import CopyButton from '../components/CopyButton.vue'
import { api } from '../api'
import type { GomObject, GvixbLink } from '../types'
import { fmtTime, jsonText, shortId } from '../lib/format'

const route = useRoute()
const id = String(route.params.id)
const version = route.query.version ? Number(route.query.version) : undefined
const object = ref<GomObject | null>(null)
const loading = ref(true)
const error = ref('')

const payload = computed<Record<string, unknown>>(() => {
  const value = object.value?.payload
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
})
const payloadKeys = computed(() => {
  const keys = object.value?.payload_keys
  if (Array.isArray(keys) && keys.length) {
    const valid = keys.filter((key): key is string => typeof key === 'string')
    if (valid.length) return valid
  }
  return Object.keys(payload.value)
})
const strainId = computed(() => stringField(object.value?.strain_id))
const pipelineVersion = computed(() => stringField(object.value?.pipeline_version))
const runId = computed(() => stringField(payload.value.run_id))
const taskId = computed(() => stringField(payload.value.task_id))
const gvixbViews = computed<GvixbLink[]>(() => {
  const items = object.value?.gvixb_views
  return Array.isArray(items)
    ? items.filter(
        (item): item is GvixbLink =>
          !!item && typeof item === 'object' && typeof item.url === 'string' && typeof item.label === 'string',
      )
    : []
})

function stringField(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    object.value = await api.getGom(id, version)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载 GOM 对象失败'
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
          <RouterLink to="/gom" class="btn btn--ghost btn--sm">
            <Icon name="arrow-left" />
            返回 GOM
          </RouterLink>
        </div>
        <h1 class="pagehead__title inline-actions">
          <span v-if="object">{{ object.object_type }} · {{ object.strain_id || shortId(object.object_id, 18) }}</span>
          <span v-else>GOM 对象</span>
          <CopyButton v-if="object" :value="object.object_id" label="对象 ID" />
        </h1>
        <p class="pagehead__sub">不可变对象的最新版本或指定版本。</p>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="loading" class="card card--pad"><div class="skeleton" style="height: 220px" /></div>

    <template v-else-if="object">
      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <h2 class="card__title">对象信息</h2>
              <span class="card__hint">不可变 · v{{ object.version }}</span>
            </div>
            <div class="card__body">
              <dl class="statuslist gom-fields">
                <div class="statuslist__row"><dt>对象 ID</dt><dd class="mono">{{ object.object_id }}</dd></div>
                <div class="statuslist__row"><dt>类型</dt><dd><code>{{ object.object_type }}</code></dd></div>
                <div class="statuslist__row"><dt>版本</dt><dd class="mono">v{{ object.version }}</dd></div>
                <div class="statuslist__row">
                  <dt>菌株</dt>
                  <dd>
                    <RouterLink
                      v-if="strainId"
                      class="link-cell"
                      :to="`/samples/${encodeURIComponent(strainId)}`"
                    >
                      {{ strainId }}
                    </RouterLink>
                    <span v-else class="muted">—</span>
                  </dd>
                </div>
                <div v-if="runId" class="statuslist__row">
                  <dt>运行</dt>
                  <dd>
                    <RouterLink class="link-cell" :to="`/runs/${encodeURIComponent(runId)}`">{{ runId }}</RouterLink>
                  </dd>
                </div>
                <div v-if="taskId" class="statuslist__row">
                  <dt>关联任务</dt>
                  <dd>
                    <RouterLink class="link-cell" :to="`/tasks/${encodeURIComponent(taskId)}`">{{ taskId }}</RouterLink>
                  </dd>
                </div>
                <div class="statuslist__row"><dt>分析版本</dt><dd class="mono">{{ pipelineVersion || '—' }}</dd></div>
                <div class="statuslist__row"><dt>创建时间</dt><dd class="mono">{{ fmtTime(object.created_at) }}</dd></div>
                <div class="statuslist__row">
                  <dt>载荷键</dt>
                  <dd>
                    <div v-if="payloadKeys.length" class="inline-actions">
                      <code v-for="key in payloadKeys" :key="key">{{ key }}</code>
                    </div>
                    <span v-else class="muted">无载荷键</span>
                  </dd>
                </div>
              </dl>
            </div>
          </section>
        </div>

        <div class="stack">
          <section v-if="gvixbViews.length" class="card">
            <div class="card__head">
              <h2 class="card__title">gvixb · 3D 可视化</h2>
              <span class="card__hint">指向对象载荷所在运行的实际产物</span>
            </div>
            <div class="card__body">
              <div class="inline-actions">
                <a
                  v-for="view in gvixbViews"
                  :key="view.id"
                  class="btn btn--ghost btn--sm"
                  :href="view.url"
                >
                  {{ view.label }}
                </a>
              </div>
            </div>
          </section>

          <details class="card gom-details">
            <summary class="gom-details__summary">
              <span class="gom-details__label">
                <Icon name="chevron-right" class="gom-details__chevron" :size="14" />
                <span class="card__title">载荷 JSON</span>
              </span>
              <span class="card__hint">{{ payloadKeys.length }} 个键 · 默认折叠</span>
            </summary>
            <div class="card__body"><pre class="code-block">{{ jsonText(object.payload) }}</pre></div>
          </details>
          <details class="card gom-details">
            <summary class="gom-details__summary">
              <span class="gom-details__label">
                <Icon name="chevron-right" class="gom-details__chevron" :size="14" />
                <span class="card__title">原始对象 JSON</span>
              </span>
              <span class="card__hint">默认折叠</span>
            </summary>
            <div class="card__body"><pre class="code-block">{{ jsonText(object) }}</pre></div>
          </details>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.gom-fields :deep(.statuslist__row) {
  grid-template-columns: 108px minmax(0, 1fr);
}

.gom-details__summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: 16px var(--sp-5);
  color: var(--text-2);
  font-size: 13px;
  cursor: pointer;
}

.gom-details__label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.gom-details__chevron {
  color: var(--text-3);
  transition: transform var(--t-micro) var(--ease-out);
}

.gom-details[open] .gom-details__summary {
  border-bottom: 1px solid var(--border-subtle);
}

.gom-details[open] .gom-details__chevron {
  transform: rotate(90deg);
}

@media (max-width: 720px) {
  .gom-fields :deep(.statuslist__row) {
    grid-template-columns: 92px minmax(0, 1fr);
  }
}
</style>
