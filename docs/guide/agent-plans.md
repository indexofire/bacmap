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

## 0. Minimal operating sequence (copy this)

1. make your client start `bacmap mcp` (configuration in §3);
2. state the goal and an **absolute path** in the chat:
   > Analyse the eight *V. parahaemolyticus* read sets in `/data/run42` with the standard pipeline.
3. the agent calls `bacmap_create_plan` and returns `plan_id`, `version`, `plan_hash` and
   `confirm_url`;
4. **you** confirm that exact version: open `confirm_url`, ask the agent to show the local dialog,
   or run:
   ```bash
   bacmap plan confirm <plan_id> --version <version> --hash <first-12-chars>
   ```
5. keep asking:
   > Where is the run? When it finishes, summarise serotype and AMR and list the samples needing
   > review.

The agent cannot confirm for you; that is a design boundary, not a malfunction. For a complete
example see the [tutorial](../getting-started/tutorial.md).

## 0.1 No per-message boilerplate: persistent instructions / hooks

The bacmap MCP server returns **server instructions** during initialisation. They already state:

- route analysis/writes through `bacmap_create_plan`;
- a human confirms the exact plan version; the agent cannot;
- do not use the harness shell/file tools to run `snakemake`/`gside`/`gapit`/`gmlst`;
- do not read raw sequences; pass absolute paths or sample IDs and let bacmap execute locally;
- track execution with `bacmap_get_plan` / `bacmap_task_status` / `bacmap_task_result`;
- cite sample, task and run identifiers in conclusions.

Clients that honour MCP instructions include this automatically. If yours does not—or you want a
stronger reminder—use that client's persistent-instruction mechanism instead of pasting rules every
turn.

### Hermes

Hermes auto-injects project context files. In the directory where Hermes starts, create one of:

```text
.hermes.md        # Hermes-specific; can inherit with the project
AGENTS.md         # portable across agents (current directory)
```

Add:

```markdown
# bacmap operating rules

- For bacmap work, call only mcp__bacmap__* tools.
- Create a plan first with bacmap_create_plan; show plan_id/version/plan_hash/confirm_url and wait for human confirmation.
- Never run snakemake/gside/gapit/gmlst through the shell; never read FASTQ/FASTA content.
- The user provides absolute paths or sample IDs; bacmap executes locally.
- Track with bacmap_get_plan/bacmap_task_status and cite task_id/run_id in conclusions.
```

Start a new session and ask “what are your bacmap operating rules?” to verify injection.
`hermes --ignore-rules` disables context injection for a control test.

### Pi

Pi supports persistent system instructions at both levels:

```text
~/.pi/agent/APPEND_SYSTEM.md     # appended globally
<project>/.pi/APPEND_SYSTEM.md   # project-level (requires project trust)
<project>/AGENTS.md              # ordinary context file
```

Put the same rules in `~/.pi/agent/APPEND_SYSTEM.md`, then run `/reload` inside Pi or start a new
session.

### DSH

DSH's agent-instructions plugin reads:

```text
$DSH_HOME/AGENTS.md              # global; defaults to ~/.dsh
<workspace>/AGENTS.md            # workspace instructions
```

Add the same rules to one of those files and open a new session. The first session-log message with
`source.kind=agent-instructions` should contain it; `dsh <profile> --dump-config` shows whether
`@deepseek-ai/dsh-agent-instructions` is enabled.

### When do you need a real hook?

Use a hook/plugin only for mechanical enforcement—intercepting shell calls, rewriting prompts, or
writing audit events. For “do not bypass bacmap”, persistent instructions plus bacmap's server-side
plan gate are enough: even a misled model has no tool to confirm a plan or sign a gate.

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

## 3. Client installation and configuration

### 3.0 Install a harness first (pick one)

All three are independent of the bacmap environment. Install them with their own installer, npm,
pipx or conda environment; they do not need `snakemake`, `gside`, `gapit` or `gmlst` on PATH.

