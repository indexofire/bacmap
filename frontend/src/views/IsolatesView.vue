<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import { requireSucceeded, waitForTask } from '../lib/tasks'
import type { AuthStatus, IsolateRow } from '../types'

const rows = ref<IsolateRow[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const offset = ref(0)
const limit = ref(50)
const total = ref(0)
const auth = ref<AuthStatus | null>(null)
const newIsolate = ref({
  isolate_id: '',
  specimen_id: '',
  lineage_id: '',
  passage: '',
})
const creating = ref(false)
const createMessage = ref('')
let timer: ReturnType<typeof setTimeout> | undefined

async function load() {
  loading.value = true
  error.value = ''
  try {
    const page = await api.isolatesPage(offset.value, limit.value, query.value.trim())
    rows.value = page.items
    total.value = page.total
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载菌株失败'
  } finally {
    loading.value = false
  }
}

watch(query, () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    offset.value = 0
    void load()
  }, 250)
})

function changePage(value: number) {
  offset.value = value
  void load()
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
  void load()
}

const canWrite = computed(() => {
  const value = auth.value
  if (!value || !value.enabled) return true
  if (value.mode === 'accounts' || value.mode === 'personal') {
    return value.role === 'admin' || value.role === 'analyst'
  }
  return true
})
const canPropose = computed(
  () => auth.value?.mode === 'accounts' && auth.value.role === 'user',
)
const canEdit = computed(() => canWrite.value || canPropose.value)

async function createIsolate() {
  const isolateId = newIsolate.value.isolate_id.trim()
  if (!isolateId) return
  creating.value = true
  createMessage.value = ''
  error.value = ''
  try {
    const passage = newIsolate.value.passage.trim()
    const payload = {
      isolate_id: isolateId,
      specimen_id: newIsolate.value.specimen_id.trim(),
      lineage_id: newIsolate.value.lineage_id.trim() || null,
      passage: passage ? Number(passage) : null,
    }
    if (canWrite.value) {
      const result = await api.createIsolate(payload)
      requireSucceeded(await waitForTask(result.task_id))
      createMessage.value = `菌株 ${isolateId} 已创建`
    } else if (canPropose.value) {
      await api.proposeWetlab({ kind: 'isolate_create', ...payload })
      createMessage.value = `已提交新建菌株提案：${isolateId}，等待审核`
    } else {
      throw new Error('当前角色无提交权限')
    }
    newIsolate.value = { isolate_id: '', specimen_id: '', lineage_id: '', passage: '' }
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建菌株失败'
  } finally {
    creating.value = false
  }
}

function displaySpecies(value?: string): string {
  return String(value ?? '').replaceAll('_', ' ') || '—'
}

function joinOrDash(values?: string[]): string {
  return values?.length ? values.join(' / ') : '—'
}

function formatDate(value?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toLocaleDateString('zh-CN')
}

onMounted(async () => {
  try {
    auth.value = await api.authStatus()
  } catch {
    // 旧服务端没有 auth/status 时按可信部署处理。
  }
  await load()
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">菌株</h1>
        <p class="pagehead__sub">菌株（isolate）实体、所属样本与结果摘要；点击编号查看详情。</p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="loading" @click="load">
          <Icon name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section v-if="canEdit" class="card card--pad" style="margin-bottom: 16px">
      <div class="card__head">
        <h2 class="card__title">新建菌株</h2>
        <span class="card__hint">可先创建空菌株，再关联测序数据或补充湿实验信息</span>
      </div>
      <form class="form" @submit.prevent="createIsolate">
        <div class="meta-grid">
          <div class="field">
            <label class="field__label" for="new-isolate-id">菌株 ID</label>
            <input
              id="new-isolate-id"
              v-model="newIsolate.isolate_id"
              class="input input--mono"
              placeholder="ISO-002"
              required
            />
          </div>
          <div class="field">
            <label class="field__label" for="new-isolate-specimen">所属样本（可选）</label>
            <input
              id="new-isolate-specimen"
              v-model="newIsolate.specimen_id"
              class="input input--mono"
              placeholder="A03-SN-001"
            />
          </div>
          <div class="field">
            <label class="field__label" for="new-isolate-lineage">谱系（可选）</label>
            <input id="new-isolate-lineage" v-model="newIsolate.lineage_id" class="input" />
          </div>
          <div class="field">
            <label class="field__label" for="new-isolate-passage">传代（可选）</label>
            <input
              id="new-isolate-passage"
              v-model="newIsolate.passage"
              class="input"
              inputmode="numeric"
            />
          </div>
        </div>
        <div class="form__actions">
          <button class="btn btn--primary" type="submit" :disabled="creating || !newIsolate.isolate_id.trim()">
            <span v-if="creating" class="spinner" />
            <Icon v-else name="plus" />
            {{ canWrite ? '创建菌株' : '提交新建提案' }}
          </button>
          <span v-if="createMessage" class="card__hint">{{ createMessage }}</span>
        </div>
      </form>
    </section>

    <section class="card">
      <div class="filters">
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索菌株 / 样本 / 谱系…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ total }} 株</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="rows.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">菌株</th>
              <th scope="col">样本</th>
              <th scope="col">物种</th>
              <th scope="col">ST</th>
              <th scope="col">血清型</th>
              <th scope="col">测序数据</th>
              <th scope="col">结果数</th>
              <th scope="col">最近分析</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.isolate_id">
              <td data-label="菌株">
                <RouterLink class="link-cell" :to="`/isolates/${row.isolate_id}`">
                  <code>{{ row.isolate_id }}</code>
                </RouterLink>
              </td>
              <td data-label="样本">
                <RouterLink
                  v-if="row.specimen_id"
                  class="link-cell"
                  :to="`/specimens/${row.specimen_id}`"
                >
                  {{ row.specimen_id }}
                </RouterLink>
                <span v-else class="muted">未关联</span>
              </td>
              <td data-label="物种"><i>{{ displaySpecies(row.species) }}</i></td>
              <td data-label="ST"><span class="mono">{{ joinOrDash(row.sts) }}</span></td>
              <td data-label="血清型">{{ joinOrDash(row.serotypes) }}</td>
              <td data-label="测序数据"><span class="mono">{{ row.n_libraries ?? 0 }}</span></td>
              <td data-label="结果数"><span class="mono">{{ row.n_results ?? 0 }}</span></td>
              <td data-label="最近分析">{{ formatDate(row.last_analysis) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="!query"
        title="暂无菌株"
        hint="登记分析数据或导入样本关联后，菌株会出现在这里。"
      />
      <EmptyState v-else title="没有匹配的菌株" hint="换个关键词试试。" />
      <Pager
        :offset="offset"
        :limit="limit"
        :total="total"
        :disabled="loading"
        @update:offset="changePage"
        @update:limit="changeLimit"
      />
    </section>
  </div>
</template>
