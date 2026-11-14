# Agents and plans

Natural-language interaction with large language models happens in an external agent harness.
The harness reaches bacmap only over MCP; the deterministic pipeline, gates and **trusted
confirmation surface** stay in bacmap. There is no built-in chat.

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

1. make your client start `bacmap start mcp` (configuration in §3);
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
- do not use the harness shell/file tools to run `snakemake`/`gside`/`gspec`/`gmlst`;
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
- Never run snakemake/gside/gspec/gmlst through the shell; never read FASTQ/FASTA content.
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

## 0.2 Installable guidance (`bacmap agent`)

The role guides and operating rules are served by bacmap itself: MCP server instructions,
`bacmap_role_<role>` prompts and `skill://bacmap/<role>/SKILL.md` resources. If your client does
not inject them automatically, generate a harness adapter instead of copying text by hand:

```bash
bacmap agent list                              # supported harnesses
bacmap agent export --harness pi               # print instructions
bacmap agent export --harness hermes --format mcp-config
bacmap agent install --harness pi --scope project
bacmap agent install --harness generic --with-skills
bacmap agent install --harness pi --inline-skills
bacmap agent doctor
```

- `install` is idempotent; it refuses to overwrite a user file unless `--force`;
- `.bacmap-agent.json` records the generated files and their hashes;
- `doctor` reports missing/modified files and bacmap-version drift;
- `--with-skills` writes portable `.bacmap/skills/<role>/SKILL.md` copies for
  harnesses without a verified skill directory (DSH, Codex), and writes directly
  into the per-harness conventions verified in 2026-11 live installs otherwise:
  Hermes `~/.hermes/skills/<role>/` (project scope `./.hermes/skills` needs
  `hermes skills trust` once), Pi `~/.pi/agent/skills/<role>/`, and the
  cross-agent `~/.agents/skills/<role>/` convention for OpenCode/generic;
- `--inline-skills` (or repeated `--inline-role ROLE`) appends the role bodies to the
  instructions file. Use it when the harness does not inject skills/resources into the model
  context (Pi in `--print` mode is a verified example);
- MCP configuration snippets are printed by `--format mcp-config` and are never written
  automatically.

These files are **guidance, not permissions**. Actual permissions come from the MCP profile; the
plan gate, write boundary and data classes stay server-side (ADR-12/16/21).

## 1. Start an MCP server

```bash
# stdio: the harness launches the process
bacmap start mcp

# read-only: no task/plan write tools at all
bacmap start mcp --read-only

# local-trusted (D4): must be enabled in config.toml first
bacmap start mcp --profile local-trusted

# Streamable HTTP: bearer auth is mandatory
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
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
pipx or conda environment; they do not need `snakemake`, `gside`, `gspec` or `gmlst` on PATH.

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
args: ["start", "mcp"]
```

**Launch through conda run (so PATH comes from that environment)**

```text
command: conda
args: ["run", "--no-capture-output", "-n", "bacmap", "bacmap", "start", "mcp"]
```

`--no-capture-output` matters: MCP stdio must be passed through unchanged.

For HTTP, start bacmap inside its environment; clients need only the URL and token:

```bash
conda run --no-capture-output -n bacmap bacmap start mcp \
  --transport http --host 127.0.0.1 --port 8765
```

### Hermes

Configure the MCP server. Prefer launching through `pixi run` (or `conda run`): task
execution shells out to `snakemake`, and a bare console-script shim does not put the
env's bin on the harness PATH.

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: pixi
    args: ["run", "--manifest-path", "/path/to/bacmap/pixi.toml", "-e", "default",
           "bacmap", "start", "mcp"]
    # With a local/LAN model and [mcp] allow_local_trusted = true:
    # args: [..., "bacmap", "start", "mcp", "--profile", "local-trusted"]
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
pi mcp add bacmap -- /path/to/bacmap start mcp
# Trusted local profile:
pi mcp add bacmap -- /path/to/bacmap start mcp --profile local-trusted

pi mcp list
pi
```

Equivalent JSON:

```json
// ~/.pi/agent/mcp.json
{"mcpServers": {"bacmap": {
  "command": "/path/to/bacmap",
  "args": ["start", "mcp"],
  "description": "Local pathogen genomics workstation"
}}}
```

Configure models with Pi's `/login` and `/model`. Use `/mcp` inside a session to inspect the
connection.

### DeepSeek Harness (DSH)

DSH connects over its MCP-client plugin. The patch file is **per profile**:
`$DSH_HOME/profiles/<profile>/cordis.patch.yml` (e.g. `~/.dsh/profiles/tui/`, `~/.dsh/profiles/web/`,
and `~/.dsh/profiles/dsh-tui/` each carry their own copy) — edit the profile you use, or all of the
ones you rely on. A new entry must be wrapped in `insert:`; a bare entry is
treated as a patch and skipped.

```yaml
# $DSH_HOME/profiles/<profile>/cordis.patch.yml
# one file per profile; DSH_HOME defaults to ~/.dsh
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: pixi
      args: ['run', '--manifest-path', '/path/to/bacmap/pixi.toml', '-e', 'default',
             'bacmap', 'start', 'mcp']
      # Trusted local profile:
      # args: [..., 'bacmap', 'start', 'mcp', '--profile', 'local-trusted']
      failOnStartupError: true
