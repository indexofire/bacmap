# Agents and plans

From v1.5 (ADR-21), conversation lives in an external agent harness. The harness reaches bacmap
only over MCP; the deterministic pipeline, gates and **trusted confirmation surface** stay in
bacmap. There is no built-in chat.

```text
Hermes / Pi / DSH / Codex / any MCP client
        │  MCP: tools, prompts, resources
        ▼
bacmap MCP server ── profile (cloud | local-trusted)
        │
        ├─ read/compute tools (profile-filtered)
        ├─ plan tools: create / revise / get
        ├─ task tools: submit / status / result / cancel
        └─ record tool (local-trusted only)
                 │
                 ▼
        task engine + gates + audit
                 ▲
                 │ human confirmation (Web / CLI / local dialog)
              you
```

## 1. Start an MCP server

```bash
# stdio: the harness launches the process
bacmap mcp

# read-only: no task/plan write tools at all
bacmap mcp --read-only

# local-trusted (D4): must be enabled in config.toml first
bacmap mcp --profile local-trusted

# Streamable HTTP: bearer auth is mandatory
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
```

`--profile` is fixed at launch; a client cannot self-upgrade. Use different ports/tokens for two
profiles.

## 2. Profiles and data classes

| Profile | Tool output ceiling | Enablement |
|---|---|---|
| `cloud` (default) | `[llm.data_policy].cloud_max_data_class`, default D1, at most D2 | nothing |
| `local-trusted` | up to D4 (sequences, metadata, lab results) | `[mcp] allow_local_trusted = true` **and** `--profile local-trusted` |

```toml
# $BACMAP_HOME/config.toml
[mcp]
allow_local_trusted = true
```

Use `local-trusted` only when the harness talks to a local/LAN model. Under `cloud`, task messages
are withheld (they may contain sample IDs/paths) but `bacmap_task_status` returns a redacted
`failure` block with a failure kind, suggested fix and recovery commands.

## 3. Client configuration

Replace `/path/to/bacmap` with your executable
(`/path/to/bacmap/.pixi/envs/default/bin/bacmap`).

### Hermes

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/bacmap
    args: ["mcp"]                 # add "--profile", "local-trusted" for local models
```

```bash
hermes mcp test bacmap
```

### Pi (≥0.99 for built-in MCP)

```json
// ~/.pi/agent/mcp.json
{"mcpServers": {"bacmap": {
  "command": "/path/to/bacmap", "args": ["mcp"]}}}
```

```bash
pi mcp list
```

### DeepSeek Harness (DSH)

A new entry must be wrapped in `insert:`; a bare entry is treated as a patch and skipped.

```yaml
# $DSH_HOME/cordis.patch.yml
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: /path/to/bacmap
      args: ['mcp']
      failOnStartupError: true
```

### Codex

```toml
# ~/.codex/config.toml
[mcp_servers.bacmap]
command = "/path/to/bacmap"
args = ["mcp"]
```

### OpenCode

```json
// opencode.json
{"mcp": {"bacmap": {
  "type": "local",
  "command": ["/path/to/bacmap", "mcp"],
  "enabled": true}}}
```

### Streamable HTTP

Point the client at `http://127.0.0.1:8765/mcp` and send:

```http
Authorization: Bearer <BACMAP_MCP_TOKEN>
```

Hermes uses `url` + `headers`; Pi supports
`pi mcp add bacmap --url … --bearer-token-env-var BACMAP_MCP_TOKEN`; DSH uses
`transport: streamable-http`.

## 4. What the tools expose

Exact visibility depends on the profile. Ask the server first:

```json
// call bacmap_capabilities
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

| Group | Tools |
|---|---|
| Capabilities | `bacmap_capabilities` |
| Read/compute | `bio_*` tools within the profile ceiling (e.g. `bio_get_result`, `bio_search_samples`, `bio_compare_runs`, sequence/compute tools) |
| Plans | `bacmap_create_plan`, `bacmap_revise_plan`, `bacmap_get_plan` |
| Plan confirmation (stdio only) | `bacmap_confirm_plan_locally` |
| Tasks | `bacmap_submit_task`, `bacmap_task_status`, `bacmap_task_result`, `bacmap_task_cancel` |
| Records (local-trusted only) | `bacmap_record_data` |
| Guidance | prompts `bacmap_role_<role>`, resources `skill://bacmap/<role>/SKILL.md` (with `sha256` metadata) |

`bacmap_submit_task` is a compatibility entry for `analyze`/`curate`; the recommended write path is
a plan. `bacmap_task_cancel` only works for tasks this client submitted directly or through its own
plan.

## 5. The plan → confirm → run loop

### 5.1 Create

```json
// bacmap_create_plan arguments
{
  "tasks": [
    {"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}
  ],
  "rationale": "batch 42 assembled genomes"
}
```

