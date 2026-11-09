import type {
  Capabilities,
  Overview,
  PlanRecord,
  RunRow,
  SampleRow,
  TaskEvent,
  TaskRow,
} from './types'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)bacmap_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const method = (init.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    headers.set('X-CSRF-Token', csrfToken())
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: 'same-origin',
  })
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.assign(`/login?next=${next}`)
    throw new ApiError(401, 'unauthorized', '需要登录')
  }
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!response.ok) {
    const record = (body ?? {}) as Record<string, unknown>
    const code = String(record.code ?? 'http_error')
    const message = String(record.error ?? record.detail ?? response.statusText)
    throw new ApiError(response.status, code, message)
  }
  return body as T
}

function json(body: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(body) }
}

export const api = {
  capabilities: () => request<Capabilities>('/capabilities'),
  overview: () => request<Overview>('/overview'),

  listTasks: (limit = 200) =>
    request<{ items: TaskRow[] }>(`/tasks?limit=${limit}`).then((r) => r.items),
  getTask: (id: string) => request<TaskRow>(`/tasks/${encodeURIComponent(id)}`),
  submitTask: (body: {
    task_type: string
    samples: string
    scope: string
  }) => request<TaskRow>('/tasks', json(body)),
  approveTask: (
    id: string,
    body: {
      approver: string
      decision: 'approve' | 'reject'
      signature: string
      comment?: string
    },
  ) => request<TaskRow>(`/tasks/${encodeURIComponent(id)}/approve`, json(body)),
  cancelTask: (id: string) =>
    request<TaskRow>(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),

  listPlans: (limit = 100) =>
    request<{ items: PlanRecord[] }>(`/plans?limit=${limit}`).then((r) => r.items),
  getPlan: (id: string, version?: number) =>
    request<PlanRecord>(
      `/plans/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`,
    ),
  confirmPlan: (id: string, body: { version: number; plan_hash: string; confirmer: string }) =>
    request<PlanRecord>(`/plans/${encodeURIComponent(id)}/confirm`, json(body)),
  rejectPlan: (id: string, body: { version: number; reason: string }) =>
    request<PlanRecord>(`/plans/${encodeURIComponent(id)}/reject`, json(body)),

  listRuns: (limit = 100) =>
    request<{ items: RunRow[] }>(`/runs?limit=${limit}`).then((r) => r.items),
  getRun: (id: string) => request<RunRow>(`/runs/${encodeURIComponent(id)}`),
  compareRuns: (id: string, other: string) =>
    request<Record<string, unknown>>(
      `/runs/${encodeURIComponent(id)}/compare?other=${encodeURIComponent(other)}`,
    ),

  listEvents: (params: { task_id?: string; plan_id?: string; after?: number; limit?: number }) => {
    const q = new URLSearchParams()
    if (params.task_id) q.set('task_id', params.task_id)
    if (params.plan_id) q.set('plan_id', params.plan_id)
    if (params.after) q.set('after', String(params.after))
    q.set('limit', String(params.limit ?? 100))
    return request<{ events: TaskEvent[]; last_seq: number }>(`/events?${q.toString()}`)
  },

  search: (params: {
    q?: string
    serotype?: string
    mlst_st?: string
    amr_gene?: string
  }) => {
    const q = new URLSearchParams()
    if (params.q) q.set('q', params.q)
    if (params.serotype) q.set('serotype', params.serotype)
    if (params.mlst_st) q.set('mlst_st', params.mlst_st)
    if (params.amr_gene) q.set('amr_gene', params.amr_gene)
    return request<{ items: SampleRow[] }>(`/search?${q.toString()}`).then((r) => r.items)
  },

  createRecord: (kind: string, body: Record<string, unknown>) =>
    request<TaskRow>(`/records/${encodeURIComponent(kind)}`, json(body)),
}
