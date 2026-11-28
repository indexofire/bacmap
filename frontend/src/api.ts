import { appUrl } from './lib/format'
import type {
  AuthStatus,
  Capabilities,
  Page,
  DatabaseStats,
  GomObject,
  IsolateDetail,
  IsolateRow,
  Overview,
  PlanRecord,
  DagArtifactPayload,
  DagView,
  ResearchClaim,
  ResearchCohort,
  ResearchLedgerEntry,
  ResearchPlan,
  ResearchSession,
  ResearchSessionView,
  ResearchStudy,
  RunRow,
  RunPurgeResult,
  SampleDetail,
  SampleRow,
  SpeciesSummary,
  SpecimenDetail,
  SpecimenRow,
  TaskEvent,
  TaskRow,
  ImportJob,
  MappingAdvice,
  WetlabWriteResult,
  UserRow,
  ChatCapabilities,
  ChatSession,
  ChatMessage,
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

export function csrfToken(): string {
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
  const response = await fetch(appUrl(`/api/v1${path}`), {
    ...init,
    headers,
    credentials: 'same-origin',
  })
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.assign(appUrl(`/console/login?next=${next}`))
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
  authStatus: () => request<AuthStatus>('/auth/status'),
  login: (token: string, next = '/console/') =>
    request<{ ok: boolean; next: string }>('/auth/login', json({ token, next })),
  loginAccount: (username: string, password: string, next = '/console/') =>
    request<{ ok: boolean; next: string }>(
      '/auth/login',
      json({ username, password, next }),
    ),
  logout: () => request<{ ok: boolean }>('/auth/logout', json({})),

  createSpecimen: (payload: {
    specimen_id: string
    origin?: string
    note?: string
  }) => request<WetlabWriteResult>('/wetlab/specimens', json(payload)),
  createIsolate: (payload: {
    isolate_id: string
    specimen_id?: string
    lineage_id?: string | null
    passage?: number | null
  }) => request<WetlabWriteResult>('/wetlab/isolates', json(payload)),
  saveSpecimenMetadata: (id: string, data: Record<string, unknown>, replace = true) =>
    request<WetlabWriteResult>(
      `/wetlab/specimens/${encodeURIComponent(id)}/metadata`,
      json({ data, replace }),
    ),
  assignSpecimenTask: (id: string, isolates: string[], datasets: string[]) =>
    request<WetlabWriteResult>(
      `/wetlab/specimens/${encodeURIComponent(id)}/assign`,
      json({ isolates, datasets }),
    ),
  deleteSpecimenMetadata: (id: string) =>
    request<WetlabWriteResult>(
      `/wetlab/specimens/${encodeURIComponent(id)}/metadata/delete`,
      json({}),
    ),
  saveIsolateMetadata: (
    id: string,
    data: Record<string, unknown>,
    sampleId = '',
    replace = true,
  ) =>
    request<WetlabWriteResult>(
      `/wetlab/isolates/${encodeURIComponent(id)}/metadata`,
      json({ data, sample_id: sampleId, replace }),
    ),
  deleteIsolateMetadata: (id: string) =>
    request<WetlabWriteResult>(
      `/wetlab/isolates/${encodeURIComponent(id)}/metadata/delete`,
      json({}),
    ),
  saveLibraryMetadata: (id: string, data: Record<string, unknown>, replace = true) =>
    request<WetlabWriteResult>(
      `/wetlab/libraries/${encodeURIComponent(id)}/metadata`,
      json({ data, replace }),
    ),
  deleteLibraryMetadata: (id: string) =>
    request<WetlabWriteResult>(
      `/wetlab/libraries/${encodeURIComponent(id)}/metadata/delete`,
      json({}),
    ),
  addLabResult: (payload: Record<string, unknown>) =>
    request<WetlabWriteResult>('/wetlab/lab', json(payload)),
  updateLabResult: (id: string, payload: Record<string, unknown>) =>
    request<WetlabWriteResult>(
      `/wetlab/lab/${encodeURIComponent(id)}`,
      json(payload),
    ),
  deleteLabResult: (id: string) =>
    request<WetlabWriteResult>(
      `/wetlab/lab/${encodeURIComponent(id)}/delete`,
      json({}),
    ),

  listImports: (offset = 0, limit = 50, status = '', kind = '') => {
    const q = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (status) q.set('status', status)
    if (kind) q.set('kind', kind)
    return request<Page<ImportJob>>(`/imports?${q.toString()}`)
  },
  getImport: (id: string) => request<ImportJob>(`/imports/${encodeURIComponent(id)}`),
  proposeWetlab: (params: Record<string, unknown>) =>
    request<ImportJob>('/wetlab/proposals', json({ params })),
  adviseImport: (id: string) =>
    request<MappingAdvice>(`/imports/${encodeURIComponent(id)}/advise`, json({})),
  previewImport: (id: string, limit = 20) =>
    request<{
      summary: ImportJob['summary']
      errors: string[]
      total?: number
      limit?: number
      rows: Array<Record<string, unknown>>
    }>(`/imports/${encodeURIComponent(id)}/preview?limit=${limit}`),
  uploadImport: async (file: File, fields: Record<string, string> = {}) => {
    const body = new FormData()
    body.append('file', file)
    for (const [key, value] of Object.entries(fields)) {
      if (value) body.append(key, value)
    }
    const response = await fetch(appUrl('/api/v1/imports'), {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken(), Accept: 'application/json' },
      body,
      credentials: 'same-origin',
    })
    if (response.status === 401) {
      window.location.assign(appUrl('/console/login'))
      throw new ApiError(401, 'unauthorized', '需要登录')
    }
    const text = await response.text()
    let parsed: unknown = null
    try {
      parsed = text ? JSON.parse(text) : null
    } catch {
      parsed = text
    }
    if (!response.ok) {
      const record = (parsed ?? {}) as Record<string, unknown>
      const details = Array.isArray(record.details) ? `：${record.details.join('；')}` : ''
      throw new ApiError(
        response.status,
        String(record.code ?? 'http_error'),
        String(record.error ?? record.detail ?? '上传失败') + details,
      )
    }
    return parsed as ImportJob
  },
  approveImport: (id: string, force = false) =>
    request<ImportJob>(
      `/imports/${encodeURIComponent(id)}/approve${force ? '?force_self_approval=true' : ''}`,
      json({}),
    ),
  rejectImport: (id: string, note = '') =>
    request<ImportJob>(
      `/imports/${encodeURIComponent(id)}/reject?note=${encodeURIComponent(note)}`,
      json({}),
    ),
  withdrawImport: (id: string) =>
    request<ImportJob>(`/imports/${encodeURIComponent(id)}/withdraw`, json({})),

  listUsers: () =>
    request<{ items: UserRow[] }>('/users').then((r) => r.items),
  createUser: (body: {
    username: string
    password: string
    role: UserRow['role']
    display_name?: string
  }) => request<UserRow>('/users', json(body)),
  setUserRole: (id: string, role: UserRow['role']) =>
    request<UserRow>(`/users/${encodeURIComponent(id)}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    }),
  setUserDisabled: (id: string, disabled: boolean) =>
    request<UserRow>(`/users/${encodeURIComponent(id)}/disabled`, {
      method: 'PATCH',
      body: JSON.stringify({ disabled }),
    }),
  resetUserPassword: (id: string, password: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(id)}/password`, json({ password })),
  listUserTokens: (id: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      `/users/${encodeURIComponent(id)}/tokens`,
    ).then((r) => r.items),
  createUserToken: (id: string, name: string, expiresDays = 0) =>
    request<{ token: string; warning: string }>(
      `/users/${encodeURIComponent(id)}/tokens`,
      json({ name, expires_days: expiresDays }),
    ),
  revokeUserToken: (id: string, tokenId: string) =>
    request<{ ok: boolean }>(
      `/users/${encodeURIComponent(id)}/tokens/${encodeURIComponent(tokenId)}`,
      { method: 'DELETE' },
    ).then(() => undefined),

  capabilities: () => request<Capabilities>('/capabilities'),

  chatConfig: () => request<ChatCapabilities>('/chat/config'),
  listChatSessions: (limit = 50, offset = 0) =>
    request<{ items: ChatSession[] }>(`/chat/sessions?limit=${limit}&offset=${offset}`),
  createChatSession: (payload: { title?: string; backend_id?: string } = {}) =>
    request<ChatSession>('/chat/sessions', json(payload)),
  getChatSession: (id: string) =>
    request<{ session: ChatSession; messages: ChatMessage[] }>(
      `/chat/sessions/${encodeURIComponent(id)}`,
    ),
  updateChatSession: (id: string, payload: { title?: string; backend_id?: string }) =>
    request<ChatSession>(`/chat/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteChatSession: (id: string) =>
    request<{ deleted: boolean; session_id: string }>(
      `/chat/sessions/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),
  overview: () => request<Overview>('/overview'),
  stats: () => request<DatabaseStats>('/stats'),

  listTasks: (limit = 200) =>
    request<{ items: TaskRow[] }>(`/tasks?limit=${limit}`).then((r) => r.items),
  taskPage: (offset = 0, limit = 50, taskType = '') => {
    const q = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (taskType) q.set('task_type', taskType)
    return request<Page<TaskRow>>(`/tasks?${q.toString()}`)
  },
  recordPage: (offset = 0, limit = 50) =>
    request<Page<TaskRow>>(`/records?offset=${offset}&limit=${limit}`),
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
  pauseTask: (id: string) =>
    request<TaskRow>(`/tasks/${encodeURIComponent(id)}/pause`, { method: 'POST' }),
  resumeTask: (id: string) =>
    request<TaskRow>(`/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' }),

  researchDag: (id: string) =>
    request<DagView>(`/research/dag/${encodeURIComponent(id)}`),
  researchDagArtifact: (id: string, artifactId: string) =>
    request<DagArtifactPayload>(
      `/research/dag/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}`,
    ),

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
  runsPage: (offset = 0, limit = 50) =>
    request<Page<RunRow>>(`/runs?offset=${offset}&limit=${limit}`),
  getRun: (id: string) => request<RunRow>(`/runs/${encodeURIComponent(id)}`),
  purgeRun: (id: string, dryRun = false) =>
    request<RunPurgeResult>(
      `/runs/${encodeURIComponent(id)}/purge${dryRun ? '?dry_run=true' : ''}`,
      json({}),
    ),
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
    return request<{ events: TaskEvent[]; last_seq: number; max_seq: number }>(
      `/events?${q.toString()}`,
    )
  },

  searchPage: (params: {
    q?: string
    serotype?: string
    mlst_st?: string
    amr_gene?: string
    offset?: number
    limit?: number
  }) => {
    const q = new URLSearchParams()
    if (params.q) q.set('q', params.q)
    if (params.serotype) q.set('serotype', params.serotype)
    if (params.mlst_st) q.set('mlst_st', params.mlst_st)
    if (params.amr_gene) q.set('amr_gene', params.amr_gene)
    q.set('offset', String(params.offset ?? 0))
    q.set('limit', String(params.limit ?? 50))
    return request<Page<SampleRow>>(`/search?${q.toString()}`)
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

  listSamples: (cursor?: string, limit = 50) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (cursor) q.set('cursor', cursor)
    return request<{ items: SampleRow[]; next_cursor: string | null }>(
      `/samples?${q.toString()}`,
    )
  },
  getSample: (id: string) => request<SampleDetail>(`/samples/${encodeURIComponent(id)}`),
  samplesPage: (
    params: {
      offset?: number
      limit?: number
      sort?: string
      order?: 'asc' | 'desc'
      q?: string
      species?: string
      serotype?: string
      mlst_st?: string
      amr_gene?: string
    } = {},
  ) => {
    const q = new URLSearchParams({
      offset: String(params.offset ?? 0),
      limit: String(params.limit ?? 50),
      sort: params.sort ?? 'sample_id',
      order: params.order ?? 'asc',
    })
    if (params.q) q.set('q', params.q)
    if (params.species) q.set('species', params.species)
    if (params.serotype) q.set('serotype', params.serotype)
    if (params.mlst_st) q.set('mlst_st', params.mlst_st)
    if (params.amr_gene) q.set('amr_gene', params.amr_gene)
    return request<Page<SampleRow> & { next_cursor: string | null; indexed?: boolean }>(
      `/samples?${q.toString()}`,
    )
  },
  speciesSummary: () =>
    request<{ items: SpeciesSummary[]; indexed: boolean }>('/species'),

  listSpecimens: (limit = 200) =>
    request<{ items: SpecimenRow[] }>(`/specimens?limit=${limit}`).then((r) => r.items),
  specimensPage: (offset = 0, limit = 50, q = '') => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (q) params.set('q', q)
    return request<Page<SpecimenRow>>(`/specimens?${params.toString()}`)
  },
  getSpecimen: (id: string) =>
    request<SpecimenDetail>(`/specimens/${encodeURIComponent(id)}`),
  searchIdentity: (q: string) =>
    request<{ specimens: SpecimenRow[]; isolates: IsolateRow[] }>(
      `/search/identity?${new URLSearchParams({ q }).toString()}`,
    ),
  searchIdentityPage: (params: {
    q: string
    specimen_offset?: number
    specimen_limit?: number
    isolate_offset?: number
    isolate_limit?: number
  }) => {
    const q = new URLSearchParams({ q: params.q })
    q.set('specimen_offset', String(params.specimen_offset ?? 0))
    q.set('specimen_limit', String(params.specimen_limit ?? 25))
    q.set('isolate_offset', String(params.isolate_offset ?? 0))
    q.set('isolate_limit', String(params.isolate_limit ?? 25))
    return request<{
      specimens: SpecimenRow[]
      isolates: IsolateRow[]
      specimen_total: number
      isolate_total: number
    }>(`/search/identity?${q.toString()}`)
  },
  assignSpecimen: (body: {
    specimen_id: string
    isolates?: string[]
    datasets?: string[]
  }) =>
    request<{ specimen_id: string; updated: number; missing: string[] }>(
      '/specimens/assign',
      json(body),
    ),
  deleteSpecimen: (id: string, force = false) =>
    request<{
      specimen_id: string
      deleted: boolean
      unlinked_isolates: number
      updated_tsv_rows: number
    }>(`/specimens/${encodeURIComponent(id)}/delete`, json({ force })),
  listIsolates: (limit = 500) =>
    request<{ items: IsolateRow[] }>(`/isolates?limit=${limit}`).then((r) => r.items),
  isolatesPage: (offset = 0, limit = 50, q = '') => {
    const params = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
    })
    if (q) params.set('q', q)
    return request<Page<IsolateRow>>(`/isolates?${params.toString()}`)
  },
  getIsolate: (id: string) => request<IsolateDetail>(`/isolates/${encodeURIComponent(id)}`),
  deleteIsolate: (id: string) =>
    request<{ deleted: boolean; isolate_id: string }>(
      `/isolates/${encodeURIComponent(id)}/delete`,
      json({}),
    ),

  listGom: (type?: string, limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (type) q.set('type', type)
    return request<{ items: GomObject[] }>(`/gom/objects?${q.toString()}`).then((r) => r.items)
  },
  gomPage: (type: string, offset = 0, limit = 50) => {
    const q = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (type) q.set('type', type)
    return request<Page<GomObject>>(`/gom/objects?${q.toString()}`)
  },
  getGom: (id: string, version?: number) =>
    request<GomObject>(
      `/gom/objects/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`,
    ),

  listResearchSessions: (limit = 50) =>
    request<{ items: ResearchSession[] }>(`/research/sessions?limit=${limit}`).then((r) => r.items),
  createResearchSession: (body: {
    run_id: string
    gene: string
    test_name: string
    profile?: string
    study_id?: string
    cohort_id?: string
    plan_id?: string
    note?: string
  }) => request<ResearchSessionView>('/research/sessions', json(body)),
  getResearchSession: (id: string) =>
    request<ResearchSessionView>(`/research/sessions/${encodeURIComponent(id)}`),
  getResearchLedger: (id: string) =>
    request<{ items: ResearchLedgerEntry[] }>(
      `/research/sessions/${encodeURIComponent(id)}/ledger`,
    ).then((r) => r.items),
  listResearchStudies: (limit = 50) =>
    request<{ items: ResearchStudy[] }>(`/research/studies?limit=${limit}`).then((r) => r.items),
  getResearchStudy: (id: string) =>
    request<ResearchStudy>(`/research/studies/${encodeURIComponent(id)}`),
  listResearchCohorts: (studyId?: string, limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (studyId) q.set('study_id', studyId)
    return request<{ items: ResearchCohort[] }>(`/research/cohorts?${q.toString()}`).then(
      (r) => r.items,
    )
  },
  listResearchPlans: (studyId?: string, limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (studyId) q.set('study_id', studyId)
    return request<{ items: ResearchPlan[] }>(`/research/plans?${q.toString()}`).then(
      (r) => r.items,
    )
  },
  listResearchClaims: (studyId?: string, limit = 100) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (studyId) q.set('study_id', studyId)
    return request<{ items: ResearchClaim[] }>(`/research/claims?${q.toString()}`).then(
      (r) => r.items,
    )
  },
}
