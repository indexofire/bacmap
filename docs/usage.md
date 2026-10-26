**English** | [简体中文](usage.zh-CN.md)

# Usage guide

bacmap has three entry points: the **CLI** (operations), the **web task console** (humans), and **MCP** (AI agents).
Conversation happens in the native UI of an external agent harness (Hermes / Pi / DSH) over MCP —
see the [agent harness guide](harnesses.md); from v1.6 the built-in assistant has been removed (ADR-21).

## 1. CLI

```bash
bacmap --version
bacmap tui [--home H]                              # full-screen task console (Textual)
bacmap console [--home H]                          # 交互式菜单
bacmap overview [--json]                           # 系统概览
bacmap task list|show|submit|approve|cancel         # 任务查询与写操作（显式、无 LLM；list alias ls）
bacmap task show <short-prefix>                    # IDs accept git-style prefixes: the 12 chars shown by list just work; lengthen on ambiguity
bacmap task submit --type analyze --fasta-dir <dir> [--species <code|name>]
                                                   # assembled-FASTA directory entry: scan, register,
                                                   # submit standard analyze; with --species omitted each
                                                   # genome is auto-identified by gside (v1.4.38)
bacmap task submit --type analyze --fastq-dir <dir> [--species <code|name>]
                                                   # reads directory entry: auto-detect *_R1/_R2 pairs;
                                                   # species omitted → UNK (identified in-pipeline; no
                                                   # species-specific typing routes)
bacmap plan ls|show|confirm|reject                 # review/confirm agent-proposed plans (v1.5.1)
bacmap record metadata|lab|knowledge-import|knowledge-approve
                                                   # data entry through the task layer (v1.7)
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web console (tasks / plans / samples)
bacmap mcp [--read-only] [--profile cloud|local-trusted] [--home H]
                                                   # MCP server (stdio/HTTP); default profile cloud
```

Query subcommands accept `--json`. Writes always go through the same gates as Web/MCP.
Day-two operations (`doctor`, `backup`, `restore`, event retention) are covered in the
[operations guide](operations.md).

Top-level commands fall into two kinds: **interfaces/modes** (`mcp`, `web`, `tui`, `console`)
that take over a terminal or bind a port, and **commands** (`overview`, `task`, `sample`,
`search`) that perform one query or write and exit. `bacmap` itself *is* the
CLI, so commands stay at the top level (`bacmap task list`) rather than nested under a `cli`
subcommand; `web`/`tui`/`console` are sibling interaction modes.

## 2. Talking to bacmap: external agents and plans

There is no built-in chat any more (ADR-21). Talk to bacmap from Hermes, Pi or DSH (or any MCP
client); the agent proposes a **plan**, and you confirm that exact version in bacmap:

```bash
bacmap plan ls                       # latest version of each plan
bacmap plan show <plan_id>           # full parameters, hash, input fingerprints
bacmap plan confirm <plan_id> --hash <first 12 chars>
bacmap plan reject <plan_id> --version 1 --reason "wrong sample"
```

The Web console offers the same under **Plans** (`/plans`). See the
[agent harness guide](harnesses.md) for client configuration, and §5 for the MCP tools.

### Giving a mine task a data path

Agents cannot read arbitrary host paths — by design (ADR-11: raw data is D3 and never enters LLM
context). External data enters only through the `mine` task's `input_paths` parameter. Ask the
agent for a `mine` plan, confirm it, and the task runs: **zero-copy registration (SHA256) →
read-only mount into the sandbox → script runs → artifacts land in the workspace → mining gate
waits for your signature**. The script finds data through the workspace `context.json`
`datasets` mapping (`id → path` — an **object, not an array**).

Rules for `input_paths` (`store/datasets.py`):

- The path **must already exist**; a file or a directory (registered recursively); an empty
  directory is rejected;
- **Zero-copy**: only hashes and identity (dev/inode/mtime) are recorded — the original stays
  where it is. Do **not move or delete** it afterwards, or the mount breaks (dataset marked
  `missing`);
