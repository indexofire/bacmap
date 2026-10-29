# MCP reference

bacmap runs an MCP server with stdio (default) or Streamable HTTP. Clients launch the process and
receive tools, prompts and resources. Conversation and model choice are the client's concern;
bacmap exposes domain tools and a human confirmation boundary.

## 1. Transports and authentication

| Transport | Command | Auth |
|---|---|---|
| stdio | `bacmap mcp` | OS process boundary; actor `mcp-stdio:<profile>:<user>` |
| HTTP | `bacmap mcp --transport http --host 127.0.0.1 --port 8765` | mandatory bearer token |
| unix socket | `bacmap mcp --transport http --uds /run/bacmap-mcp.sock` | mandatory bearer token |

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
# client: http://127.0.0.1:8765/mcp, Authorization: Bearer <token>
```

HTTP refuses to start without a token. DNS-rebinding protection only allows configured hosts
(loopback by default).

`--read-only` removes task/plan/record write tools; only read/compute and capabilities remain.

## 2. Profiles

One profile per server instance, fixed at launch:

```bash
bacmap mcp                          # cloud (default)
bacmap mcp --profile local-trusted  # requires [mcp] allow_local_trusted = true
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
- the model cannot confirm; `confirm_url` points to the Web plan page.

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

### 3.5 `bio_*` tools

The 26 registry tools are documented in [Tool registry](tools.md). Under `cloud`, only tools within
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
