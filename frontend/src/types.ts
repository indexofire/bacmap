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
  strain_ids: string[]
  started_at: string
  finished_at?: string | null
  workflow?: string
  baseline_version?: string
  task_id?: string
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

export interface SampleDetail {
  digest: SampleRow & { has_report: boolean }
  steps: Record<string, unknown>
  summary: Record<string, unknown>
}

export interface GomObject {
  object_id: string
  object_type: string
  version: number
  strain_id?: string
  created_at: string
  payload_keys?: string[]
  payload?: Record<string, unknown>
  [key: string]: unknown
}

export interface ResearchSession {
  session_id: string
  run_id: string
  gene: string
  test_name: string
  profile: string
  status: string
  data_class: number
  created_by: string
  created_at: string
  updated_at: string
  label: string
  study_id: string
  cohort_id: string
  plan_id: string
  note: string
  [key: string]: unknown
}

export interface ResearchStat {
  session_id: string
  table: Record<string, number>
  odds_ratio: number | null
  ci_low: number | null
  ci_high: number | null
  p_value: number | null
  n: number
  diagnostics: string[]
  [key: string]: unknown
}

export interface ResearchArtifact {
  session_id: string
  kind: string
  path: string
  sha256: string
  created_at: string
}

export interface ResearchSessionView {
  session: ResearchSession
  stat: ResearchStat | null
  artifacts: ResearchArtifact[]
}

export interface ResearchStudy {
  study_id: string
  question: string
  pathogen_scope: string
  data_class: number
  status: string
  [key: string]: unknown
}

export interface ResearchCohort {
  cohort_id: string
  study_id: string
  name?: string
  status: string
  n_members?: number
  [key: string]: unknown
}

export interface ResearchPlan {
  plan_id: string
  study_id: string
  status: string
  [key: string]: unknown
}

export interface ResearchClaim {
  claim_id: string
  study_id: string
  claim_type: string
  evidence_level: string
  status: string
  wording: string
  [key: string]: unknown
}

export interface ResearchLedgerEntry {
  seq?: number
  object_type?: string
  object_id?: string
  action?: string
  actor?: string
  created_at?: string
  event?: string
  at?: string
  payload_json?: string
  [key: string]: unknown
}

export interface Capabilities {
  api_version: string
  bacmap_version: string
  plannable_task_types: string[]
  features: string[]
}

export interface CountItem {
  name: string
  count: number
}

export interface DatabaseStats {
  schema: string
  home: string
  tasks: {
    total: number
    by_state: Record<string, number>
    plans: number
    [key: string]: unknown
  }
  runs: { total: number; [key: string]: unknown }
  gom: { genome_objects: number; isolates: number; amr_genes: number; [key: string]: unknown }
  strains: {
    total: number
    species: CountItem[]
    serotypes: CountItem[]
    mlst: CountItem[]
    amr_top: CountItem[]
  }
  lab_results: { total: number; strains: number; [key: string]: unknown }
  knowledge: { entries: number; [key: string]: unknown }
  research: {
    sessions: number
    studies: number
    cohorts: number
    claims: number
    requests: number
    analyses: number
    advstats_results: number
    [key: string]: unknown
  }
  results: { sample_reports: number; [key: string]: unknown }
}
