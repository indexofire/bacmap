<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { ECharts } from 'echarts/core'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { Overview, TaskRow } from '../types'
import { fmtRelative, fmtTime, shortId } from '../lib/format'
import { mountChart } from '../lib/echarts'

const tasks = ref<TaskRow[]>([])
const overview = ref<Overview | null>(null)
const loading = ref(true)
const error = ref('')

const statusEl = ref<HTMLElement>()
const trendEl = ref<HTMLElement>()
let statusChart: ECharts | undefined
let trendChart: ECharts | undefined

const counts = computed(() => {
  const out: Record<string, number> = {
    pending: 0,
    running: 0,
    awaiting_approval: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
  }
  for (const task of tasks.value) out[task.state] = (out[task.state] ?? 0) + 1
  return out
})

const total = computed(() => tasks.value.length)
const recent = computed(() => tasks.value.slice(0, 6))
const pending = computed(() => tasks.value.filter((t) => t.state === 'awaiting_approval'))

const statusItems = computed(() => [
  { key: 'running', label: '运行中', value: counts.value.running, color: '#6aa1ff' },
  { key: 'awaiting_approval', label: '待审批', value: counts.value.awaiting_approval, color: '#e8b64a' },
  { key: 'succeeded', label: '已完成', value: counts.value.succeeded, color: '#2fbe77' },
  { key: 'failed', label: '已失败', value: counts.value.failed, color: '#e5484d' },
  { key: 'cancelled', label: '已取消', value: counts.value.cancelled, color: '#5c6167' },
  { key: 'pending', label: '排队中', value: counts.value.pending, color: '#8a8f98' },
])

