<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import { requireSucceeded, waitForTask } from '../lib/tasks'
import type { AuthStatus, IsolateRow, SpecimenRow } from '../types'

const router = useRouter()
const rows = ref<SpecimenRow[]>([])
const isolates = ref<IsolateRow[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const offset = ref(0)
const limit = ref(50)
const total = ref(0)
const assignSpecimenId = ref('')
const selectedIsolates = ref<string[]>([])
const assignDatasets = ref('')
const assignMessage = ref('')
const assigning = ref(false)
const auth = ref<AuthStatus | null>(null)
const newSpecimen = ref({ specimen_id: '', origin: 'manual', note: '' })
const creating = ref(false)
const createMessage = ref('')
let timer: ReturnType<typeof setTimeout> | undefined

const unassigned = computed(() => isolates.value.filter((row) => !row.specimen_id))
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

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [specimens, isolatesRows] = await Promise.all([
      api.specimensPage(offset.value, limit.value, query.value.trim()),
      api.listIsolates(2000),
    ])
    rows.value = specimens.items
    total.value = specimens.total
    isolates.value = isolatesRows
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载样本失败'
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

async function createSpecimen() {
  const specimenId = newSpecimen.value.specimen_id.trim()
  if (!specimenId) return
  creating.value = true
  createMessage.value = ''
  error.value = ''
  try {
    if (canWrite.value) {
      const result = await api.createSpecimen({
        specimen_id: specimenId,
        origin: newSpecimen.value.origin || 'manual',
        note: newSpecimen.value.note,
      })
      requireSucceeded(await waitForTask(result.task_id))
      createMessage.value = `样本 ${specimenId} 已创建`
    } else if (canPropose.value) {
      await api.proposeWetlab({
        kind: 'specimen_create',
        specimen_id: specimenId,
        origin: newSpecimen.value.origin || 'manual',
        note: newSpecimen.value.note,
      })
      createMessage.value = `已提交新建样本提案：${specimenId}，等待审核`
    } else {
      throw new Error('当前角色无提交权限')
    }
    newSpecimen.value = { specimen_id: '', origin: 'manual', note: '' }
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '创建样本失败'
  } finally {
    creating.value = false
  }
}

async function assign() {
  const specimenId = assignSpecimenId.value.trim()
  const datasets = assignDatasets.value
    .split(/[,\s]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  if (!specimenId || (!selectedIsolates.value.length && !datasets.length)) return
  assigning.value = true
  assignMessage.value = ''
  error.value = ''
  try {
    if (canWrite.value) {
      const result = await api.assignSpecimen({
        specimen_id: specimenId,
        isolates: selectedIsolates.value,
        datasets,
      })
      assignMessage.value =
        `已关联 ${result.updated} 行` +
        (result.missing.length ? `；未找到：${result.missing.join(', ')}` : '')
    } else if (canPropose.value) {
      await api.proposeWetlab({
        kind: 'specimen_assign',
        specimen_id: specimenId,
        isolates: selectedIsolates.value,
        datasets,
      })
      assignMessage.value = '已提交关联提案，等待审核'
    } else {
      throw new Error('当前角色无提交权限')
    }
    selectedIsolates.value = []
    assignDatasets.value = ''
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '关联失败'
  } finally {
    assigning.value = false
  }
}

function displaySpecies(value?: string): string {
  return String(value ?? '').replaceAll('_', ' ') || '—'
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
        <h1 class="pagehead__title">样本</h1>
        <p class="pagehead__sub">
          送检样本（specimen）；一份样本可分离出多个菌株，分析结果按菌株/测序数据归属。
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

    <section v-if="canEdit" class="card card--pad" style="margin-bottom: 16px">
      <div class="card__head">
        <h2 class="card__title">新建样本</h2>
        <span class="card__hint">样本编号由实验室提供；创建后可在详情页补充湿实验信息</span>
      </div>
      <form class="form" @submit.prevent="createSpecimen">
        <div class="meta-grid">
          <div class="field">
            <label class="field__label" for="new-specimen-id">样本编号</label>
            <input
              id="new-specimen-id"
              v-model="newSpecimen.specimen_id"
              class="input input--mono"
              placeholder="A03-SN-002"
              required
            />
          </div>
          <div class="field">
            <label class="field__label" for="new-specimen-origin">来源</label>
            <input id="new-specimen-origin" v-model="newSpecimen.origin" class="input" placeholder="manual" />
          </div>
        </div>
        <div class="field">
          <label class="field__label" for="new-specimen-note">备注（可选）</label>
          <input id="new-specimen-note" v-model="newSpecimen.note" class="input" />
        </div>
        <div class="form__actions">
          <button class="btn btn--primary" type="submit" :disabled="creating || !newSpecimen.specimen_id.trim()">
            <span v-if="creating" class="spinner" />
            <Icon v-else name="plus" />
            {{ canWrite ? '创建样本' : '提交新建提案' }}
          </button>
          <span v-if="createMessage" class="card__hint">{{ createMessage }}</span>
        </div>
      </form>
    </section>

    <section v-if="canEdit" class="card card--pad" style="margin-bottom: 16px">
      <div class="card__head">
        <h2 class="card__title">关联数据到样本</h2>
        <span class="card__hint">样本编号由实验室提供；菌株/测序数据可后补关联</span>
      </div>
      <form class="form" @submit.prevent="assign">
        <div class="meta-grid">
          <div class="field">
            <label class="field__label" for="specimen-id">样本编号</label>
            <input
              id="specimen-id"
              v-model="assignSpecimenId"
              class="input input--mono"
              placeholder="A03-SN-001"
            />
          </div>
          <div class="field">
            <label class="field__label" for="specimen-datasets">测序数据（可选）</label>
            <input
              id="specimen-datasets"
              v-model="assignDatasets"
              class="input input--mono"
              placeholder="逗号分隔，如 26SAL0501, 26SAL0501__ont"
            />
          </div>
        </div>
        <div v-if="unassigned.length" class="field">
          <label class="field__label">未关联菌株（可多选）</label>
          <div class="inline-actions" style="flex-wrap: wrap; gap: 8px">
            <label
              v-for="row in unassigned"
              :key="row.isolate_id"
              class="chip"
              :class="{ 'is-active': selectedIsolates.includes(row.isolate_id) }"
            >
              <input
                v-model="selectedIsolates"
                type="checkbox"
                :value="row.isolate_id"
                style="margin-right: 6px"
              />
              {{ row.isolate_id }}
            </label>
          </div>
        </div>
        <p v-else class="card__hint">没有待关联的菌株；可在“测序数据”栏手动指定。</p>
        <div class="form__actions">
          <button
            class="btn btn--primary"
            type="submit"
            :disabled="assigning || !assignSpecimenId.trim()"
          >
            <span v-if="assigning" class="spinner" />
            <Icon v-else name="check" />
            {{ canWrite ? '关联' : '提交关联提案' }}
          </button>
          <span v-if="assignMessage" class="card__hint">{{ assignMessage }}</span>
        </div>
      </form>
    </section>

    <section class="card">
      <div class="filters">
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索样本编号 / 来源 / 备注…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ total }} 份</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="rows.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">样本</th>
              <th scope="col">物种</th>
              <th scope="col">菌株数</th>
              <th scope="col">结果数</th>
              <th scope="col">最近分析</th>
              <th scope="col">来源</th>
              <th scope="col">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="row.specimen_id"
              class="row-click"
              @click="goRow($event, `/specimens/${row.specimen_id}`)"
            >
              <td data-label="样本">
                <RouterLink class="link-cell" :to="`/specimens/${row.specimen_id}`">
                  {{ row.specimen_id }}
                </RouterLink>
              </td>
              <td data-label="物种"><i>{{ displaySpecies(row.species) }}</i></td>
              <td data-label="菌株数"><span class="mono">{{ row.n_isolates ?? 0 }}</span></td>
              <td data-label="结果数"><span class="mono">{{ row.n_results ?? 0 }}</span></td>
              <td data-label="最近分析">{{ formatDate(row.last_analysis) }}</td>
              <td data-label="来源">{{ row.origin || '—' }}</td>
              <td data-label="备注" class="muted">{{ row.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="!query"
        title="暂无样本"
        hint="登记分析数据后，样本会自动出现在这里（旧数据迁移为影子样本）。"
      />
      <EmptyState v-else title="没有匹配的样本" hint="换个关键词试试。" />
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
