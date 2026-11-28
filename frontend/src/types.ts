export type TaskState =
  | 'pending'
  | 'running'
  | 'paused'
  | 'awaiting_approval'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export interface AuthStatus {
  enabled: boolean
  mode: 'cookie' | 'bearer' | 'accounts' | 'personal' | 'disabled'
  authenticated: boolean
  operator: string
  login_url: string
  role?: 'admin' | 'analyst' | 'user' | ''
  username?: string
  display_name?: string
  accounts_ready?: boolean
  personal_ready?: boolean
  permissions?: string[]
}

export interface WetlabWriteResult {
  task_id: string
  kind: string
  task: TaskRow
}

export interface MappingAdvice {
  job_id: string
  endpoint: string
  location: string
  data_class: string
  included_values: boolean
  columns: Array<{
    layer: string
    source_column: string
    suggested_field: string
    action: 'map' | 'keep_extra' | 'ignore'
    confidence: 'high' | 'medium' | 'low'
    reason: string
  }>
  warnings: string[]
  notes: string
}

export interface ImportJob {
  job_id: string
  kind?: 'import' | 'edit'
  target_type?: string
  target_id?: string
  base_version?: string
  payload?: Array<Record<string, unknown>>
  filename: string
  status: 'pending_review' | 'submitted' | 'rejected' | 'withdrawn'
  created_by: string
  created_at: string
  updated_at: string
  reviewed_by?: string
  reviewed_at?: string
  review_note?: string
  task_id?: string
  sheet_args?: Record<string, string>
  summary?: {
    operation?: string
    target_type?: string
    target_id?: string
    isolate_rows?: number
    specimen_rows?: number
    library_rows?: number
    lab_rows?: number
    isolates?: string[]
    specimens?: string[]
    libraries?: string[]
    isolate_fields?: string[]
    specimen_fields?: string[]
    library_fields?: string[]
    lab_fields?: string[]
  }
  errors?: string[]
}

export interface UserRow {
  user_id: string
  username: string
  role: 'admin' | 'analyst' | 'user'
  display_name: string
  disabled: boolean
  created_at: string
  updated_at: string
}

export interface SpeciesSummary {
  species: string
  n_samples: number
  n_specimens: number
  n_isolates: number
  last_analysis: string
  n_with_metrics: number
}

export interface ContigBin {
  label: string
  count: number
  bp: number
}

export interface NxPoint {
  x: number
  length: number
}

export interface TopContig {
  name: string
  length: number
  gc: number | null
}

export interface AssemblyContigStats {
  source: string
  count: number
  total_length: number
  largest: number
  n50: number
  l50: number
  n75: number
  l75: number
  n90: number
  l90: number
  gc_mean: number | null
  length_bins: ContigBin[]
  gc_bins: ContigBin[]
  nx: NxPoint[]
  top_contigs: TopContig[]
}

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

export interface GvixbLink {
  id: string
  kind: 'genome' | 'circle' | 'tree' | 'mst'
  label: string
  context: string
  url: string
  data_url: string
}

export interface RunRow {
  run_id: string
  strain_ids: string[]
  started_at: string
  finished_at?: string | null
  workflow?: string
  baseline_version?: string
  task_id?: string
  gvixb_views?: GvixbLink[]
  [key: string]: unknown
}

export interface RunPurgeResult {
  run_id: string
  task_id: string
  purged: boolean
  dry_run: boolean
  files: number
  bytes: number
  latest_links: string[]
  already_purged: boolean
  purged_at?: string | null
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
  genome_size: number | null
  contigs: number | null
  gc_pct: number | null
  st: string
  serovar: string
  n_card: number
  n_vfdb: number
  n_plasmid: number
  ipaH?: string
  pathotype?: string
  card_genes: string[]
  vfdb_genes: string[]
  plasmids: string[]
  specimen_id?: string
  isolate_id?: string
  owner_user_id?: string
  analysis_date?: string
  prelim?: boolean
}

export interface SampleDetail {
  digest: SampleRow & { has_report: boolean; has_prelim_report?: boolean; prelim?: boolean }
  steps: Record<string, unknown>
  summary: Record<string, unknown>
  gvixb?: GvixbLink[]
}

export interface LibraryRow {
  library_id: string
  sample?: string
  isolate?: string
  specimen?: string
  species?: string
  platform?: string
  metadata?: Record<string, unknown>
  metadata_specimen_id?: string
  metadata_isolate_id?: string
  [key: string]: unknown
}

export interface IsolateRow {
  isolate_id: string
  specimen_id?: string | null
  lineage_id?: string | null
  passage?: number | null
  n_libraries?: number
  libraries?: LibraryRow[]
  owner_user_id?: string | null
  species?: string
  sts?: string[]
  serotypes?: string[]
  n_results?: number
  last_analysis?: string
  [key: string]: unknown
}

export interface SpecimenRow {
  specimen_id: string
  origin?: string
  note?: string
  n_isolates?: number
  owner_user_id?: string | null
  species?: string
  n_results?: number
  last_analysis?: string
  [key: string]: unknown
}

export interface SpecimenDetail {
  specimen: SpecimenRow
  isolates: IsolateRow[]
  libraries?: LibraryRow[]
  metadata?: Record<string, unknown> | null
  lab_results?: LabResultRow[]
}

export interface LabResultRow {
  id: string
  strain_id: string
  subject_type?: string
  subject_id?: string
  category: string
  test_name: string
  result: string
  unit?: string
  method?: string
  interpretation?: string
  tested_date?: string
  lab?: string
  notes?: string
  [key: string]: unknown
}

