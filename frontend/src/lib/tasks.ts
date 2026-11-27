import { api } from '../api'
import type { TaskRow } from '../types'

const TERMINAL = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'awaiting_approval',
])

export async function waitForTask(taskId: string): Promise<TaskRow> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const task = await api.getTask(taskId)
    if (TERMINAL.has(String(task.state))) return task
    await new Promise((resolve) => window.setTimeout(resolve, 250))
  }
  throw new Error('记录任务仍在运行，请稍后刷新')
}

export function requireSucceeded(task: TaskRow): TaskRow {
  if (String(task.state) !== 'succeeded') {
    throw new Error(task.message || `记录任务 ${task.state}`)
  }
  return task
}
