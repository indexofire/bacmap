# MCP reference

bacmap runs an MCP server with stdio (default) or Streamable HTTP. Clients launch the process and
receive tools, prompts and resources. Conversation and model choice are the client's concern;
bacmap exposes domain tools and a human confirmation boundary.

## 1. Transports and authentication

| Transport | Command | Auth |
|---|---|---|
| stdio | `bacmap start mcp` | OS process boundary; actor `mcp-stdio:<profile>:<user>` |
| HTTP | `bacmap start mcp --transport http --host 127.0.0.1 --port 8765` | mandatory bearer token |
| unix socket | `bacmap start mcp --transport http --uds /run/bacmap-mcp.sock` | mandatory bearer token |

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
# client: http://127.0.0.1:8765/mcp, Authorization: Bearer <token>
```

HTTP refuses to start without a token. DNS-rebinding protection only allows configured hosts
(loopback by default).

`--read-only` removes task/plan/record write tools; only read/compute and capabilities remain.

## 2. Profiles

One profile per server instance, fixed at launch:

```bash
bacmap start mcp                          # cloud (default)
bacmap start mcp --profile local-trusted  # requires [mcp] allow_local_trusted = true
```

| Profile | Tool output ceiling | Task message | Task result |
|---|---|---|---|
| `cloud` | `[llm.data_policy].cloud_max_data_class` (D1 default, max D2) | withheld | gate counts |
| `local-trusted` | D4 | full | per-sample verdicts |

The client cannot escalate. Use two instances (different ports/tokens) if needed.

## 3. Tools

Exact visibility depends on the profile; `bacmap_capabilities` reports the effective ceiling and
plannable types.

### 3.1 Capabilities

```json
// bacmap_capabilities → (abridged)
{
  "server": "bacmap",
  "bacmap_version": "0.1.2",
  "api": "mcp",
  "profile": "cloud",
  "max_data_class": "D1",
  "plannable_task_types": ["analyze", "curate", "mine", "write"],
  "recommended_write_path": "bacmap_create_plan -> user confirms in bacmap CLI/Web -> bacmap_get_plan -> bacmap_task_status",
  "long_running": "explicit task handles (bacmap_task_status polling)",
  "tasks_extension": "unsupported_by_sdk"
}
```

### 3.2 Plans

| Tool | Arguments | Returns |
|---|---|---|
| `bacmap_create_plan` | `tasks: PlannableTask[]`, `rationale?: string` | plan with `plan_id`, `version`, `state`, `plan_hash`, `confirm_url`, `next_step` |
| `bacmap_revise_plan` | `plan_id`, `tasks`, `rationale?` | new version; old version superseded |
| `bacmap_get_plan` | `plan_id`, `version?` | plan state, tasks, hash, `task_ids` |
| `bacmap_confirm_plan_locally` | `plan_id`, `version` | opens a local dialog (stdio only); the click is the confirmation |

Task shapes:

```json
{"task_type":"analyze","samples":["SAM-001"]}
{"task_type":"analyze","fasta_dir":"/abs/dir","species":"VPA"}
{"task_type":"analyze","fastq_dir":"/abs/dir","species":"SAL"}
{"task_type":"curate","scope":{"pathogen":"Salmonella"}}
{"task_type":"mine","objective":"...","script":"...","input_paths":["/abs/data"],"input_data_class":"D3","sandbox_image":"docker://python:3.12-slim"}
{"task_type":"write","objective":"...","draft":"...","known_citations":[]}
```

Rules:

- `analyze` needs exactly one of `samples`/`fasta_dir`/`fastq_dir`;
- directory paths must be absolute; `mine.input_paths` must be absolute;
- a plan holds at most 10 tasks;
- `mine.script` ≤20k characters; `write.draft` ≤40k;
- read/revise is limited to the creating client;
- the model cannot confirm; by default `confirm_url` points to the Web plan page. With an explicit `[plans.auto_confirm]` policy the server may confirm automatically.

### 3.3 Tasks

| Tool | Arguments | Notes |
|---|---|---|
| `bacmap_submit_task` | `task_type` (`analyze`/`curate`), `samples?`, `scope?` | compatibility direct submission; no `submitted_by` (server decides) |
| `bacmap_task_status` | `task_id` | state, step, message (redacted under cloud), failure block |
| `bacmap_task_result` | `task_id` | `finished`, `run_id`, gates/counts |
| `bacmap_task_cancel` | `task_id` | only tasks this client submitted or its own plan |

```json
// bacmap_task_status → (cloud, failed)
{
  "task_id": "3f9c...",
  "state": "failed",
  "current_step": "pipeline",
  "message": "",
  "message_withheld": true,
  "failure": {
    "kind": "sandbox_unavailable",
    "suggested_fix": "安装 Apptainer 或 Podman 后重试；直通模式仅用于受控开发",
    "recovery_commands": ["pixi global install podman"]
  }
}
```

### 3.4 Records (`local-trusted` only)

`bacmap_record_data` submits a `record` task. Arguments:

```json
{"kind":"metadata","strain_id":"HZCPE-01","sample_id":"HZCPE-01",
 "fields":{"isolation_date":"2026-10-12","province":"Guangdong","sample_source":"food"}}