export interface IsolateDetail {
  isolate: IsolateRow
  specimen: SpecimenRow | null
  libraries: LibraryRow[]
  metadata: Record<string, unknown> | null
  lab_results: LabResultRow[]
}

export interface GomObject {
  object_id: string
  object_type: string
  version: number
  strain_id?: string
  created_at: string
  payload_keys?: string[]
  payload?: Record<string, unknown>
  gvixb_views?: GvixbLink[]
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

export interface AgentEmbedLink {
  name: string
  url: string
}

export interface Capabilities {
  api_version: string
  bacmap_version: string
  plannable_task_types: string[]
  features: string[]
  agent_embeds?: AgentEmbedLink[]
  chat?: ChatCapabilities
}

export interface CountItem {
  name: string
  count: number
}

export interface SpeciesBreakdown {
  name: string
  count: number
  mlst: CountItem[]
  serotypes: CountItem[]
  amr_top: CountItem[]
  virulence_top: CountItem[]
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
    registered?: number
    species: CountItem[]
    serotypes: CountItem[]
    mlst: CountItem[]
    amr_top: CountItem[]
    by_species?: SpeciesBreakdown[]
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

export interface DagRun {
  task_id: string
  dag_hash: string
  state: string
  data_class: number
  created_at: string
  updated_at: string
}

export interface DagNodeRow {
  task_id: string
  node_id: string
  op: string
  state: string
  cache_hit: number
  outputs_json: string
  error: string
  started_at: string
  finished_at: string
}

export interface DagArtifactRow {
  artifact_id: string
  type: string
  sha256: string
  path: string
  producer_task: string
  producer_node: string
  data_class: number
  size_bytes: number
  created_at: string
}

export interface DagView {
  run: DagRun | null
  nodes: DagNodeRow[]
  artifacts: DagArtifactRow[]
}

export interface DagArtifactPayload {
  artifact_id: string
  type: string
  value: unknown
}

// ---- Web 控制台对话（P1，AG-UI） ------------------------------------------------

export interface ChatBackendInfo {
  id: string
  name: string
  kind: 'builtin' | 'external'
  protocol: string
  available: boolean
  reason: string
}

export interface ChatCapabilities {
  enabled: boolean
  mode: 'off' | 'builtin' | 'external' | 'both'
  default_backend: string
  backends: ChatBackendInfo[]
  can_confirm_plans: boolean
}

export interface ChatPageContext {
  route: string
  entity_type: string
  entity_id: string
  title: string
}

export interface ChatSession {
  session_id: string
  owner_user_id: string
  title: string
  backend_id: string
  linked_tasks: string[]
  created_at: string
  updated_at: string
}

export interface ChatToolCall {
  id: string
  name: string
  args: string
  result: string
  done?: boolean
}

export interface ChatPlanCard {
  kind: 'bacmap.plan_card'
  plan_id: string
  version: number
  state: string
  plan_hash: string
  short_hash: string
  rationale: string
  tasks: Array<Record<string, unknown>>
  task_ids: string[]
  created_by: string
  can_confirm?: boolean
}

export interface ChatTaskRefCard {
  kind: 'bacmap.task_ref'
  task_id: string
  state?: string
  plan_id?: string
}

export type ChatCard = ChatPlanCard | ChatTaskRefCard | ({ kind: string } & Record<string, unknown>)

export interface ChatMessage {
  message_id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  thinking: string
  tool_calls: ChatToolCall[]
  cards: ChatCard[]
  backend_id: string
  created_at: string
  streaming?: boolean
}

// AG-UI v0.1 wire events（camelCase 与后端 agui.py 一致）
export type AgUiEvent =
  | { type: 'RUN_STARTED'; threadId: string; runId: string; timestamp?: number }
  | { type: 'RUN_FINISHED'; threadId: string; runId: string; result?: unknown; timestamp?: number }
  | { type: 'RUN_ERROR'; message: string; code?: string; timestamp?: number }
  | { type: 'THINKING_START'; title?: string; timestamp?: number }
  | { type: 'THINKING_TEXT_MESSAGE_START'; timestamp?: number }
  | { type: 'THINKING_TEXT_MESSAGE_CONTENT'; delta: string; timestamp?: number }
  | { type: 'THINKING_TEXT_MESSAGE_END'; timestamp?: number }
  | { type: 'THINKING_END'; timestamp?: number }
  | { type: 'TEXT_MESSAGE_START'; messageId: string; role?: string; timestamp?: number }
  | { type: 'TEXT_MESSAGE_CONTENT'; messageId: string; delta: string; timestamp?: number }
  | { type: 'TEXT_MESSAGE_END'; messageId: string; timestamp?: number }
  | {
      type: 'TOOL_CALL_START'
      toolCallId: string
      toolCallName: string
      parentMessageId?: string
      timestamp?: number
    }
  | { type: 'TOOL_CALL_ARGS'; toolCallId: string; delta: string; timestamp?: number }
  | { type: 'TOOL_CALL_END'; toolCallId: string; timestamp?: number }
  | {
      type: 'TOOL_CALL_RESULT'
      messageId: string
      toolCallId: string
      content: string
      role?: string
      timestamp?: number
    }
  | { type: 'STATE_SNAPSHOT'; snapshot: Record<string, unknown>; timestamp?: number }
  | { type: 'STATE_DELTA'; delta: Array<Record<string, unknown>>; timestamp?: number }
  | { type: 'CUSTOM'; name: string; value: unknown; timestamp?: number }