- Identical content deduplicates by manifest hash (reuses the `dataset_id`);
- `bio_inspect_dataset` with `verify=true` recomputes SHA256 to detect content changes;
- There is **no global config item** for it — it is a per-task parameter, and form/CLI/MCP do
  not accept mine at all (see §4 task form details).

**Execution prerequisite**: a sandbox backend (Apptainer or Podman — installation guide §6).
Without one the task fails with "沙箱不可用 / sandbox unavailable"; installing `podman` fixes
it with zero further configuration.

Besides `sandbox_run` (a Python script), a restricted **`sandbox_shell`** runs a single shell
command inside the same sandbox — only read/analysis commands (`ls`, `cat`, `grep`, `zcat`,
`samtools`, `seqkit`, `python`, …) are allowed; anything else is refused and should become a
signed `mine` task. It only runs with a real container backend (passthrough is refused by
default) and every invocation is recorded in `$BACMAP_HOME/audits/sandbox_shell.jsonl`. These
two tools belong to the **in-task** agents; MCP clients never get them.

## 3. TUI and interactive console

`bacmap tui` starts a **task console**: a status header (LLM endpoint), a collapsible sidebar
(Tasks / Samples), an operation log, and a command input, with a footer of key hints. It is a
read/dashboard surface plus a few explicit operations — there is no chat.

- **Direct keys**: `Enter` run command · `Esc` cancel pending approval / focus input · `Ctrl+C`
  quit · `Ctrl+B` toggle sidebar · `Ctrl+R` refresh · `Ctrl+L` clear log · `Ctrl+Y` confirm a
  pending signature. The input box is **focused on start**.
- **Leader `Ctrl+G`** chords (work even while the input is focused): `i` focus input · `l` tasks ·
  `s` samples · `m` model/endpoint · `t` theme · `a` **approve the selected `awaiting_approval`
  task** (the hint bar shows the task and signature; `Ctrl+Y` confirms, `Esc` cancels; the
  signature defaults to the system username) · `h` help · `q` quit.
- **Failure echo**: when a submitted task ends `failed`/`cancelled`, the log gets one line —
  `任务 <id> failed（<step>）：<reason>` — so you need not watch the sidebar.