{"kind":"lab_result","strain_id":"HZCPE-01","category":"mic",
 "test_name":"meropenem","result":"0.25","unit":"mg/L","interpretation":"S"}

{"kind":"knowledge_import","title":"Paper","identifier":"PMID:12345678","entry_kind":"literature"}

{"kind":"knowledge_approve","entry_id":7}
```

The call returns `{"task_id": "...", "kind": "...", "state": "running"}`. Follow it with
`bacmap_task_status`.

### 3.5 Research Workbench (P1)

| Tool | Arguments | Notes |
|---|---|---|
| `bacmap_research_capabilities` | none | P1 capabilities; available on every profile |
| `bacmap_research_sessions` | `limit?` | D2; only if the profile allows D2 |
| `bacmap_research_session` | `session_id` | D2; stat table, diagnostics and artifact paths |
| `bacmap_research_figure_spec` | `session_id` | D2; exact figure contract (data, statistics, source IDs, style) |
| `bacmap_research_figure_recipes` | `executable_only?` | D2; versioned figure recipes and their status |
| `bacmap_research_phylo_profile` | `alignment`, `dates_file?` | D3; local-trusted only; alignment summary |
| `bacmap_research_phylo_plan` | `alignment`, `goal?`, `dates_file?` | D3; local-trusted only; typed ML/BEAST2 plan |
| `bacmap_research_logistic` | `data_path`, `outcome`, `predictors` | D3; local-trusted only; multivariable logistic regression |
| `bacmap_research_power` | `p1?`, `p2?`, `baseline?`, `odds_ratio?`, `n1?`, `n2?`, `alpha?`, `power?`, `ratio?`, `session_id?` | D2; a priori sample size / achieved power for two proportions |
| `bacmap_research_reporting_checklist` | `study_id` | D2; deterministic STROBE draft |
| `bacmap_research_request` | question, run_ids?, gene?, test_name?, analysis?, ... | D2+; writes a draft request only; human approves in Web |
| `bacmap_research_requests` | `status?`, `limit?` | D2+; list request drafts |

Research creation and custom figure attachment are CLI/Web/API only; MCP is read-only for
research sessions. Custom figures are attached with `bacmap research figure attach` after the
script has run through the `mine` sandbox.
P1 output is `TEST/UNVERIFIED` (open-test) or `REVIEW REQUIRED`.

### 3.6 `bio_*` tools

The 27 registry tools are documented in [Tool registry](tools.md). Under `cloud`, only tools within
the data ceiling are registered; under `local-trusted`, all read/compute tools are available. Four
`write` tools (`bio_analyze_pathogen`, `bio_generate_report`, `bio_add_metadata`,
`bio_add_lab_result`) are never exposed directly; use tasks/plans/records.

## 4. Prompts and resources

| Kind | Name | Purpose |
|---|---|---|
| Prompt | `bacmap_role_<role>` | global principles + permission boundary + SKILL guidance |
| Resource | `skill://bacmap/<role>/SKILL.md` | raw SKILL.md, metadata includes `sha256` |

Roles: analyst, curator, miner, literature, writer, epidemiologist. Fetch the role prompt before
performing domain work.

## 5. Errors

MCP tool failures return JSON envelopes rather than transport errors where possible:

```json
{"code": "validation_error", "error": "directory not found: /data/run42"}
{"code": "not_found", "error": "no such task: ..."}
{"code": "conflict", "error": "plan hash mismatch ..."}
{"code": "forbidden", "error": "only the MCP client that created this plan may revise it"}
```

Unknown tools are rejected by the SDK. Data-class violations are refused at registration and again
at call time.

## 6. Minimal client conversation

```text
1. bacmap_capabilities {}
2. bacmap_create_plan {"tasks":[{"task_type":"analyze","samples":["SAM-001"]}]}
3. (show confirm_url to the user; user confirms in Web/CLI)
4. bacmap_get_plan {"plan_id":"..."}                  # → state=submitted, task_ids
5. bacmap_task_status {"task_id":"..."}               # poll
6. bacmap_task_result {"task_id":"..."}               # gate summary + run_id
```

The client never receives a tool that confirms a plan or signs an approval.
