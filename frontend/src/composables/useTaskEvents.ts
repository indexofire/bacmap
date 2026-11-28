import { reactive, ref } from 'vue'
import { api } from '../api'
import { appUrl } from '../lib/format'
import type { TaskEvent } from '../types'

/**
 * 管线步级实时进度共享存储。
 *
 * 后端 StepWatcher 在分析运行期间把每个落盘子步骤写成富化 ``task.step`` 事件
 * （payload: {step, subject, result, artifact}）。本 composable 提供两条摄取通道：
 *
 * 1. ``ingest(events)``——页面轮询（如任务详情页）顺手喂入，零额外开销；
 * 2. ``ensureStream()``——全局 SSE 单例（对话卡片等长生命周期 UI 用），
 *    断线由浏览器 EventSource 自动重连（Last-Event-ID 续传）。
 *
 * 事件是观察不是真相：同一 (step, subject) 覆盖式合并，丢失时页面刷新后
 * 由 ``backfill`` 重新拉取。
 */

export interface StepEntry {
  step: string
  subject: string
  result: Record<string, unknown>
  artifact?: string
  occurred_at?: string
}

/** taskId → `${subject}:${step}` → StepEntry */
const progress = reactive<Record<string, Record<string, StepEntry>>>({})
/** taskId → 最新任务状态（task.state 事件） */
const states = reactive<Record<string, string>>({})
/** subject（样本/组）→ 最近出现该主体的 taskId（样本页反查运行中任务用） */
const subjectIndex = reactive<Record<string, string>>({})
const streaming = ref(false)

/** 展示顺序与中文标签（与后端 step_watch.STEP_SPECS 对齐）。 */
export const STEP_ORDER: Array<[string, string]> = [
  ['species', '物种鉴定'],
  ['assembly', '组装质控'],
  ['mlst', 'MLST 分型'],
  ['serotype', '血清型/基因型'],
  ['amr', '耐药检测'],
  ['vfdb', '毒力基因筛查'],
  ['card', '耐药基因筛查'],
  ['plasmid', '质粒筛查'],
  ['prelim_summary', '初步汇总'],
  ['final_summary', '最终汇总'],
  ['report', '完整报告'],
  ['cgmlst', 'cgMLST 队列'],
]

function stepIndex(step: string): number {
  const idx = STEP_ORDER.findIndex(([key]) => key === step)
  return idx >= 0 ? idx : STEP_ORDER.length
}

function ingestEvent(ev: TaskEvent): void {
  if (!ev.task_id) return
  if (ev.type === 'task.state') {
    const state = typeof ev.payload?.state === 'string' ? ev.payload.state : ''
    if (state) states[ev.task_id] = state
    return
  }
  if (ev.type !== 'task.step') return
  const step = typeof ev.payload?.step === 'string' ? ev.payload.step : ''
  if (!step || !STEP_ORDER.some(([key]) => key === step)) return
  const subject = typeof ev.payload?.subject === 'string' ? ev.payload.subject : ''
  const result =
    typeof ev.payload?.result === 'object' && ev.payload.result !== null
      ? (ev.payload.result as Record<string, unknown>)
      : {}
  const artifact = typeof ev.payload?.artifact === 'string' ? ev.payload.artifact : undefined
  const bucket = (progress[ev.task_id] ??= {})
  bucket[`${subject}:${step}`] = {
    step,
    subject,
    result,
    artifact,
    occurred_at: ev.occurred_at,
  }
  if (subject) subjectIndex[subject] = ev.task_id
}

function ingest(events: TaskEvent[]): void {
  for (const ev of events) ingestEvent(ev)
  evictIfNeeded()
}

/**
 * 内存上界：SPA 长会话里 progress/states/subjectIndex 会随任务数单调增长。
 * 终态任务的步骤条目在卡片收起后没有持续价值——超过上限时优先逐出终态
 * 任务（按插入序最旧的在前），运行中任务最后才逐出。被逐出的任务若再次
 * 进入视野，backfill 会重新拉取，语义无损。
 */
const MAX_TRACKED_TASKS = 50
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])

function evictIfNeeded(): void {
  const keys = Object.keys(progress)
  if (keys.length <= MAX_TRACKED_TASKS) return
  const terminalFirst = [...keys].sort((a, b) => {
    const ta = TERMINAL.has(states[a] ?? '') ? 0 : 1
    const tb = TERMINAL.has(states[b] ?? '') ? 0 : 1
    return ta - tb
  })
  for (const key of terminalFirst.slice(0, keys.length - MAX_TRACKED_TASKS)) {
    delete progress[key]
    delete states[key]
    for (const [subject, taskId] of Object.entries(subjectIndex)) {
      if (taskId === key) delete subjectIndex[subject]
    }
  }
}

/** 拉取某任务的历史步级事件补齐 store（进入页面/会话时调用）。 */
async function backfill(taskId: string): Promise<void> {
  if (!taskId) return
  try {
    const body = await api.listEvents({ task_id: taskId, limit: 200 })
    ingest(body.events)
  } catch {
    // 事件接口不可用时静默——详情页自身的轮询会覆盖。
  }
}

/**
 * 样本页反查：运行中的分析还没有运行记录链接，扫描近期事件里该样本的
 * 步级产物（Role.USER 由服务端自动限定为自己提交的任务），找到后整量回填。
 */
async function backfillSample(sampleId: string): Promise<void> {
  if (!sampleId) return
  try {
    const body = await api.listEvents({ limit: 200 })
    ingest(body.events)
    const taskId = subjectIndex[sampleId]
    if (taskId) await backfill(taskId)
  } catch {
    // 静默：实时流仍覆盖后续步骤。
  }
}

/** 任务的步级条目按 (subject, 固定步序) 排序输出。 */
function stepsFor(taskId: string): StepEntry[] {
  const bucket = progress[taskId]
  if (!bucket) return []
  return Object.values(bucket).sort((a, b) => {
    if (a.subject !== b.subject) return a.subject.localeCompare(b.subject)
    return stepIndex(a.step) - stepIndex(b.step)
  })
}

let eventSource: EventSource | null = null

/** 全局 SSE 单例：从最新 seq 起订阅 task.step / task.state。 */
async function ensureStream(): Promise<void> {
  if (eventSource || streaming.value) return
  streaming.value = true
  try {
    const { max_seq } = await api.listEvents({ limit: 1 })
    eventSource = new EventSource(appUrl(`/api/v1/events/stream?after=${max_seq}`))
    const onEvent = (event: MessageEvent<string>) => {
      try {
        ingestEvent(JSON.parse(event.data) as TaskEvent)
        evictIfNeeded()
      } catch {
        // 非 JSON 或未知事件：SSE 连接保持。
      }
    }
    eventSource.addEventListener('task.step', onEvent as EventListener)
    eventSource.addEventListener('task.state', onEvent as EventListener)
    eventSource.onerror = () => {
      // 浏览器自动带 Last-Event-ID 重连；不额外处理。
    }
  } catch {
    // 未登录/旧服务：无实时流，轮询通道仍可用。
  } finally {
    streaming.value = false
  }
}

export function useTaskEvents() {
  return { progress, states, subjectIndex, stepsFor, ingest, backfill, backfillSample, ensureStream }
}
