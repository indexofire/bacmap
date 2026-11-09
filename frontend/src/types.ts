export type TaskState =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export type PlanState =
  | 'awaiting_confirmation'
  | 'confirmed'
  | 'submitted'
  | 'rejected'
  | 'superseded'
  | 'failed'

export interface TaskRow {
  task_id: string
  task_type: string
  state: TaskState
  submitted_by: string
  created_at: string
  updated_at: string
  current_step: string | null
  message: string | null
}

export interface TaskEvent {
  seq: number
  event_id: string
  type: string
  occurred_at: string
  actor: string
  task_id?: string | null
  plan_id?: string | null
  data_class?: string
  payload?: Record<string, unknown> | null
}

export interface PlanTask {
  task_type: string
  [key: string]: unknown
}

export interface PlanRecord {
  plan_id: string
  version: number
  state: PlanState
  tasks: PlanTask[]
  inputs: Record<string, string>
  plan_hash: string
  rationale: string
  created_by: string
  created_at: string
  updated_at: string
  confirmed_by: string
  confirmed_at: string
  task_ids: string[]
  message: string
}

export interface RunRow {
  run_id: string
  sample_id?: string
  task_id?: string
  created_at?: string
  [key: string]: unknown
}

export interface Overview {
  endpoints: Array<{
    name: string
    location: string
    base_url: string
    model: string
    enabled: boolean
  }>
  routing: Record<string, unknown>
  cloud_max_data_class: string
  versions: Record<string, string>
  paths: Record<string, string>
  sandbox: string
  task_counts: Record<string, number>
}

export interface SampleRow {
  sample_id: string
  verdict: string
  st: string
  serovar: string
  n_card: number
  n_vfdb: number
  n_plasmid: number
  ipaH: string
  pathotype: string
  card_genes: string[]
  vfdb_genes: string[]
  plasmids: string[]
}

export interface Capabilities {
  api_version: string
  bacmap_version: string
  plannable_task_types: string[]
  features: string[]
}