const trend = computed(() => {
  const days: Array<{ label: string; value: number }> = []
  const now = new Date()
  for (let i = 6; i >= 0; i--) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i)
    const key = `${day.getFullYear()}-${day.getMonth() + 1}-${day.getDate()}`
    days.push({
      label: `${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`,
      value: tasks.value.filter((t) => {
        const d = new Date(t.created_at)
        return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}` === key
      }).length,
    })
  }
  return days
})

const statusOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    backgroundColor: '#202123',
    borderColor: 'rgba(255,255,255,.12)',
    textStyle: { color: '#d0d6e0', fontSize: 12 },
  },
  legend: {
    bottom: 0,
    left: 'center',
    textStyle: { color: '#8a8f98', fontSize: 11 },
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 14,
  },
  graphic: statusItems.value.some((item) => item.value > 0)
    ? undefined
    : {
        type: 'text',
        left: 'center',
        top: 'middle',
        style: { text: '暂无任务', fill: '#8a8f98', fontSize: 12 },
      },
  series: [
    {
      type: 'pie',
      radius: ['56%', '76%'],
      center: ['50%', '43%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: '#191a1b', borderWidth: 2 },
      label: { show: false },
      data: statusItems.value
        .filter((item) => item.value > 0)
        .map((item) => ({ name: item.label, value: item.value, itemStyle: { color: item.color } })),
    },
  ],
}))

const trendOption = computed(() => ({
  backgroundColor: 'transparent',
  grid: { left: 4, right: 8, top: 18, bottom: 22, containLabel: true },
  tooltip: {
    trigger: 'axis',
    backgroundColor: '#202123',
    borderColor: 'rgba(255,255,255,.12)',
    textStyle: { color: '#d0d6e0', fontSize: 12 },
  },
  xAxis: {
    type: 'category',
    data: trend.value.map((d) => d.label),
    axisLine: { lineStyle: { color: '#2a2b2e' } },
    axisTick: { show: false },
    axisLabel: { color: '#8a8f98', fontSize: 10 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } },
    axisLabel: { color: '#8a8f98', fontSize: 10 },
  },
  series: [
    {
      type: 'bar',
      data: trend.value.map((d) => d.value),
      barWidth: '44%',
      itemStyle: { color: '#5e6ad2', borderRadius: [3, 3, 0, 0] },
    },
  ],
}))

async function renderCharts() {
  await nextTick()
  if (statusEl.value) {
    if (statusChart) statusChart.setOption(statusOption.value)
    else statusChart = await mountChart(statusEl.value, statusOption.value)
  }
  if (trendEl.value) {
    if (trendChart) trendChart.setOption(trendOption.value)
    else trendChart = await mountChart(trendEl.value, trendOption.value)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [taskItems, overviewData] = await Promise.all([api.listTasks(200), api.overview()])
    tasks.value = taskItems
    overview.value = overviewData
    loading.value = false
    await renderCharts()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function resize() {
  statusChart?.resize()
  trendChart?.resize()
}

onMounted(() => {
  void load()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  statusChart?.dispose()
  trendChart?.dispose()
})

watch([statusItems, trend], () => {
  void renderCharts()
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">仪表盘</h1>
        <p class="pagehead__sub">
          本地病原菌分析任务总览。任务状态、审批门与运行证据都在本机。
        </p>
      </div>
      <div class="pagehead__actions">
        <RouterLink to="/tasks" class="btn btn--ghost">
          <Icon name="tasks" />
          全部任务
        </RouterLink>
        <RouterLink to="/tasks?new=1" class="btn btn--primary">
          <Icon name="plus" />
          提交任务
        </RouterLink>
      </div>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="kpi-grid">
        <div v-for="i in 4" :key="i" class="kpi">
          <div class="skeleton" style="width: 70px" />
          <div class="skeleton" style="width: 52px; height: 30px; margin-top: 10px" />
        </div>
      </div>
      <div class="dash-grid">
        <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
        <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
      </div>
    </template>

    <template v-else>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi__label"><Icon name="tasks" /> 总任务</div>
          <div class="kpi__value">{{ total }}</div>
          <div class="kpi__foot">最近 200 条任务记录</div>
        </div>
        <div class="kpi kpi--running">
          <div class="kpi__label"><Icon name="runs" /> 运行中</div>
          <div class="kpi__value">{{ counts.running }}</div>
          <div class="kpi__foot">正在执行的分析管线</div>
        </div>
        <div class="kpi kpi--await">
          <div class="kpi__label"><Icon name="clock" /> 待审批</div>
          <div class="kpi__value">{{ counts.awaiting_approval }}</div>
          <div class="kpi__foot">等待人工签名的门</div>
        </div>
        <div class="kpi kpi--ok">
          <div class="kpi__label"><Icon name="check-circle" /> 已完成</div>
          <div class="kpi__value">{{ counts.succeeded }}</div>
          <div class="kpi__foot">成功结束的任务</div>
        </div>
      </div>

      <div class="dash-grid">
        <div class="stack">
          <section class="card">
            <div class="card__head">
              <h2 class="card__title">最近 7 天任务</h2>
              <span class="card__hint">按创建日期统计</span>
            </div>
            <div class="card__body">
              <div ref="trendEl" class="chart chart--sm" role="img" aria-label="最近 7 天任务数量柱状图" />
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">最近任务</h2>
              <RouterLink to="/tasks" class="btn btn--ghost btn--sm">查看全部</RouterLink>
            </div>
            <div v-if="recent.length" class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th scope="col">任务 ID</th>
                    <th scope="col">类型</th>
                    <th scope="col">状态</th>
                    <th scope="col">提交人</th>
                    <th scope="col">创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="task in recent" :key="task.task_id" class="row-click">
                    <td data-label="任务 ID">
                      <RouterLink class="link-cell" :to="`/tasks/${task.task_id}`">
                        {{ shortId(task.task_id) }}
                      </RouterLink>
                    </td>
                    <td data-label="类型"><code>{{ task.task_type }}</code></td>
                    <td data-label="状态"><StatusBadge :state="task.state" /></td>
                    <td data-label="提交人">{{ task.submitted_by }}</td>
                    <td data-label="创建时间"><span class="mono muted">{{ fmtTime(task.created_at) }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState
              v-else
              title="还没有任务"
              hint="从任务页提交第一个分析任务；运行状态会实时出现在这里。"
              icon="tasks"
            >
              <RouterLink to="/tasks?new=1" class="btn btn--primary btn--sm">提交任务</RouterLink>
            </EmptyState>
          </section>
        </div>

        <div class="stack">
          <section class="card">
            <div class="card__head">
              <h2 class="card__title">任务状态分布</h2>
              <span class="card__hint">全部任务</span>
            </div>
            <div class="card__body">
              <div ref="statusEl" class="chart" role="img" aria-label="任务状态分布环形图" />
            </div>
          </section>

          <section class="card">
            <div class="card__head">
              <h2 class="card__title">待审批</h2>
              <span class="badge badge--awaiting_approval">
                <span class="badge__dot" aria-hidden="true" />
                {{ pending.length }}
              </span>
            </div>
            <div v-if="pending.length" class="stack" style="padding: 12px 16px 16px">
              <RouterLink
                v-for="task in pending.slice(0, 4)"
                :key="task.task_id"
                :to="`/tasks/${task.task_id}`"
                class="pending-item"
              >
                <div>
                  <div class="mono" style="color: var(--text-1); font-size: 12px">
                    {{ shortId(task.task_id, 16) }}
                  </div>
                  <div class="muted" style="font-size: 11.5px">
                    {{ task.task_type }} · {{ fmtRelative(task.created_at) }}
                  </div>
                </div>
                <Icon name="chevron-right" />
              </RouterLink>
            </div>
            <EmptyState
              v-else
              title="没有待审批任务"
              hint="curate 发布、mine 产物签字等门会在这里提醒你。"
              icon="check-circle"
            />
          </section>

          <section class="card card--pad">
            <div class="card__head" style="padding: 0; border: 0; margin-bottom: 12px">
              <h2 class="card__title">系统状态</h2>
              <RouterLink to="/overview" class="btn btn--ghost btn--sm">概览</RouterLink>
            </div>
            <div v-if="overview" class="meta-grid">
              <div class="meta-item">
                <dt>沙箱</dt>
                <dd>{{ overview.sandbox }}</dd>
              </div>
              <div class="meta-item">
                <dt>数据上限</dt>
                <dd>{{ overview.cloud_max_data_class }}</dd>
              </div>
              <div class="meta-item">
                <dt>LLM 端点</dt>
                <dd>{{ overview.endpoints.length }} 个</dd>
              </div>
              <div class="meta-item">
                <dt>bacmap</dt>
                <dd class="mono">{{ overview.versions.bacmap ?? '—' }}</dd>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pending-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-ctl);
  background: rgba(255, 255, 255, 0.02);
  transition: border-color 140ms ease-out, background-color 140ms ease-out;
}

.pending-item:hover {
  border-color: var(--st-await-line);
  background: rgba(232, 182, 74, 0.06);
}

.pending-item .icon {
  color: var(--text-4);
}
</style>
