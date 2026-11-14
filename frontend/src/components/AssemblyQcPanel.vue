<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ECharts } from 'echarts/core'
import { mountChart } from '../lib/echarts'
import { useTheme } from '../composables/useTheme'
import type { AssemblyContigStats, ContigBin } from '../types'

const props = defineProps<{
  stats: AssemblyContigStats | null
  quastText?: string
}>()

const { resolved: resolvedTheme } = useTheme()

const lengthEl = ref<HTMLElement>()
const gcEl = ref<HTMLElement>()
const nxEl = ref<HTMLElement>()
let lengthChart: ECharts | undefined
let gcChart: ECharts | undefined
let nxChart: ECharts | undefined

const palette = computed(() => {
  if (resolvedTheme.value === 'light') {
    return {
      bar: '#5e6ad2',
      text: '#344054',
      muted: '#667085',
      axis: '#e4e7ec',
      split: '#eef0f3',
      tooltipBg: '#ffffff',
      tooltipBorder: '#e4e7ec',
    }
  }
  if (resolvedTheme.value === 'gray') {
    return {
      bar: '#111111',
      text: '#26251f',
      muted: '#6b6a63',
      axis: '#c9c7bd',
      split: '#e4e2d9',
      tooltipBg: '#f5f4ef',
      tooltipBorder: '#c9c7bd',
    }
  }
  return {
    bar: '#828fff',
    text: '#d0d6e0',
    muted: '#8a8f98',
    axis: 'rgba(255,255,255,0.08)',
    split: 'rgba(255,255,255,0.05)',
    tooltipBg: '#0f1011',
    tooltipBorder: 'rgba(255,255,255,0.1)',
  }
})

function fmtBp(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} Mb`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)} kb`
  return `${Math.round(n)} bp`
}

function binTooltip(bins: ContigBin[]) {
  return (params: { dataIndex?: number } | Array<{ dataIndex?: number }>) => {
    const first = Array.isArray(params) ? params[0] : params
    const bin = bins[first?.dataIndex ?? 0]
    if (!bin) return ''
    return `${bin.label}<br/>${bin.count} 条 · ${fmtBp(bin.bp)}`
  }
}

function categoryAxis(labels: string[]) {
  return {
    type: 'category',
    data: labels,
    axisLabel: {
      color: palette.value.muted,
      fontSize: 10,
      interval: 0,
      rotate: labels.length > 7 ? 30 : 0,
    },
    axisLine: { lineStyle: { color: palette.value.axis } },
    axisTick: { show: false },
  }
}

function valueAxis() {
  return {
    type: 'value',
    axisLabel: { color: palette.value.muted, fontSize: 10 },
    splitLine: { lineStyle: { color: palette.value.split } },
  }
}

const baseOption = computed(() => ({
  animationDuration: 280,
  grid: { left: 10, right: 14, top: 18, bottom: 26, containLabel: true },
  tooltip: {
    trigger: 'axis',
    backgroundColor: palette.value.tooltipBg,
    borderColor: palette.value.tooltipBorder,
    textStyle: { color: palette.value.text, fontSize: 12 },
  },
}))