**Hermes**

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes --version
```

**Pi** (built-in MCP needs ≥0.99; Node ≥22.19)

```bash
curl -fsSL https://pi.dev/install.sh | sh
# or: npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --version
```

**DeepSeek Harness (DSH)**

```bash
npx @deepseek-ai/dsh web
# Web UI defaults to http://127.0.0.1:3080
```

### 3.1 Where the bacmap executable lives

The current supported distribution uses pixi:

```text
/path/to/bacmap/.pixi/envs/default/bin/bacmap
```

Once a standalone conda package is published it will be installable as:

```bash
conda create -n bacmap -c conda-forge -c bioconda bacmap
```

For a stdio client, do not rely on the harness PATH. Two robust wiring patterns:

**Point directly at the executable (pixi / conda env bin)**

```text
command: /opt/conda/envs/bacmap/bin/bacmap
args: ["mcp"]
```

**Launch through conda run (so PATH comes from that environment)**

```text
command: conda
args: ["run", "--no-capture-output", "-n", "bacmap", "bacmap", "mcp"]
```

`--no-capture-output` matters: MCP stdio must be passed through unchanged.

For HTTP, start bacmap inside its environment; clients need only the URL and token:

```bash
conda run --no-capture-output -n bacmap bacmap mcp \
  --transport http --host 127.0.0.1 --port 8765
```

### Hermes

Configure the MCP server:

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/bacmap
    args: ["mcp"]
    # With a local/LAN model and [mcp] allow_local_trusted = true:
    # args: ["mcp", "--profile", "local-trusted"]
```

Model credentials belong to Hermes, not bacmap. Configure them with Hermes itself (usually
`/login`, `/model`, or `hermes auth add ...`), then verify:

```bash
hermes mcp test bacmap
hermes
```

Connected tools appear as `mcp__bacmap__bacmap_create_plan`.

### Pi (≥0.99 for built-in MCP)

The CLI is the easiest way to write the config:

```bash
pi mcp add bacmap -- /path/to/bacmap mcp
# Trusted local profile:
pi mcp add bacmap -- /path/to/bacmap mcp --profile local-trusted

pi mcp list
pi
```

Equivalent JSON:

```json
// ~/.pi/agent/mcp.json
{"mcpServers": {"bacmap": {
  "command": "/path/to/bacmap",
  "args": ["mcp"],
  "description": "Local pathogen genomics workstation"
}}}
```

Configure models with Pi's `/login` and `/model`. Use `/mcp` inside a session to inspect the
connection.

### DeepSeek Harness (DSH)

DSH connects over its MCP-client plugin. A new entry must be wrapped in `insert:`; a bare entry is
treated as a patch and skipped.

```yaml
# $DSH_HOME/cordis.patch.yml
# DSH_HOME defaults to ~/.dsh
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: /path/to/bacmap
      args: ['mcp']
      # Trusted local profile:
      # args: ['mcp', '--profile', 'local-trusted']
      failOnStartupError: true
```

Check the composed configuration:

```bash
dsh <profile> --dump-config
```

Start it:

```bash
npx @deepseek-ai/dsh web
```

Tools appear as `mcp__bacmap__bacmap_create_plan`. Configure models in DSH's
**Settings → Models**.

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

### Streamable HTTP (recommended for multi-client/isolated deployment)

Start bacmap inside its environment:

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
```

Hermes:

```yaml
mcp_servers:
  bacmap:
    url: http://127.0.0.1:8765/mcp
    headers:
      Authorization: "Bearer ${BACMAP_MCP_TOKEN}"
```

Pi:

```bash
pi mcp add bacmap \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var BACMAP_MCP_TOKEN
pi mcp list
```

DSH:

```yaml
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: streamable-http
      url: http://127.0.0.1:8765/mcp
      headers:
        Authorization: "Bearer ${BACMAP_MCP_TOKEN}"
      failOnStartupError: true
```

In HTTP mode the harness needs neither bacmap's conda nor its pixi environment; it only reaches the
local URL. To expose both `cloud` and `local-trusted`, run two ports with separate tokens.

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