```

Research tools carry D2 data: under `cloud` they appear only when the administrator relaxes
`[llm.data_policy] cloud_max_data_class` to `"D2"` (D1 by default). `--profile local-trusted`
(D4) is only for local/intranet models, never for cloud endpoints (ADR-16). See the end-to-end
DSH research tutorial in
[Research Workbench §19](research-workbench.md#19-tutorial-driving-research-from-an-external-agent-dsh).

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
args = ["start", "mcp"]
```

### OpenCode

```json
// opencode.json
{"mcp": {"bacmap": {
  "type": "local",
  "command": ["/path/to/bacmap", "start", "mcp"],
  "enabled": true}}}
```

### Streamable HTTP (recommended for multi-client/isolated deployment)

Start bacmap inside its environment:

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
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
  "bacmap_version": "0.1.5",
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

### 5.2 Confirm (human or server-side pre-authorisation)

Three channels:

1. **Web link** (default): `confirm_url` → plan page → **Confirm and submit**.
2. **Local dialog** (stdio): ask the agent to call `bacmap_confirm_plan_locally`; a zenity/kdialog
   dialog shows plan ID/version/hash; the click is the confirmation (`actor=local-dialog`).
3. **Pre-authorisation** (admin, optional): by default only analyze plans over registered samples;
   `task_types`, `allow_directory_ingestion`, `allow_scripts` and `allow_drafts` can explicitly
   broaden it for automated iteration (`actor=policy:auto-confirm`).

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

### 5.4 Completion and progress without busy polling

Two mechanisms (v1.10.30) keep the agent informed after the user confirms a long-running plan:

1. **Callback URL** — pass `callback_url` to `bacmap_create_plan` (the watch covers every task the
   plan submits) or to `bacmap_submit_task` / `bacmap_task_watch`. bacmap POSTs JSON on
   `submitted`, `step`, `progress` and `finished` with D1 metadata only: `task_id`, `state`,
   `step`, `progress_pct`, `seq`, `plan_id`. Loopback hosts are allowed by default; set
   `BACMAP_NOTIFY_ALLOWED_HOSTS` for a LAN agent endpoint.
2. **Durable outbox polling** — `bacmap_task_notifications(after=cursor, task_id=... | plan_id=...,
   wait_seconds=30)` returns the next events; pass the returned `cursor` on the next call. The
   optional long-poll (up to 30 s) lets an agent wait cheaply and then relay a progress update to
   the user.

Progress is an estimate: the current stage floor plus elapsed time versus the median duration of
previous successful tasks of the same type (`estimated=true`). Without history only the stage
floor is reported (`estimated=false`); terminal states are always 100. The notification payload
never includes the task message (sample IDs/paths, D2) — call `bacmap_task_status` for details.

## 6. Open-path review

`mine` and `write` plans show the **entire** script/draft at confirmation; they are part of the plan
hash. Read them before confirming. `mine` runs offline in a sandbox; artefacts still need the mining
gate and a human signature.

## 7. Data boundary and deployment

MCP profiles only protect data that flows through MCP. Harnesses bring their own shell/file tools, so
for cloud-backed harnesses:

1. run bacmap under a dedicated OS account with `BACMAP_HOME` mode `0700`;
2. run `bacmap start mcp --transport http` (and `bacmap start web`) as that account, bound to loopback;
3. give the harness only the MCP URL/token, never the Web token.

bacmap cannot control files copied into the harness workspace or what a model provider does with
content it receives.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Harness sees no tools | `bacmap_capabilities`; confirm the process is running and the profile is expected |
| "tool not found" for D3/D4 | Cloud profile ceiling; use `local-trusted` with a local model |
| `forbidden` on `bacmap_get_plan` | The plan belongs to another MCP client; use the same client or create a new plan |
| `confirm_url` unreachable | `BACMAP_WEB_URL` / run `bacmap start web`; or use CLI confirmation |
| Confirmation conflict | Input changed since planning; ask the agent to revise and re-confirm |
| Task `awaiting_approval` forever | A human must sign the gate; agents cannot |
| `sandbox unavailable` | Install Apptainer/Podman; passthrough is dev-only |
| Redacted task failure | Cloud profile limit; use `local-trusted` or check `bacmap task show` locally |

## 9. Verified clients (2026-11)