const lengthOption = computed<Record<string, unknown>>(() => {
  const bins = props.stats?.length_bins ?? []
  return {
    ...baseOption.value,
    xAxis: categoryAxis(bins.map((bin) => bin.label)),
    yAxis: valueAxis(),
    tooltip: { ...baseOption.value.tooltip, formatter: binTooltip(bins) },
    series: [
      {
        type: 'bar',
        name: 'contig 数',
        data: bins.map((bin) => bin.count),
        barMaxWidth: 30,
        itemStyle: { color: palette.value.bar, borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})

const gcOption = computed<Record<string, unknown>>(() => {
  const bins = props.stats?.gc_bins ?? []
  return {
    ...baseOption.value,
    xAxis: categoryAxis(bins.map((bin) => bin.label)),
    yAxis: valueAxis(),
    tooltip: { ...baseOption.value.tooltip, formatter: binTooltip(bins) },
    series: [
      {
        type: 'bar',
        name: 'contig 数',
        data: bins.map((bin) => bin.count),
        barMaxWidth: 30,
        itemStyle: { color: palette.value.bar, borderRadius: [3, 3, 0, 0] },
      },
    ],
  }
})

const nxOption = computed<Record<string, unknown>>(() => {
  const points = props.stats?.nx ?? []
  return {
    ...baseOption.value,
    grid: { left: 10, right: 18, top: 18, bottom: 26, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((point) => `${point.x}%`),
      axisLabel: { color: palette.value.muted, fontSize: 10, interval: 3 },
      axisLine: { lineStyle: { color: palette.value.axis } },
      axisTick: { show: false },
    },
    yAxis: {
      ...valueAxis(),
      axisLabel: {
        color: palette.value.muted,
        fontSize: 10,
        formatter: (value: number) => fmtBp(value),
      },
    },
    tooltip: {
      ...baseOption.value.tooltip,
      formatter: (params: { dataIndex?: number } | Array<{ dataIndex?: number }>) => {
        const first = Array.isArray(params) ? params[0] : params
        const point = points[first?.dataIndex ?? 0]
        if (!point) return ''
        return `累计 ${point.x}%<br/>${fmtBp(point.length)}`
      },
    },
    series: [
      {
        type: 'line',
        name: 'Nx',
        data: points.map((point) => point.length),
        showSymbol: false,
        smooth: false,
        lineStyle: { color: palette.value.bar, width: 2 },
        areaStyle: { color: palette.value.bar, opacity: 0.12 },
      },
    ],
  }
})

const kpis = computed(() => {
  const s = props.stats
  if (!s) return []
  return [
    { label: '总长度', value: fmtBp(s.total_length), hint: `${s.count} 条 contig` },
    { label: '最长 contig', value: fmtBp(s.largest), hint: 'N0' },
    { label: 'N50', value: fmtBp(s.n50), hint: `L50 ${s.l50} 条覆盖 50%` },
    { label: 'N75', value: fmtBp(s.n75), hint: `L75 ${s.l75} 条覆盖 75%` },
    { label: 'N90', value: fmtBp(s.n90), hint: `L90 ${s.l90} 条覆盖 90%` },
    {
      label: 'GC 平均',
      value: s.gc_mean != null ? `${s.gc_mean.toFixed(2)}%` : '—',
      hint: '按 contig 长度加权',
    },
  ]
})

async function renderCharts() {
  await nextTick()
  if (lengthEl.value) {
    if (lengthChart) lengthChart.setOption(lengthOption.value)
    else lengthChart = await mountChart(lengthEl.value, lengthOption.value)
  }
  if (gcEl.value) {
    if (gcChart) gcChart.setOption(gcOption.value)
    else gcChart = await mountChart(gcEl.value, gcOption.value)
  }
  if (nxEl.value) {
    if (nxChart) nxChart.setOption(nxOption.value)
    else nxChart = await mountChart(nxEl.value, nxOption.value)
  }
}

function onResize() {
  lengthChart?.resize()
  gcChart?.resize()
  nxChart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  void renderCharts()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  lengthChart?.dispose()
  gcChart?.dispose()
  nxChart?.dispose()
})

watch([() => props.stats, resolvedTheme], () => {
  void renderCharts()
})
</script>

<template>
  <section class="card">
    <div class="card__head">
      <h2 class="card__title">组装质控</h2>
      <span class="card__hint">QUAST 汇总 + seqkit 逐 contig（含 &lt;500 bp）</span>
    </div>
    <div class="card__body">
      <template v-if="props.stats">
        <div class="qc-kpis">
          <div v-for="item in kpis" :key="item.label" class="qc-kpi">
            <span class="qc-kpi__label">{{ item.label }}</span>
            <strong class="qc-kpi__value mono">{{ item.value }}</strong>
            <span class="qc-kpi__hint">{{ item.hint }}</span>
          </div>
        </div>

        <div class="qc-charts">
          <div class="qc-chart">
            <h3 class="qc-chart__title">Contig 长度分布</h3>
            <div ref="lengthEl" class="qc-chart__canvas" role="img" aria-label="Contig 长度分布" />
          </div>
          <div class="qc-chart">
            <h3 class="qc-chart__title">GC 分布（按 contig）</h3>
            <div ref="gcEl" class="qc-chart__canvas" role="img" aria-label="GC 分布" />
          </div>
          <div class="qc-chart qc-chart--wide">
            <h3 class="qc-chart__title">Nx 曲线（累计长度）</h3>
            <div ref="nxEl" class="qc-chart__canvas" role="img" aria-label="Nx 曲线" />
          </div>
        </div>

        <div v-if="props.stats.top_contigs.length" class="qc-top table-wrap">
          <table class="table">
            <thead>
              <tr><th scope="col">最长 contig</th><th scope="col">长度</th><th scope="col">GC</th></tr>
            </thead>
            <tbody>
              <tr v-for="contig in props.stats.top_contigs.slice(0, 5)" :key="contig.name">
                <td><code>{{ contig.name }}</code></td>
                <td class="mono">{{ fmtBp(contig.length) }}</td>
                <td class="mono">{{ contig.gc != null ? `${contig.gc}%` : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <details v-if="props.quastText" class="qc-raw">
        <summary>原始 QUAST 汇总数据</summary>
        <pre class="code-block">{{ props.quastText }}</pre>
      </details>
    </div>
  </section>
</template>

<style scoped>
.qc-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.qc-kpi {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-soft);
}

.qc-kpi__label {
  color: var(--text-3);
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.qc-kpi__value {
  color: var(--text-1);
  font-size: 17px;
  font-weight: 600;
}

.qc-kpi__hint {
  color: var(--text-4);
  font-size: 10px;
}

.qc-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.qc-chart {
  min-width: 0;
  padding: 12px 12px 6px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-soft);
}

.qc-chart--wide {
  grid-column: 1 / -1;
}

.qc-chart__title {
  margin: 0 0 6px;
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.qc-chart__canvas {
  width: 100%;
  height: 210px;
}

.qc-top {
  margin-top: 14px;
}

.qc-raw {
  margin-top: 14px;
}

.qc-raw summary {
  cursor: pointer;
  color: var(--text-3);
  font-size: 12px;
}

@media (max-width: 900px) {
  .qc-charts {
    grid-template-columns: 1fr;
  }
}
</style>
