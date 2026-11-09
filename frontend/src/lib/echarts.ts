import type { ECharts } from 'echarts/core'

let cached: Promise<typeof import('echarts/core')> | null = null

export async function echartsCore(): Promise<typeof import('echarts/core')> {
  if (!cached) {
    cached = (async () => {
      const [core, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])
      core.use([
        charts.PieChart,
        charts.BarChart,
        charts.LineChart,
        components.TooltipComponent,
        components.LegendComponent,
        components.GridComponent,
        components.DatasetComponent,
        renderers.CanvasRenderer,
      ])
      return core
    })()
  }
  return cached
}

export async function mountChart(
  el: HTMLElement,
  option: Record<string, unknown>,
): Promise<ECharts> {
  const core = await echartsCore()
  const chart = core.init(el, undefined, { renderer: 'canvas' })
  chart.setOption(option)
  return chart
}