| Harness | Version | Discovery | Plan round trip |
|---|---|---|---|
| Hermes | 0.23.0 | `hermes mcp test bacmap` | create → human confirm → read back `submitted` + task ID |
| Pi | 1.4.0 (built-in MCP ≥0.99) | `pi mcp list` | same |
| DSH | 0.2.2-rc.1 | plugin starts the MCP server | MCP plugin layer verified; browser chat layer pending manual check |

2026-11 real-data run (8 *V. parahaemolyticus* assemblies, Hermes headless `-z` + CLI
confirm): analyze plan confirmed and executed to `succeeded`; read-only tools summarised
MLST/AMR per sample; a `mine` plan ran in the rootless-Podman sandbox, produced
`mine_report.json` and stopped at the mining gate until a human signature (`task approve` →

`succeeded`). The agent self-corrected `input_data_class` D3→D2 under the cloud profile and
never attempted to confirm a plan itself.

Upstream workarounds:

- **Hermes fresh `HERMES_HOME`**: `python-olm` fails to build with CMake ≥4; set
  `CMAKE_POLICY_VERSION_MINIMUM=3.5` for the first launch. The isolated runtime ignores
  `ZAI_API_KEY`/`GLM_API_KEY` until you add it with
  `hermes auth add zai --type api-key --api-key <key>`.
- **Moved pixi env**: after moving/renaming the repo, conda entry points keep stale shebangs
  (`snakemake`, `bedtools`, …: `bad interpreter`). `pixi clean --environment default && pixi
  install` rebuilds them. Launching MCP through `pixi run` (see §3) also keeps the env's bin
  on PATH for task execution.
- **DSH**: new entries must be wrapped in `insert:`; a bare entry is treated as a patch and
  skipped. The web UI prints a `?token=…` URL on first start; curl from outside the browser
  meets the browser-trust fence by design.
- **Pi**: if MCP tools are missing, check `pi --version` (≥0.99).

The automated test suite covers the stdio plan round trip with a real MCP client; the table above
records manual model-backed checks with the Zhipu coding-plan endpoint.

## 10. Embedding the bacmap console in your harness (PLAN #20)

Running bacmap Web and your agent harness in separate windows works, but some users prefer
a single window. Each harness has a different mechanism:

### DSH: sidebar bundle (implemented)

`tools/dsh-bacmap-console` is a DSH bundle that embeds the bacmap web console in the DSH
sidebar. It reverse-proxies `http://127.0.0.1:8800` under the DSH origin at `/bacmap/console/`
(removing `X-Frame-Options` and rewriting CSP `frame-ancestors`), sets the SPA router base and
prefixes runtime report/API URLs for the mount. The console and the embedded full report both
work inside the DSH iframe; open `/bacmap/console/` directly if needed.

```bash
# Already in the bacmap repo; link it into your DSH profile:
ln -s /path/to/bacmap/tools/dsh-bacmap-console ~/.dsh/profiles/web/node_modules/@local/
```

### Hermes: Desktop plugin panel

Hermes Desktop supports custom sidebar panels via `desktop/plugin.js` in a plugin
package. A bacmap panel would:

1. Register a `bacmap_console` panel in `plugin.yaml`
2. In `desktop/plugin.js`, create an `<iframe>` pointing to `http://127.0.0.1:8800`
   (CORS headers may need adjusting, or use Hermes's built-in proxy)
3. The panel appears alongside Hermes's built-in panels

This requires Hermes Desktop (not the CLI/TUI version).

### Pi: glimpseui WebView window

Pi extensions can use the [`glimpse`](https://github.com/hazat/glimpse) native WebView
to open bacmap Web in a floating window with **bidirectional JSON communication**:

```typescript
// Pi extension (TypeScript)
import { spawn } from "child_process";

export default {
  name: "bacmap-panel",
  tools: [{
    name: "bacmap_panel",
    description: "Open the bacmap web console",
    parameters: { type: "object", properties: { path: { type: "string" } } },
    execute: async (params) => {
      const url = `http://127.0.0.1:8800${params.path || "/"}`;
      const proc = spawn("glimpse", ["--url", url]);
      return { text: `bacmap console opened: ${url}` };
    },
  }],
};
```

Install: `pi install npm:glimpseui`

### Remote deployment (bacmap on server, agent on laptop)

When bacmap runs on a server and the agent runs locally:

1. **SSH tunnel** (simplest): `ssh -L 8800:localhost:8800 server` — both Web and MCP
   accessible via `localhost`
2. **Direct HTTP with token**: expose `bacmap start web` on the LAN (with
   `BACMAP_WEB_TOKEN`), and point the harness's MCP config to
   `http://server:8765/mcp` with the token
3. **VPN/WireGuard**: full network access, no special configuration needed

The DSH reverse-proxy approach works for remote bacmap too — just change the proxy
target from `localhost:8800` to the server address.