- **Slash commands**: `/help /clear /tasks /samples /search <kw> /model /result <sample>`
  `/approve <ID> [signature]` `/analyze <sample> /curate [scope] /quit` (`/analyze` and
  `/curate` are the explicit no-LLM path; `/approve` accepts the short ID prefix shown by
  `task list` and with no argument approves the selected task; `/result` renders the selected
  sample's key findings and report path).

The sidebar auto-collapses on narrow terminals and restores your preference when width returns.
Natural language goes to an external harness (ADR-21); `bacmap console` remains a numbered menu
for users who prefer prompts over subcommands.

## 4. Web console (tasks / plans / samples / search)

Run `bacmap web`, then open `http://127.0.0.1:8800` in a browser:

1. **Plans** (`/plans`): plans proposed by agents over MCP, with their full parameters, hash and
   input fingerprints; confirm or reject here (same as `bacmap plan`).
2. **Submit a task** (Tasks page): the explicit form (task type + sample list / scope JSON).
3. **Monitor**: six state badges (queued / running / pending approval / completed / failed
   / canceled); the detail page refreshes every 2 seconds.
4. **Query results**: the Samples pages browse completed samples (list, per-sample detail
   with detected genes). Per-sample detail offers **查看 HTML 报告** — rendered *inline* in the
   browser under a `sandbox` CSP (script-free, no external requests) — and **下载** for the
   file (`?download=1`). Search finds samples by keyword or filters.
3. **Approve**: when a task reaches `pending approval`, an amber approval card appears on the detail page. Fill in the approver, the decision (approve/reject), and the signature passphrase. After submission the task passes the mining gate / release gate and proceeds

> Approval is one of the six gates: unsigned mining output cannot enter a report, and a
> baseline library that misses the gold standard cannot be released. That is by design
> (agents cannot sign off on their own), not a fault.

### Task form details

The **sample list** field (for `analyze`) takes **registered sample IDs** (e.g. `SAM-TYP-001`) —
not file paths, not natural language:

- Separate multiple IDs with **half-width (ASCII) commas or newlines**. The full-width comma
  `，` is NOT recognized — the whole entry becomes one invalid ID and the form rejects it with
  "非法样本 ID" (the TUI `/analyze` command additionally accepts spaces);
- The ID whitelist is `^[A-Za-z0-9._-]+$` — letters/digits/`.`/`_`/`-`; **no CJK characters
  or spaces**;
- Where IDs come from: the `gs/<ID>/<ID>_R{1,2}.fastq.gz` convention, or registration in
  `$BACMAP_HOME/workflows/bacmap/config/samples.tsv` (registration wins; see §7 and the
  configuration guide §5).

**scope** (for `curate`, optional) selects which isolates enter the local epidemiological baseline.
One isolate contributes once even when it has several datasets: the newest analysis is chosen by
default, or pick one explicitly with `{"representative_dataset": {"<isolate>": "<dataset>"}}`
(the candidate records the choice in `representative_runs` and lists the rest in `superseded`).: `{"pathogen": "Salmonella"}` filters by species substring;
`{"strains": ["SAM-001", "SAM-002"]}` by explicit list; empty includes every qualifying
sample (strains failing per-strain checks are recorded as excluded). `analyze` ignores it.

**mine/write never go through the form**: they are open paths (script/draft parameters) and
are submitted only through a plan confirmed by a person (ask an external harness for it) or the
Python API — the web form, CLI `task submit`, and MCP deliberately decline them, to prevent
forged requests and script injection.

### Data entry: metadata, lab results, knowledge (v1.7)

Three kinds of input are **not** registry tools you call directly — they go through the task layer
so every write is auditable. Use the **记录 / Records** page (`/records`) or the CLI:

```bash
bacmap record metadata --strain-id S1 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id S1 --category mic --test-name meropenem --result 0.25 --unit mg/L
bacmap record knowledge-import --title "Paper" --identifier PMID:12345678
bacmap record knowledge-approve 7        # the citation gate only honours approved entries
```

Each command submits a `record` task; `bacmap task show <id>` reports the outcome. Knowledge
entries land in a staging area (`approved_by` empty) until a `knowledge-approve` task runs.
Record tasks are not plannable and are never exposed over MCP (D4 writes).

### JSON API `/api/v1` (v1.5.2)

The Web server also exposes a versioned JSON API under the same authentication. It is a **trusted
surface**: whoever holds the Web token is the operator, so never hand that token to a harness.

| Method and path | Purpose |
|---|---|
| `GET /api/v1/capabilities` | API version, bacmap version, plannable task types, features |
| `GET /api/v1/tasks` · `GET /api/v1/tasks/{id}` · `POST /api/v1/tasks/{id}/cancel` | Tasks |
| `GET /api/v1/plans` · `GET /api/v1/plans/{id}?version=` | Plans |
| `POST /api/v1/plans/{id}/confirm` `{"version", "plan_hash", "confirmer"}` · `POST /api/v1/plans/{id}/reject` `{"version", "reason"}` | Confirm or reject a plan |
| `GET /api/v1/events?after=&task_id=&plan_id=` | Domain events after a cursor (`last_seq`) |
| `GET /api/v1/events/stream` | Server-Sent Events; resumes from `Last-Event-ID` |
| `GET /api/v1/samples?cursor=&limit=` | Sample list with cursor pagination (only the requested page is parsed) |
| `GET /api/v1/runs` · `GET /api/v1/runs/{id}` · `GET /api/v1/runs/{id}/compare?other=` | Run records and provenance comparison (v1.7.1) |
| `GET /api/v1/gom/objects?type=&limit=` · `GET /api/v1/gom/objects/{id}?version=` | GOM objects, latest version by default (v1.7.1) |

Errors use `{"code": "validation_error" | "not_found" | "conflict", "error": "..."}` with HTTP
400/404/409. In cookie mode, state-changing requests need an `X-CSRF-Token` header equal to the
`bacmap_csrf` cookie. Events record plan and task transitions (created, confirmed, submitted, step,
state, approval); they are not the source of truth, so after a disconnect a client should re-read
the task or plan.

### Remote access: SSH tunnel (the recommended way)

`bacmap web` binds to `127.0.0.1` only by default (ADR-16). If you need to reach it from
another computer, do **not** expose it bare with `--host 0.0.0.0`: without `BACMAP_WEB_TOKEN`
set, bacmap **refuses to start on a non-loopback host** (fail-fast, aligned with MCP HTTP);
with a token set it will start, but an SSH tunnel is still the recommended path.
Use an SSH tunnel instead: SSH carries all of the encryption and authentication, and bacmap needs zero changes:

> `BACMAP_WEB_TOKEN` (`--token-env`) adds authentication. In the default `bearer` mode it is
> sent as an `Authorization` header, which **browsers cannot set** — the HTML console answers
> **401 with a short page telling you what to do**, and `/login` renders the same explanation
> (it never redirects, so there is no redirect loop). Set `BACMAP_WEB_AUTH=cookie` to log in
> at `/login` (signed `HttpOnly` session cookie + CSRF token on every state-changing POST);
> add `BACMAP_WEB_COOKIE_SECURE=1` for TLS deployments. The startup line prints the URL and
> the effective auth hint.

```bash
# 在你自己的电脑上执行（user 为工作站账号，10.0.0.5 换成工作站实际 IP）：
ssh -L 8800:127.0.0.1:8800 user@10.0.0.5
# 保持连接，然后本地浏览器打开 http://127.0.0.1:8800
```

- Each user builds their own tunnel; tunnels do not interfere with each other
- Traffic is encrypted the whole way, which satisfies the requirement that genomic data (D3/D4) never leaves the local network and never appears in plaintext
- No root needed, no firewall port to open on the workstation, no authentication layer added to bacmap
- Data files are still registered on the workstation by the operator, per [configuration guide §5](configuration.md); remote upload is a planned feature (to be considered once the agent-side bioinformatics analysis features are done)

## 5. MCP agent access

From v1.5 the recommended way to *talk* to bacmap is through the native UI of an external agent harness — **Hermes, Pi (≥0.99) or DeepSeek Harness (DSH)** — connected over MCP (frozen ADR-21). bacmap keeps the CLI and Web console for deterministic work and for **confirmations and approvals**, which never happen inside the harness. Any other client that speaks MCP (Codex / OpenCode / OpenClaw / Claude, and more) works the same way. Sample client configurations:

```yaml
# Hermes (~/.hermes/config.yaml)
mcp_servers:
  bacmap:
    command: /path/to/.pixi/envs/default/bin/bacmap
    args: ["mcp"]                       # add "--profile", "local-trusted" for local models
```

```json
// Pi (~/.pi/agent/mcp.json, Pi ≥ 0.99)
{ "mcpServers": { "bacmap": {
  "command": "/path/to/.pixi/envs/default/bin/bacmap", "args": ["mcp"] } } }
```

```yaml
# DSH ($DSH_HOME/cordis.patch.yml; a new entry must be wrapped in insert:)
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: /path/to/.pixi/envs/default/bin/bacmap
      args: ['mcp']
```

```json
// OpenCode（opencode.json）
{ "mcp": { "bacmap": { "type": "local",
  "command": ["/path/to/.pixi/envs/default/bin/bacmap", "mcp"], "enabled": true } } }
```

```toml
# Codex（~/.codex/config.toml）
[mcp_servers.bacmap]
command = "/path/to/.pixi/envs/default/bin/bacmap"
args = ["mcp"]
```

Streamable HTTP (ADR-12) is available for clients that speak it. It is bound to localhost (or a unix socket) and **requires bearer auth**:

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
# or a unix socket: bacmap mcp --transport http --uds /run/bacmap-mcp.sock
```

Point the client at `http://127.0.0.1:8765/mcp` with header `Authorization: Bearer $BACMAP_MCP_TOKEN`. The HTTP transport refuses to start when no token is set.

### Profiles: what a client can see (v1.5)

Each MCP server instance is bound to one **profile**, chosen at launch. The client cannot change it, because the model behind an MCP client may be a cloud model that bacmap cannot verify (ADR-16).

| Profile | Tools visible | How to enable |
|---|---|---|
| `cloud` (default) | read/compute tools whose output data class is ≤ `[llm.data_policy].cloud_max_data_class` (D1 by default, at most D2). Out of the box this means `bio_list_reference_genomes` and `bio_diagnose`, plus the task tools | nothing to do |
| `local-trusted` | all read/compute tools up to D4 (sequences, metadata, lab results) | the administrator sets `[mcp] allow_local_trusted = true` in `config.toml`, then launches `bacmap mcp --profile local-trusted`. Without the setting the server refuses to start |

Use `local-trusted` only when the harness talks to a **local or LAN model**. Hidden tools are rejected again at call time. To serve two profiles at once over HTTP, run two instances on different ports with different tokens.

Task submissions are recorded under a server-determined identity (`mcp-stdio:<profile>:<OS user>` or `mcp-http:<profile>`); `bacmap_submit_task` no longer accepts a `submitted_by` argument.

Once connected, agents can call (under `local-trusted`; `cloud` shows the D0–D1/D2 subset):

| Category | Tools | Notes |
|---|---|---|
| Capabilities | `bacmap_capabilities` | Version, profile and data-class ceiling, plannable task types, long-task mechanism — call it first |
| Read/compute (22) | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` `bio_compare_runs` … | Return results synchronously; accept any local path |
| Plans (v1.5.1) | `bacmap_create_plan` `bacmap_revise_plan` `bacmap_get_plan` | **Recommended write path**: the agent proposes typed analyze/curate tasks; nothing runs until a person confirms the exact version in bacmap |
| Task submission | `bacmap_submit_task` | Compatibility entry (direct submission); analyze/curate tasks run asynchronously |
| Task queries | `bacmap_task_status` `bacmap_task_result` | Status (under `cloud` the message is withheld); result summary with run ID and gate verdicts (counts only under `cloud`) |
| Task control | `bacmap_task_cancel` | Cancel a running task this client submitted, directly or through its own plan |

Agents can also fetch domain guidance via MCP prompts: each delivered role (analyst / curator / miner / literature / writer / epidemiologist) exposes its instructions as a `bacmap_role_<name>` prompt (global principles + permission boundary + SKILL guidance). The raw `SKILL.md` files are also published as resources `skill://bacmap/<role>/SKILL.md`, each with a `sha256` digest in its metadata. Per-harness setup is in the [agent harness guide](harnesses.md).

Security model (identical for every client):

- The MCP channel has **no direct writes**: store writes happen only through task submission and the six gates;
- For untrusted clients, connect `bacmap mcp --read-only` first (query tools only);
- MCP only protects data that flows through MCP. Harnesses bring their own shell and file tools, so run bacmap under a dedicated system account whose `BACMAP_HOME` the harness user cannot read, and connect the harness over HTTP with a token (ADR-21);
- Confirm plans and sign approvals in the bacmap Web console or CLI, not in the harness chat;
- Connectivity troubleshooting: `hermes mcp test bacmap`.

### Plans: propose in the harness, confirm in bacmap (v1.5.1)

1. The agent calls `bacmap_create_plan` with typed tasks, for example
   `{"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}`. Plannable types:
   `analyze` (exactly one of `samples` / `fasta_dir` / `fastq_dir`), `curate` (`scope` =
   `pathogen`/`strains`), **`mine`** (`objective`, `script`, optional absolute `input_paths`,
   `sandbox_image`) and **`write`** (`objective`, `draft`). The reply carries `plan_id`, `version`
   and `plan_hash`.
2. The person reviews and confirms **that exact version** in bacmap:

   ```bash
   bacmap plan ls                                   # latest version of each plan
   bacmap plan show <plan_id>                       # full parameters, hash, input fingerprints
   bacmap plan confirm <plan_id> --version 1 --hash <first 12 chars>
   bacmap plan confirm <plan_id>                    # or: show the plan, then confirm interactively
   bacmap plan reject <plan_id> --version 1 --reason "wrong sample"
   ```

   The Web console offers the same under **计划 / Plans** (`/plans`), with CSRF protection in cookie mode.
3. The agent polls `bacmap_get_plan` for `task_ids`, then `bacmap_task_status`.

Guarantees: a revision (`bacmap_revise_plan`) creates a new version and the old one can no longer be
confirmed; if an input directory (or a `mine` input file) changes between creation and confirmation,
confirmation fails with a conflict; confirming twice (or from CLI and Web at the same time) submits
the tasks only once.

Open-path plans (`mine` / `write`) are shown **in full** at confirmation — the sandbox script or the
draft text is part of the plan hash, so what you read is what runs. `mine` executes with no network
inside the sandbox and its artefacts still go through the mining gate and your signature.

### Runs and GOM: the evidence trail (v1.7.1)

```bash
bacmap run ls                                  # recent run records
bacmap run show <run_id>                       # parameters, tool/db versions, input hashes, seeds
bacmap run compare <run_a> <run_b>             # attribute differences to params/db/tool/input
bacmap gom ls --type analysis                  # latest version of each GOM object
bacmap gom show <object_id> [--version N]      # full object payload
```

The Web console mirrors this at **Runs** and **GOM**, with a compare form on the run page. Every
analyze run writes one immutable record (ADR-18); GOM objects are immutable too — new results create
new versions rather than overwriting.

A typical exchange with an agent:

> "Run the full analysis for SAM-TYP-001" → the agent calls `bacmap_submit_task`(analyze) → gets a task_id
> → polls `bacmap_task_status` → "Completed, the report is in results/SAM-TYP-001/report/"

## 6. Four task types and their gates

| Task | What it does | Key gate |
|---|---|---|
| `analyze` | Full pipeline: QC→assembly→typing→AMR/virulence→report. An HTML report is **generated automatically at the end of the task** (`results/{id}/report/{id}_report.html`) | Analysis-conclusion gate (contradictory interpretations are flagged for human review) |
| `curate` | Build the local epidemiological baseline library (de-identification, aggregation) | **Release gate**: anything below the gold-standard thresholds is refused release |
| `mine` | Run custom analysis scripts inside the sandbox | **Signature gate**: unsigned output must not enter reports |
| `write` | LLM drafts reports / briefs | **Citation gate**: exports are refused if they cite entries absent from the knowledge base |

Checkpoint resume: the task engine is built on DBOS. Kill a running process and restart it, and the task continues from its checkpoint (verified in V2).

**Closed vs open paths: the LLM's capability boundary.** The four task types split into two
execution shapes: `analyze`/`curate` take the **closed path** (a fixed Snakemake DAG whose rule
set is a frozen decision — no runtime additions or edits); `mine`/`write` take the **open
path** (LLM-generated scripts/text under sandbox and gate constraints). The division of labor
has three layers:

| Layer | The LLM may | Deliberately may not |
|---|---|---|
| Planning (before submit) | choose which tasks, which samples, which parameters; compose at the **task level** within one plan (e.g. `analyze → mine(stats) → mine(charts) → write(report)`) | pick or combine DAG rules; touch pipeline logic beyond parameters |
| Execution — `analyze` | — (the closed DAG runs as-is) | there is no entry point for runtime pipeline building |
| Execution — `mine` | write arbitrary Python over **already-produced** data (stats, cross-checks, plots) | the sandbox is offline and the default image (python:3.12-slim) ships no bio tools — an improvised bioinformatics pipeline cannot be assembled |

Why runtime orchestration by the LLM is blocked: ① every `analyze` run is sealed into a run
record with seeds, tool versions, and hashes (ADR-18) — improvised pipelines cannot be sealed
or reproduced; ② fixed outputs can pass deterministic verifiers and gates, while free-form
ones have no predefinable checks; ③ bioinformatics is externalized to gside/gapit/gmlst, and
the orchestration itself must stay deterministic and versioned (ADR-20). **The right path for
a new analysis capability is a developer action**: add an `.smk` rule + adapter + tests →
versioned deploy (tree-hash stamp) → it joins the closed set — after which every analyze task
and the assistant's planning can use it automatically.

## 7. End-to-end example (new sample on the sequencer → report)

```bash
# ① 布局数据并注册（reads 样本；已组装 FASTA 则登记 assembly 列，R1/R2 留空）
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz\t" \
  >> ~/.local/share/bacmap/workflows/bacmap/config/samples.tsv

# ② 提交（Web 表单选 analyze 填 SAM-NEW-100，或智能体对话）
# ③ 监控直至完成；待审批任务在详情页签字
# ④ 取报告
ls ~/.local/share/bacmap/results/SAM-NEW-100/report/
```

## 8. Known capability boundaries (external tool dependencies)

| Field / capability | Status | Waiting on |
|---|---|---|
| Species identification (marker/panel/mash profiles) | ✅ integrated via gside | none |
| Serotype | ⏳ `pending_gapit` placeholder | gapit serotype subcommand (in development) |
| Genome annotation | ⏳ `pending_external_tool` placeholder | gapit annotation subcommand |
| Species identification GTDB-Tk standard profile / classification | ⏳ `pending_gside` placeholder | gside GTDB-Tk profile |

The pipeline keeps running on these fields and emits placeholder values. Once the external capability is ready, only the rules need replacing; no architectural change required.

## 9. Troubleshooting FAQ

**Submission & forms**

| Symptom | Cause / fix |
|---|---|
| "非法样本 ID" rejected | The ID contains characters outside `A-Za-z0-9._-`, or you separated IDs with a **full-width comma** — use ASCII `,` or newlines |
| Not sure what the sample-list field takes | **Registered sample IDs** (the name used in samples.tsv / the `gs/` layout), not paths; see §4 task form details |
| Want to submit mine from the form | Form/CLI/MCP deliberately accept only analyze/curate; ask an external harness for a mine plan (confirmed), or use the Python API |

**LLM endpoints & agents** (setup tutorial and full table: installation guide §5)

| Symptom | Cause / fix |
|---|---|
| `payload D4 exceeds cloud limit` | Data-class block (ADR-16); in-task agents and cloud MCP instances trim their tool belt automatically — if you see this, upgrade first |
| 401 / 429 (1113) / model-not-found | Key not injected, key/endpoint mismatch (GLM standard vs coding endpoint), or no quota for the model — installation guide §5.2 |
| "LLM 不可用 / degraded" | The unified degrade notice; check the endpoint with `bacmap overview` (deterministic functions keep working, C3) |
| Want streaming conversation | Conversation lives in the harness (ADR-21); bacmap only streams domain events via `/api/v1/events/stream` |
| The agent says it cannot read a path "for security" | By design: external data goes through mine registration (§2); if the task then says "sandbox unavailable", install podman (installation guide §6) |
| mine task fails with a bare "workflow ERROR" | Older builds collapsed environmental failures into that generic message; the task message now names the cause and remedy (e.g. "沙箱启动失败: no apptainer/podman on PATH → install podman") — upgrade and resubmit |

**Samples & data**

| Symptom | Cause / fix |
|---|---|
| analyze cannot find FASTQs | The sample is not registered: follow the `gs/<ID>/<ID>_R{1,2}.fastq.gz` layout or register in samples.tsv (§7, configuration guide §5); **pre-assembled FASTA can enter the closed path via the `assembly` column** (v1.4.33, skips QC/assembly) |
| A registered dataset no longer readable | The original file was moved/deleted (zero-copy registration depends on the original path); detect with `bio_inspect_dataset verify=true` |
| A task is stuck at "pending approval" | Normal: the mining/release gate awaits a human signature — use the approval card on the detail page (§4) |
