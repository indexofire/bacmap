**English** | [简体中文](harnesses.zh-CN.md)

# Agent harnesses (Hermes · Pi · DeepSeek Harness)

From v1.5 (frozen ADR-21), conversation with bacmap is meant to happen in the native interface of an
external agent harness. The harness reaches bacmap only through MCP. bacmap keeps the deterministic
pipeline, the gates, and the **trusted confirmation surface**: plans proposed by an agent run only after
a person confirms the exact version in `bacmap plan confirm` or the Web page `/plans`.

No harness is required. Without one, the CLI and Web console still provide every deterministic function.

## 1. What a harness can do over MCP

| Tool | Purpose |
|---|---|
| `bio_*` read/compute tools | Query results and run single-step tools, filtered by the instance's profile |
| `bacmap_create_plan` / `bacmap_revise_plan` / `bacmap_get_plan` | Propose typed analyze/curate tasks; read the plan state and, after confirmation, its `task_ids` |
| `bacmap_task_status` / `bacmap_task_result` / `bacmap_task_cancel` | Follow tasks; the result is a summary (run ID, gate verdicts); cancellation is limited to tasks this client submitted |
| `bacmap_record_data` | Metadata / lab results / knowledge entries via `record` tasks (local-trusted only) |
| `bacmap_confirm_plan_locally` | Local confirmation dialog over stdio; the human click is the confirmation |
| Plan ownership | `bacmap_get_plan` / `bacmap_revise_plan` only work for plans this client created |
| `bacmap_capabilities` | Server version, profile and data-class ceiling, plannable task types, recommended write path, long-task mechanism |
| `bacmap_submit_task` | Compatibility entry for direct submission |
| Prompts `bacmap_role_<role>` and resources `skill://bacmap/<role>/SKILL.md` | Domain instructions; each resource carries a `sha256` digest in its metadata |

A harness cannot confirm a plan or sign an approval. MCP elicitation and the harness's own tool
approvals are answered by the client or the model, so bacmap never treats them as confirmation.

## 2. Profiles

Each bacmap MCP instance is bound to one profile at launch (see the [usage guide](usage.md)):

- `cloud` (default): tools whose output is at or below `[llm.data_policy].cloud_max_data_class`.
  Task messages are withheld and task results contain gate counts only, because they can name
  individual strains.
- `local-trusted`: all read/compute tools up to D4. The administrator enables it with
  `[mcp] allow_local_trusted = true` in `config.toml`. Use it only when the harness talks to a local
  or LAN model.

## 3. Client configuration

Replace `/path/to/bacmap` with the `bacmap` executable of your pixi environment
(`.pixi/envs/default/bin/bacmap`).

### Hermes (verified with v0.21.3)

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/bacmap
    args: ["mcp"]                    # add "--profile", "local-trusted" for local models
```

Check the connection without starting a conversation: `hermes mcp test bacmap`.

### Pi (verified with v1.1.0; built-in MCP needs Pi ≥ 0.99)

```json
// ~/.pi/agent/mcp.json
{ "mcpServers": { "bacmap": { "command": "/path/to/bacmap", "args": ["mcp"] } } }
```

Check it with `pi mcp list`. Pi enables its own `bash`, `read`, `write` and `edit` tools by default; see §4.

### DeepSeek Harness (verified with v0.2.1-rc.2)

DSH composes plugins from patch layers. A new entry must be wrapped in `insert:`; a bare entry is
treated as a patch of an existing ID and is skipped with `patch: entry ... not found`.

```yaml
# $DSH_HOME/cordis.patch.yml (all profiles) or $DSH_HOME/profiles/<profile>/cordis.patch.yml
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

`dsh <profile> --dump-config` shows whether the entry was composed. Tools appear as
`mcp__bacmap__<tool>`.

### Streamable HTTP (any harness)

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765            # cloud profile
```

Point the harness at `http://127.0.0.1:8765/mcp` with `Authorization: Bearer <token>`
(Hermes: `url` + `headers`; Pi: `pi mcp add bacmap --url … --bearer-token-env-var BACMAP_MCP_TOKEN`;
DSH: `transport: streamable-http`, `url`, `headers`). To offer `local-trusted` as well, run a second
instance on another port with another token.

## 4. Data boundary: isolate bacmap by operating-system account

MCP profiles only protect data that flows through MCP. Every supported harness also has shell and
file tools, and a harness backed by a cloud model would send whatever those tools read. The
recommended deployment therefore separates the two by account:

1. Run bacmap under a dedicated system account, for example `bacmap`, with
   `BACMAP_HOME=/srv/bacmap` and `chmod 700 /srv/bacmap`.
2. Start `bacmap mcp --transport http` (and `bacmap web`) as that account, for example from a systemd
   service, bound to `127.0.0.1`.
3. Run the harness as your normal user. Give it only the MCP URL and token, not the Web token.

With this layout the harness's shell cannot read sequences or metadata directly. bacmap cannot control
data that a user copies into the harness's working directory, or what a model provider does with
content it receives. The deployment reduces these risks but does not remove them.

**Local models and resource arbitration (ADR-17).** If a harness talks to the same local Strata
instance that bacmap uses, its requests bypass bacmap's serial queue. While a memory-heavy pipeline
step has the model unloaded, the harness session will stall or fail. Prefer a separate inference host
for the harness, or a cloud endpoint together with the `cloud` profile.

## 5. Verification record

Checked with `glm-5.3` on the Zhipu coding-plan endpoint
(`https://open.bigmodel.cn/api/coding/paas/v4`). Each harness ran the same conversation twice:
first it called `bacmap_create_plan` and reported the `plan_id`, `version` and `state`; a person then
confirmed that exact version in the CLI; second, the harness called `bacmap_get_plan` and
`bacmap_task_status` and reported `submitted` plus the task ID.

| Harness | Version | MCP discovery | Full plan round trip | Notes |
|---|---|---|---|---|
| Hermes | 0.17.0+52045 (2026-10-25) | ✓ full loop after the two workarounds below | ✓ create → confirm → read back `submitted` + task ID | `provider: zai` with `GLM_BASE_URL` pointing at the coding-plan endpoint |
| Hermes | 0.21.3 (2026-10-25, earlier record) | ✓ `hermes mcp test`, tools under `cloud` | ✓ same | Before the build moved to per-data-root runtimes |
| Pi | 1.4.0 (2026-10-25) | ✓ `pi mcp list` | ✓ same | Custom `models.json` provider with `api: openai-completions`; re-verified after the 1.4 update |
| DSH | 0.2.1-rc.2 (2026-10-25) | ✓ plugin start launches the bacmap MCP server | ✓ same | Patch the existing `llm-pi-ai` entry; adding a second `dsh-llm-pi-ai` entry fails with `provider "amazon-bedrock" is already declared` |

**Hermes 0.17.0+52045 workarounds (both upstream behaviours, not bacmap issues):**

1. A *fresh* `HERMES_HOME` bootstraps its own runtime, and `python-olm 3.2.16` fails to build
   because CMake ≥ 4 rejects `cmake_minimum_required` < 3.5. Set
   `CMAKE_POLICY_VERSION_MINIMUM=3.5` for the first launch (or install a build without the
   `matrix` extra).
2. That isolated runtime ignores `ZAI_API_KEY`/`GLM_API_KEY` from the environment; store the key
   in its own credential store first:
   `hermes auth add zai --type api-key --api-key <key>` (then `hermes auth status zai`).

The reproduction script is `dev/harness-e2e.sh` (local only, requires a model API key in the
environment; it never writes the key to disk). Plan round trips are also covered with a real MCP
stdio client in the test suite and in the release smoke test, without a model.
