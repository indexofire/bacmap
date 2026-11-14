<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'
import Pager from '../components/Pager.vue'
import { api } from '../api'
import type { IsolateRow, SpecimenRow } from '../types'

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

const unassigned = computed(() =>
  isolates.value.filter((row) => !row.specimen_id),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) =>
    [row.specimen_id, row.origin, row.note].join(' ').toLowerCase().includes(q),
  )
})

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
      api.specimensPage(offset.value, limit.value),
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

function changePage(value: number) {
  offset.value = value
  void load()
}

function changeLimit(value: number) {
  limit.value = value
  offset.value = 0
  void load()
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
    const result = await api.assignSpecimen({
      specimen_id: specimenId,
      isolates: selectedIsolates.value,
      datasets,
    })
    assignMessage.value =
      `已关联 ${result.updated} 行` +
      (result.missing.length ? `；未找到：${result.missing.join(', ')}` : '')
    selectedIsolates.value = []
    assignDatasets.value = ''
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '关联失败'
  } finally {
    assigning.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">样本</h1>
        <p class="pagehead__sub">
          送检样本（specimen）；一份样本可分离出多个菌株，也可直接测序（mNGS/tNGS，后续版本）。
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

    <section class="card card--pad" style="margin-bottom: 16px">
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
            关联
          </button>
          <span v-if="assignMessage" class="card__hint">{{ assignMessage }}</span>
        </div>
      </form>
    </section>

    <section class="card">
      <div class="filters">
        <label class="search-mini">
          <Icon name="search" />
          <input v-model="query" type="search" placeholder="搜索样本编号…" />
        </label>
        <span class="filter-spacer" />
        <span class="card__hint">{{ filtered.length }} / {{ total }} 份</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 220px" /></div>

      <div v-else-if="filtered.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">样本</th>
              <th scope="col">菌株数</th>
              <th scope="col">来源</th>
              <th scope="col">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in filtered"
              :key="row.specimen_id"
              class="row-click"
              @click="goRow($event, `/specimens/${row.specimen_id}`)"
            >
              <td data-label="样本">
                <RouterLink class="link-cell" :to="`/specimens/${row.specimen_id}`">
                  {{ row.specimen_id }}
                </RouterLink>
              </td>
              <td data-label="菌株数"><span class="mono">{{ row.n_isolates ?? 0 }}</span></td>
              <td data-label="来源">{{ row.origin || '—' }}</td>
              <td data-label="备注" class="muted">{{ row.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else-if="rows.length === 0"
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
