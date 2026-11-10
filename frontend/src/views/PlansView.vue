<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import PlanBadge from '../components/PlanBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { PlanRecord } from '../types'
import { fmtRelative, fmtTime, shortId } from '../lib/format'

const router = useRouter()
const plans = ref<PlanRecord[]>([])
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')

const sorted = computed(() =>
  plans.value.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
)

function goRow(event: Event, path: string) {
  const target = event.target
  if (target instanceof Element && target.closest('a,button')) return
  void router.push(path)
}

async function load(initial = false) {
  if (initial) loading.value = true
  else refreshing.value = true
  error.value = ''
  try {
    plans.value = await api.listPlans(100)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载计划失败'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

onMounted(() => void load(true))
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">计划</h1>
        <p class="pagehead__sub">
          外部智能体创建计划，人在这里审阅版本、参数与哈希后确认提交。
        </p>
      </div>
      <div class="pagehead__actions">
        <button class="btn btn--ghost" type="button" :disabled="refreshing" @click="load()">
          <span v-if="refreshing" class="spinner" />
          <Icon v-else name="refresh" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <section class="card">
      <div class="card__head">
        <h2 class="card__title">全部计划</h2>
        <span class="card__hint">{{ sorted.length }} 个版本</span>
      </div>

      <div v-if="loading" class="card__body"><div class="skeleton" style="height: 200px" /></div>

      <div v-else-if="sorted.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th scope="col">计划 ID</th>
              <th scope="col">版本</th>
              <th scope="col">状态</th>
              <th scope="col">任务</th>
              <th scope="col">创建者</th>
              <th scope="col">创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="plan in sorted"
              :key="`${plan.plan_id}-${plan.version}`"
              class="row-click"
              @click="goRow($event, `/plans/${plan.plan_id}?version=${plan.version}`)"
            >
              <td data-label="计划 ID">
                <RouterLink class="link-cell" :to="`/plans/${plan.plan_id}?version=${plan.version}`">
                  {{ shortId(plan.plan_id) }}
                </RouterLink>
                <div class="muted mono" style="font-size: 10.5px">hash {{ plan.plan_hash.slice(0, 12) }}…</div>
              </td>
              <td data-label="版本"><span class="mono">v{{ plan.version }}</span></td>
              <td data-label="状态"><PlanBadge :state="plan.state" /></td>
              <td data-label="任务"><span class="mono">{{ plan.tasks.length }}</span></td>
              <td data-label="创建者">{{ plan.created_by }}</td>
              <td data-label="创建时间">
                <span class="mono muted">{{ fmtTime(plan.created_at) }}</span>
                <div class="muted" style="font-size: 10.5px">{{ fmtRelative(plan.created_at) }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="还没有计划"
        hint="外部智能体通过 MCP 创建计划后，会在这里等待人工确认。"
        icon="plans"
      />
    </section>
  </div>
</template>