Response (abridged):

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "plan_hash": "c1d2e3f4a5b6...",
  "inputs": {"/data/run42": "files-v1:sha256:..."},
  "confirm_url": "http://127.0.0.1:8800/plans/9a3f2c1b7d4e4f60?version=1",
  "next_step": "Ask the user to review and confirm ... You cannot confirm it."
}
```

Plannable task shapes:

```json
{"task_type": "analyze", "samples": ["SAM-001"]}
{"task_type": "analyze", "fasta_dir": "/abs/dir"}
{"task_type": "analyze", "fastq_dir": "/abs/dir", "species": "SAL"}
{"task_type": "curate", "scope": {"pathogen": "Salmonella"}}
{"task_type": "mine", "objective": "...", "script": "print('hi')", "input_paths": ["/abs/data"]}
{"task_type": "write", "objective": "...", "draft": "text [PMID:12345678]", "known_citations": []}
```

A plan holds at most 10 tasks. Input paths are fingerprinted at creation and re-checked at
confirmation; a change is a conflict.

### 5.2 Confirm (human only)

Three channels:

1. **Web link** (default): `confirm_url` → plan page → **Confirm and submit**.
2. **Local dialog** (stdio): ask the agent to call `bacmap_confirm_plan_locally`; a zenity/kdialog
   dialog shows plan ID/version/hash; the click is the confirmation (`actor=local-dialog`).
3. **Pre-authorisation** (admin, optional): analyze-only plans over registered samples within
   `max_samples`; `actor=policy:auto-confirm`.

CLI fallback:

```bash
bacmap plan list
bacmap plan show 9a3f2c1b7d4e4f60
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
bacmap plan reject 9a3f2c1b7d4e4f60 --version 1 --reason "wrong sample"
```

Invariants:

- Confirmation binds `(plan_id, version, plan_hash)`; a revision invalidates the old version;
- Single use: confirming twice submits the same deterministic task IDs once;
- A model cannot confirm; MCP elicitation and client tool approvals are not accepted;
- Plans are scoped to the creating MCP client: another client gets `forbidden` for
  `bacmap_get_plan` / `bacmap_revise_plan`.

### 5.3 Poll

```json
// bacmap_get_plan
{"plan_id": "9a3f2c1b7d4e4f60", "version": 1}
// → state=submitted, task_ids=["..."]
```

```json
// bacmap_task_status
{"task_id": "..."}
// → {"state": "running", "current_step": "pipeline", ...}
```

After confirmation, the tasks are submitted with `submitted_by="<confirmer> via plan <id>@v1"`.

## 6. Open-path review

`mine` and `write` plans show the **entire** script/draft at confirmation; they are part of the plan
hash. Read them before confirming. `mine` runs offline in a sandbox; artefacts still need the mining
gate and a human signature.

## 7. Data boundary and deployment

MCP profiles only protect data that flows through MCP. Harnesses bring their own shell/file tools, so
for cloud-backed harnesses:

1. run bacmap under a dedicated OS account with `BACMAP_HOME` mode `0700`;
2. run `bacmap mcp --transport http` (and `bacmap web`) as that account, bound to loopback;
3. give the harness only the MCP URL/token, never the Web token.

bacmap cannot control files copied into the harness workspace or what a model provider does with
content it receives.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Harness sees no tools | `bacmap_capabilities`; confirm the process is running and the profile is expected |
| "tool not found" for D3/D4 | Cloud profile ceiling; use `local-trusted` with a local model |
| `forbidden` on `bacmap_get_plan` | The plan belongs to another MCP client; use the same client or create a new plan |
| `confirm_url` unreachable | `BACMAP_WEB_URL` / start `bacmap web`; or use CLI confirmation |
| Confirmation conflict | Input changed since planning; ask the agent to revise and re-confirm |
| Task `awaiting_approval` forever | A human must sign the gate; agents cannot |
| `sandbox unavailable` | Install Apptainer/Podman; passthrough is dev-only |
| Redacted task failure | Cloud profile limit; use `local-trusted` or check `bacmap task show` locally |

## 9. Verified clients (2026-10)

| Harness | Version | Discovery | Plan round trip |
|---|---|---|---|
| Hermes | 0.21.3 (and 0.17.0+52045) | `hermes mcp test bacmap` | create → human confirm → read back `submitted` + task ID |
| Pi | 1.4.0 (built-in MCP ≥0.99) | `pi mcp list` | same |
| DSH | 0.2.1-rc.2 | plugin starts the MCP server | same |

Upstream workarounds:

- **Hermes fresh `HERMES_HOME`**: `python-olm` fails to build with CMake ≥4; set
  `CMAKE_POLICY_VERSION_MINIMUM=3.5` for the first launch. The isolated runtime ignores
  `ZAI_API_KEY`/`GLM_API_KEY` until you add it with
  `hermes auth add zai --type api-key --api-key <key>`.
- **DSH**: new entries must be wrapped in `insert:`; a bare entry is treated as a patch and skipped.
- **Pi**: if MCP tools are missing, check `pi --version` (≥0.99).

The automated test suite covers the stdio plan round trip with a real MCP client; the table above
records manual model-backed checks with the Zhipu coding-plan endpoint.
