<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { ECharts } from 'echarts/core'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import { api } from '../api'
import type { CountItem, DatabaseStats, Overview, TaskRow } from '../types'
import { fmtRelative, fmtTime, shortId } from '../lib/format'
import { mountChart } from '../lib/echarts'
import { useTheme } from '../composables/useTheme'

const { resolved: resolvedTheme } = useTheme()

const tasks = ref<TaskRow[]>([])
const overview = ref<Overview | null>(null)
const stats = ref<DatabaseStats | null>(null)
const loading = ref(true)
const error = ref('')

const statusEl = ref<HTMLElement>()
const trendEl = ref<HTMLElement>()
let statusChart: ECharts | undefined
let trendChart: ECharts | undefined

// 任务列表只取最近 200 条；统计接口可用时以统计库全量计数为准。
const listCounts = computed(() => {
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

const statsAvailable = computed(() => stats.value !== null)

function stateCount(state: string): number {
  if (stats.value) return stats.value.tasks.by_state[state] ?? 0
  return listCounts.value[state] ?? 0
}

const total = computed(() => (stats.value ? stats.value.tasks.total : tasks.value.length))
const awaitingCount = computed(() => stateCount('awaiting_approval'))
const recent = computed(() => tasks.value.slice(0, 6))
const pending = computed(() => tasks.value.filter((t) => t.state === 'awaiting_approval'))
const shownPending = computed(() => pending.value.slice(0, 4))
const unlistedPending = computed(() => Math.max(0, awaitingCount.value - shownPending.value.length))

const chartPalette = computed(() => {
  if (resolvedTheme.value === 'light') {
    return {
      tooltipBg: '#ffffff',
      tooltipBorder: '#e4e7ec',
      text: '#344054',
      muted: '#667085',
      axis: '#e4e7ec',
      split: '#eef0f3',
      pieBorder: '#ffffff',
      bar: '#5e6ad2',
      running: '#2e90fa',
      await: '#f79009',
      ok: '#12b76a',
      fail: '#f04438',
      cancel: '#98a2b3',
      pending: '#98a2b3',
    }
  }
  if (resolvedTheme.value === 'gray') {
    return {
      tooltipBg: '#f7f7f2',
      tooltipBorder: '#111111',
      text: '#111111',
      muted: '#3f3f3b',
      axis: '#111111',
      split: 'rgba(10,10,10,.12)',
      pieBorder: '#f7f7f2',
      bar: '#111111',
      running: '#111111',
      await: '#b88a2e',
      ok: '#1f5c3a',
      fail: '#a11b1b',
      cancel: '#5a5a54',
      pending: '#3f3f3b',
    }
  }
  return {
    tooltipBg: '#202123',
    tooltipBorder: 'rgba(255,255,255,.12)',
    text: '#d0d6e0',
    muted: '#8a8f98',
    axis: '#2a2b2e',
    split: 'rgba(255,255,255,.06)',
    pieBorder: '#191a1b',
    bar: '#5e6ad2',
    running: '#6aa1ff',
    await: '#e8b64a',
    ok: '#2fbe77',
    fail: '#e5484d',
    cancel: '#5c6167',
    pending: '#8a8f98',
  }
})

const statusItems = computed(() => [
  { key: 'running', label: '运行中', value: stateCount('running'), color: chartPalette.value.running },
  { key: 'awaiting_approval', label: '待审批', value: stateCount('awaiting_approval'), color: chartPalette.value.await },
  { key: 'succeeded', label: '已完成', value: stateCount('succeeded'), color: chartPalette.value.ok },
  { key: 'failed', label: '已失败', value: stateCount('failed'), color: chartPalette.value.fail },
  { key: 'cancelled', label: '已取消', value: stateCount('cancelled'), color: chartPalette.value.cancel },
  { key: 'pending', label: '排队中', value: stateCount('pending'), color: chartPalette.value.pending },
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

const dbKpis = computed(() => {
  const s = stats.value
  return [
    { label: '菌株总数', value: s ? s.strains.total : '—', icon: 'records', foot: 'strain_genotype_index' },
    { label: '基因组对象', value: s ? s.gom.genome_objects : '—', icon: 'server', foot: 'GOM 不可变对象' },
    { label: 'AMR 基因命中', value: s ? s.gom.amr_genes : '—', icon: 'alert-triangle', foot: 'CARD/VFDB/NCBI 命中行' },
    { label: '样本报告', value: s ? s.results.sample_reports : '—', icon: 'file-text', foot: '已完成分析样本' },
    { label: '研究会话', value: s ? s.research.sessions : '—', icon: 'chart', foot: 'AMR 关联 / 高级统计' },
    { label: '知识库条目', value: s ? s.knowledge.entries : '—', icon: 'terminal', foot: '已审核知识条目' },
    { label: '运行记录', value: s ? s.runs.total : '—', icon: 'runs', foot: 'runs.sqlite' },
    { label: '化验结果', value: s ? s.lab_results.total : '—', icon: 'check-circle', foot: 'lab_results' },
  ]
})

type DistributionKey = 'species' | 'serotypes' | 'mlst' | 'amr'

interface DistributionRow extends CountItem {
  displayName: string
}

interface DistributionGroup {
  key: DistributionKey
  title: string
  label: string
  rows: DistributionRow[]
  total: number
}

const DISTRIBUTION_LIMIT = 10
const HIDDEN_DISTRIBUTION_NAMES = new Set(['', 'n/a', 'na', 'unknown', '未知'])

const distributionGroups = computed<DistributionGroup[]>(() => {
  const s = stats.value
  const groups: Array<{
    key: DistributionKey
    title: string
    label: string
    rows: CountItem[]
  }> = [
    { key: 'species', title: '物种分布', rows: s?.strains.species ?? [], label: '物种' },
    { key: 'serotypes', title: '血清型分布', rows: s?.strains.serotypes ?? [], label: '血清型' },
    { key: 'mlst', title: 'MLST ST 分布', rows: s?.strains.mlst ?? [], label: 'ST' },
    { key: 'amr', title: 'AMR 基因 Top 10', rows: s?.strains.amr_top ?? [], label: '基因' },
  ]

  return groups.map((group) => {
    const meaningful = group.rows.filter((row) => {
      const name = row.name.trim()
      return row.count > 0 && !HIDDEN_DISTRIBUTION_NAMES.has(name.toLowerCase())
    })
    return {
      ...group,
      rows: meaningful.slice(0, DISTRIBUTION_LIMIT).map((row) => {
        const name = row.name.trim()
        return {
          ...row,
          displayName: group.key === 'species' ? name.replace(/_/g, ' ') : name,
        }
      }),
      total: meaningful.length,
    }
  })
})

const statusOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    backgroundColor: chartPalette.value.tooltipBg,
    borderColor: chartPalette.value.tooltipBorder,
    textStyle: { color: chartPalette.value.text, fontSize: 12 },
  },
  legend: {
    bottom: 0,
    left: 'center',
    textStyle: { color: chartPalette.value.muted, fontSize: 11 },
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
        style: { text: '暂无任务', fill: chartPalette.value.muted, fontSize: 12 },
      },
  series: [
    {
      type: 'pie',
      radius: ['56%', '76%'],
      center: ['50%', '43%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: chartPalette.value.pieBorder, borderWidth: 2 },
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
    backgroundColor: chartPalette.value.tooltipBg,
    borderColor: chartPalette.value.tooltipBorder,
    textStyle: { color: chartPalette.value.text, fontSize: 12 },
  },
  xAxis: {
    type: 'category',
    data: trend.value.map((d) => d.label),
    axisLine: { lineStyle: { color: chartPalette.value.axis } },
    axisTick: { show: false },
    axisLabel: { color: chartPalette.value.muted, fontSize: 10 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: chartPalette.value.split } },
    axisLabel: { color: chartPalette.value.muted, fontSize: 10 },
  },
  series: [
    {
      type: 'bar',
      data: trend.value.map((d) => d.value),
      barWidth: '44%',
      itemStyle: { color: chartPalette.value.bar, borderRadius: [3, 3, 0, 0] },
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
    // 任务与数据库统计独立加载：统计接口不可用时，任务区仍然可用。
    const [taskRes, overviewRes, statsRes] = await Promise.allSettled([
      api.listTasks(200),
      api.overview(),
      api.stats(),
    ])
    const failures: string[] = []
    if (taskRes.status === 'fulfilled') tasks.value = taskRes.value
    else failures.push('任务列表加载失败')
    if (overviewRes.status === 'fulfilled') overview.value = overviewRes.value
    else failures.push('系统概览不可用')
    if (statsRes.status === 'fulfilled') stats.value = statsRes.value
    else failures.push('数据库统计不可用（如服务刚升级，请重启 bacmap web）')
    if (failures.length) error.value = failures.join('；')
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

function maxCount(rows: CountItem[]): number {
  return Math.max(1, ...rows.map((row) => row.count))
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

watch([statusItems, trend, resolvedTheme], () => {
  void renderCharts()
})
</script>

<template>
  <div>
    <div class="pagehead">
      <div>
        <h1 class="pagehead__title">仪表盘</h1>
        <p class="pagehead__sub">
          本地病原菌分析任务、菌株库、表型/型别与证据链总览。数据不出本机。
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

    <section class="gray-hero" aria-hidden="true">
      <div class="gray-hero__left">
        <div class="gray-hero__logo">BACMAP / LOCAL GENOMIC EVIDENCE</div>
        <h2>LOCAL<br />GENOMIC<br />EVIDENCE</h2>
        <div class="gray-hero__meta">
          {{ total }} TASKS / {{ stats?.strains.total ?? 0 }} STRAINS<br />
          D1—D4 / AIR-GAPPED / NO CLOUD
        </div>
      </div>
      <div class="gray-hero__map">
        <span v-for="i in 12" :key="i" class="gray-hero__node" />
      </div>
    </section>

    <div v-if="!loading && awaitingCount > 0" class="pending-banner" role="status">
      <Icon name="clock" />
      <div class="pending-banner__text">
        <strong class="pending-banner__title">{{ awaitingCount }} 个任务等待审批</strong>
        <span class="pending-banner__hint">curate 发布、mine 产物签字等门需要人工确认后才会继续。</span>
      </div>
      <RouterLink
        :to="pending.length ? `/tasks/${pending[0].task_id}` : '/tasks'"
        class="btn btn--ghost btn--sm"
      >
        去审批
        <Icon name="arrow-right" />
      </RouterLink>
    </div>

    <div v-if="error" class="form-error" style="margin-bottom: 16px">{{ error }}</div>

    <template v-if="loading">
      <div class="kpi-grid kpi-grid--tasks">
        <div v-for="i in 6" :key="i" class="kpi">
          <div class="skeleton" style="width: 70px" />
          <div class="skeleton" style="width: 52px; height: 30px; margin-top: 10px" />
        </div>
      </div>
      <div class="card card--pad"><div class="skeleton" style="height: 220px" /></div>
    </template>

    <template v-else>
      <section class="section">
        <div class="section__head">
          <h2 class="section__title">任务</h2>
          <span class="section__hint">{{ statsAvailable ? '全部任务（统计库）' : '最近 200 条' }}</span>
        </div>
        <div class="kpi-grid kpi-grid--tasks">
          <div class="kpi">
            <div class="kpi__label"><Icon name="tasks" /> 总任务</div>
            <div class="kpi__value">{{ total }}</div>
            <div class="kpi__foot">
              {{ statsAvailable ? '统计库全部任务记录' : '最近 200 条任务记录' }}
            </div>
          </div>
          <div class="kpi kpi--running">
            <div class="kpi__label"><Icon name="runs" /> 运行中</div>
            <div class="kpi__value">{{ stateCount('running') }}</div>
            <div class="kpi__foot">正在执行的分析管线</div>
          </div>
          <div class="kpi kpi--await">
            <div class="kpi__label"><Icon name="clock" /> 待审批</div>
            <div class="kpi__value">{{ awaitingCount }}</div>
            <div class="kpi__foot">等待人工签名的门</div>
          </div>
          <div class="kpi kpi--ok">
            <div class="kpi__label"><Icon name="check-circle" /> 已完成</div>
            <div class="kpi__value">{{ stateCount('succeeded') }}</div>
            <div class="kpi__foot">成功结束的任务</div>
          </div>
          <div class="kpi kpi--fail">
            <div class="kpi__label"><Icon name="alert-triangle" /> 已失败</div>
            <div class="kpi__value">{{ stateCount('failed') }}</div>
            <div class="kpi__foot">执行失败的任务</div>
          </div>
          <div class="kpi kpi--cancel">
            <div class="kpi__label"><Icon name="ban" /> 已取消</div>
            <div class="kpi__value">{{ stateCount('cancelled') }}</div>
            <div class="kpi__foot">人工取消的任务</div>
          </div>
        </div>
      </section>

      <section class="card section">
        <div class="card__head">
          <h2 class="card__title">待审批</h2>
          <span class="badge badge--awaiting_approval">
            <span class="badge__dot" aria-hidden="true" />
            {{ awaitingCount }}
          </span>
        </div>
        <div v-if="pending.length" class="stack" style="padding: 12px 16px 16px">
          <RouterLink
            v-for="task in shownPending"
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
          <p v-if="unlistedPending" class="pending-note">
            另有 {{ unlistedPending }} 个待审批任务未在此列出。
            <RouterLink to="/tasks" class="link-cell">前往任务页</RouterLink>
          </p>
        </div>
        <div v-else-if="awaitingCount" class="card__body">
          <p class="pending-note">
            统计库显示 {{ awaitingCount }} 个待审批任务，但它们不在最近 200 条任务列表中。
          </p>
          <RouterLink to="/tasks" class="btn btn--ghost btn--sm" style="margin-top: 10px">
            前往任务页
          </RouterLink>
        </div>
        <EmptyState
          v-else
          title="没有待审批任务"
          hint="curate 发布、mine 产物签字等门会在这里提醒你。"
          icon="check-circle"
        />
      </section>

      <section class="section">
        <div class="section__head">
          <h2 class="section__title">数据库概览</h2>
          <span class="section__hint">GOM · 菌株索引 · 研究 · 知识库</span>
        </div>
        <div class="kpi-grid kpi-grid--db">
          <div v-for="item in dbKpis" :key="item.label" class="kpi">
            <div class="kpi__label"><Icon :name="item.icon" /> {{ item.label }}</div>
            <div class="kpi__value">{{ item.value }}</div>
            <div class="kpi__foot">{{ item.foot }}</div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card__head">
          <h2 class="card__title">最近 7 天任务</h2>
          <span class="card__hint">基于最近 200 条任务 · 按创建日期统计</span>
        </div>
        <div v-if="tasks.length" class="card__body">
          <div ref="trendEl" class="chart chart--sm" role="img" aria-label="最近 7 天任务数量柱状图" />
        </div>
        <EmptyState v-else title="暂无任务" hint="提交任务后，这里会显示最近 7 天的任务趋势。" icon="chart" />
      </section>

      <section class="card">
        <div class="card__head">
          <h2 class="card__title">任务状态分布</h2>
          <span class="card__hint">{{ statsAvailable ? '全部任务（统计库）' : '最近 200 条任务' }}</span>
        </div>
        <div v-if="total" class="card__body">
          <div ref="statusEl" class="chart" role="img" aria-label="任务状态分布环形图" />
        </div>
        <EmptyState v-else title="暂无任务" hint="任务状态分布会在提交第一个任务后出现。" icon="tasks" />
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

      <section class="section">
        <div class="section__head">
          <h2 class="section__title">菌株与型别分布</h2>
          <span class="section__hint">GOM 菌株索引</span>
        </div>
        <div v-if="stats?.strains.total" class="distribution-grid">
          <section v-for="group in distributionGroups" :key="group.key" class="card">
            <div class="card__head">
              <h2 class="card__title">{{ group.title }}</h2>
              <span class="card__hint">
                <template v-if="group.total > group.rows.length">
                  Top {{ group.rows.length }} · 共 {{ group.total }} 类
                </template>
                <template v-else>{{ group.total }} 类</template>
              </span>
            </div>
            <div v-if="group.rows.length" class="card__body">
              <div class="distribution">
                <div v-for="row in group.rows" :key="`${group.key}-${row.name}`" class="distribution__row">
                  <span class="distribution__name" :title="row.displayName">
                    <i v-if="group.key === 'species'">{{ row.displayName }}</i>
                    <template v-else>{{ row.displayName }}</template>
                  </span>
                  <span class="distribution__track">
                    <span class="distribution__bar" :style="{ width: `${(row.count / maxCount(group.rows)) * 100}%` }" />
                  </span>
                  <span class="distribution__count mono">{{ row.count }}</span>
                </div>
              </div>
            </div>
            <EmptyState v-else title="暂无数据" hint="完成分析后，型别与表型信息会汇总到这里。" icon="chart" />
          </section>
        </div>
        <section v-else class="card">
          <EmptyState
            v-if="!stats"
            title="数据库统计不可用"
            :hint="error || '统计接口没有返回数据；请重启 bacmap web 后刷新。'"
            icon="chart"
          />
          <EmptyState
            v-else
            title="暂无菌株统计"
            hint="完成一次分析并写入 GOM 后，物种、血清型、MLST 与 AMR 分布会出现在这里。"
            icon="chart"
          />
        </section>
      </section>

      <section class="card card--pad">
        <div class="card__head" style="padding: 0; border: 0; margin-bottom: 12px">
          <h2 class="card__title">系统状态</h2>
          <RouterLink to="/overview" class="btn btn--ghost btn--sm">概览</RouterLink>
        </div>
        <div v-if="overview" class="meta-grid">
          <div class="meta-item"><dt>沙箱</dt><dd>{{ overview.sandbox }}</dd></div>
          <div class="meta-item"><dt>数据上限</dt><dd>{{ overview.cloud_max_data_class }}</dd></div>
          <div class="meta-item"><dt>LLM 端点</dt><dd>{{ overview.endpoints.length }} 个</dd></div>
          <div class="meta-item"><dt>bacmap</dt><dd class="mono">{{ overview.versions.bacmap ?? '—' }}</dd></div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.section {
  margin-bottom: 20px;
}

.section__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.section__title {
  color: var(--text-1);
  font-size: 16px;
  font-weight: 600;
}

.section__hint {
  color: var(--text-3);
  font-size: 12px;
}

.kpi-grid--tasks {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.kpi-grid--db {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.kpi--cancel {
  --kpi-glow: rgba(138, 143, 152, 0.14);
}

.pending-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border: 1px solid var(--st-await-line);
  border-radius: var(--r-card);
  background: var(--st-await-bg);
}

.pending-banner > .icon {
  flex: none;
  width: 18px;
  height: 18px;
  color: var(--st-await-dot);
}

.pending-banner__text {
  display: grid;
  flex: 1;
  gap: 2px;
  min-width: 220px;
}

.pending-banner__title {
  color: var(--st-await-text);
  font-size: 13px;
  font-weight: 600;
}

.pending-banner__hint {
  color: var(--text-3);
  font-size: 12px;
}

.pending-banner .btn {
  flex: none;
}

.pending-note {
  margin: 0;
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.6;
}

.distribution-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
  align-items: start;
}

@media (min-width: 1100px) {
  .distribution-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.distribution {
  display: grid;
  gap: 8px;
}

.distribution__row {
  display: grid;
  grid-template-columns: minmax(110px, 180px) minmax(0, 1fr) 48px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.distribution__name {
  overflow: hidden;
  color: var(--text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.distribution__track {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--surface-track);
}

.distribution__bar {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--link));
}

.distribution__count {
  color: var(--text-3);
  text-align: right;
}

.pending-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-ctl);
  background: var(--surface-soft);
  transition: border-color 140ms ease-out, background-color 140ms ease-out;
}

.pending-item:hover {
  border-color: var(--st-await-line);
  background: var(--st-await-bg);
}

.pending-item .icon {
  color: var(--text-4);
}

@media (max-width: 1180px) {
  .kpi-grid--tasks {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .kpi-grid--db {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .kpi-grid--tasks,
  .kpi-grid--db {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .distribution__row {
    grid-template-columns: minmax(90px, 130px) minmax(0, 1fr) 36px;
  }
}
</style>
