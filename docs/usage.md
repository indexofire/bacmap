**English** | [简体中文](usage.zh-CN.md)

# Usage guide

bacmap has three entry points: the **CLI** (operations), the **web task console** (humans), and **MCP** (AI agents).

## 1. CLI

```bash
bacmap --version
bacmap ask "跑 SAM-001 的分析并和去年暴发株比较"   # LLM 规划 → 确认 → 提交
bacmap chat                                        # 多轮对话式分析助手
bacmap tui [--home H]                              # 全屏 TUI（Textual）
bacmap console [--home H]                          # 交互式菜单
bacmap overview [--json]                           # 系统概览
bacmap task list|show|submit|approve|cancel         # 任务查询与写操作（显式、无 LLM；list alias ls）
bacmap task show <short-prefix>                    # IDs accept git-style prefixes: the 12 chars shown by list just work; lengthen on ambiguity
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web 控制台（含助手）
bacmap mcp [--read-only] [--home H]                # MCP 服务器（stdio/HTTP）
```

Query subcommands accept `--json`. Writes always go through the same gates as Web/MCP.

Top-level commands fall into two kinds: **interfaces/modes** (`mcp`, `web`, `tui`, `console`)
that take over a terminal or bind a port, and **commands** (`overview`, `task`, `sample`,
`search`, `ask`, `chat`) that perform one query or write and exit. `bacmap` itself *is* the
CLI, so commands stay at the top level (`bacmap task list`) rather than nested under a `cli`
subcommand; `web`/`tui`/`console` are sibling interaction modes.

## 2. LLM-driven assistant (CLI ask/chat, TUI Chat, Web /assistant)

The built-in assistant turns a natural-language analysis need into an executable plan.
It is the shared **agent session** (`agent/session.py`) used by all three interfaces
(ADR-10 planner + ADR-11 open path):

1. **Understand + look around**: the LLM may call read tools (`bio_list_samples`,
   `bio_get_result`, `bio_search_samples`, `bio_query_metadata`, `bio_review_flags`,
   `bio_compare_runs`) to ground itself.
2. **Plan & execute**: it returns a structured plan of closed task types — `analyze` (standard
   Snakemake pipeline) or `curate` for most requests; `mine` for deep mining where it writes a
   Python script to run in the sandbox (multiple sequential `mine` tasks for multi-step work);
   `write` for documents. During planning it can also call **`sandbox_run`** to execute a script
   (no network) and read back stdout/artifacts — so it can iterate on statistics and **render
   charts (PNG/CSV)** before proposing a `mine` task that goes through the mining gate.
3. **Clarify**: when the request is ambiguous it asks instead of guessing.
4. **Confirm (risk-tiered)**: reads/analysis-of-existing-results run inside planning;
   **writes are only submitted after confirmation** (`bacmap ask` prompts, add `--yes` to
   skip; TUI: `Ctrl+Y` or the button; Web: the confirm button).
5. **Degrade (C3)**: if the LLM endpoint is unavailable, the assistant says so and you fall
   back to the explicit subcommands / task form — the deterministic path always works.

**Streaming output & thinking indicator (v1.4.31; v1.4.32 thinking inline in the main
view)**: TUI chat and CLI `ask`/`chat` consume an event stream — model thinking deltas
(native reasoning streams such as GLM's) stream **inline in the conversation view** (dim
italic; the full text **stays visible** when the turn ends, `Ctrl+T` collapses/expands the
most recent one), the reply types out in place and is finalized with
the authoritative text, and tool calls appear as an activity line (e.g.
`⠋ 调用 bio_list_samples…`); `Esc` cancels the in-flight request. Web `/assistant`
remains a full-page round trip for now. The structured-plan contract is unchanged (ADR-10
planner; streaming is presentation-only — the final result is still fully validated by
pydantic-ai).

**Assistant on a cloud endpoint (v1.4.30)**: when the assistant routes to a `cloud` endpoint
(GLM, DeepSeek, …), its tool belt is trimmed against `cloud_max_data_class` — the D4
metadata/lab-result queries (`bio_query_metadata`, …) and the D3 dataset inspector
(`bio_inspect_dataset`) stay out of the session, sandbox tools (`sandbox_run`/`sandbox_shell`)
are excluded entirely, and the session data class is ≤D2; local/lan endpoints keep the full
belt. For full sample-query and planning capability on cloud, the administrator relaxes
`cloud_max_data_class` to `"D2"` (the maximum, configuration doc §3). The ADR-16 red line is
unchanged: D3/D4 data never reaches a cloud endpoint under any configuration.

Example:

```bash
$ bacmap ask "把本地沙门菌按 ST 统计并画图"
bacmap › 建议先统计再绘图。
建议执行的分析计划：
  1. mine —— 按 ST 聚合本地沙门菌并输出统计 CSV
  2. mine —— 由统计 CSV 绘制 ST 分布图
确认提交该计划？ [y/N]
```

### Giving the assistant a data path

The assistant cannot read arbitrary host paths — by design (ADR-11: raw data is D3 and never
enters LLM context), not a fault. The single entry point for external data is the `mine`
task's `input_paths` parameter. **Just give the path in conversation**:

```bash
$ bacmap ask "读取 /data/2026批次/st_list.csv，按 ST 统计样本数并画柱状图"
bacmap › 收到。/data/... is an external path; a mine task is required:
       zero-copy registration (SHA256) → read-only mount into the sandbox → stats inside.
建议执行的分析计划：
  1. mine —— register the CSV as an input dataset; group by ST, emit st_counts.csv + st_counts.png
确认提交该计划？ [y/N]
```

After confirmation the task runs: **register → read-only mount → script in sandbox →
artifacts in the workspace → mining gate awaits your signature**. The script locates data
via the workspace `context.json` `datasets` mapping (`id → path` — an **object, not an array**).

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
it with zero further configuration. The cloud GLM assistant can *plan* mine tasks, but cannot
inspect registered datasets (D3 tools are trimmed on cloud) or iterate scripts in-session —
for a "look at the data, then adjust the script" workflow, configure a local/lan endpoint.

Besides `sandbox_run` (a Python script), a restricted **`sandbox_shell`** runs a single shell
command inside the same sandbox — only read/analysis commands (`ls`, `cat`, `grep`, `zcat`,
`samtools`, `seqkit`, `python`, …) are allowed; anything else is refused and should become a
signed `mine` task. It only runs with a real container backend (passthrough is refused by
default) and every invocation is written to `$BACMAP_HOME/audits/sandbox_shell.jsonl`.

## 3. TUI and interactive console

`bacmap tui` starts a chat-first Textual workspace (inspired by opencode's TUI and the hermes
agent REPL): a **status header** (LLM endpoint), a collapsible **sidebar** (Tasks / Samples),
the **conversation**, a **plan hint**, and the **prompt**, with a **footer** of key hints.

- **Direct keys**: `Enter` send · `Shift/Alt+Enter` newline · `Esc` interrupt / ignore the
  pending plan · `Ctrl+C` quit · `Ctrl+B` toggle sidebar · `Ctrl+R` refresh · `Ctrl+L` clear
  conversation · `Ctrl+F` toggle follow (stop auto-scroll while reading back) · `Ctrl+P`
  command palette · `Ctrl+Y` confirm the pending plan. The input box is **focused on start**,
  so you can type immediately.
- **Leader `Ctrl+G`** chords: `n` new session · `i` focus input · `l` tasks · `s` samples ·
  `m` model/endpoint · `t` theme · `h` help · `q` quit.
- **Failure echo**: when a submitted task ends `failed`/`cancelled`, the conversation gets one
  line — `任务 <id> failed（<step>）：<reason>` — so you need not watch the sidebar.
- **Slash commands** in the prompt: `/help /new /clear /tasks /samples /search <kw> /model`
  `/analyze <样本> /curate [scope] /quit` (the `/analyze` and `/curate` commands are the
  explicit no-LLM path).

The prompt is the assistant: plan → confirm (`Ctrl+Y`) → submit. The sidebar auto-collapses on
narrow terminals and restores your preference when width returns. `bacmap console` remains a
numbered menu for users who prefer prompts over subcommands.

## 4. Web console (tasks / assistant / samples / search)

Run `bacmap web`, then open `http://127.0.0.1:8800` in a browser:

1. **Assistant** (`/assistant`): describe the need in natural language; the page shows the
   assistant's reply and the proposed plan, with a button to confirm and submit (multi-turn
   session kept server-side).
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

**scope** (for `curate`, optional) is a JSON object scoping which samples enter the local
epidemiological baseline: `{"pathogen": "Salmonella"}` filters by species substring;
`{"strains": ["SAM-001", "SAM-002"]}` by explicit list; empty includes every qualifying
sample (strains failing per-strain checks are recorded as excluded). `analyze` ignores it.

**mine/write never go through the form**: they are open paths (script/draft parameters) and
are submitted only via the conversational assistant (after confirmation) or the Python API —
the web form, CLI `task submit`, and MCP deliberately decline them, to prevent forged
requests and script injection.

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

Any client that supports MCP stdio can connect (Hermes / Codex / OpenCode / OpenClaw / Claude, and more). Sample client configurations:

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

Once connected, agents can call **23 tools**:

| Category | Tools | Notes |
|---|---|---|
| Single-step compute (21) | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` `bio_compare_runs` … | Return results synchronously; accept any local path |
| Task submission | `bacmap_submit_task` | **The sole write entry point**; analyze/curate tasks run asynchronously |
| Task queries | `bacmap_task_status` | Poll status and gate messages |

Agents can also fetch domain guidance via MCP prompts: each delivered role (analyst / curator / miner / literature / writer / epidemiologist) exposes its instructions as a `bacmap_role_<name>` prompt (global principles + permission boundary + SKILL guidance).

Security model (identical for every client):

- The MCP channel has **no direct writes**: store writes happen only through task submission and the six gates;
- For untrusted clients, connect `bacmap mcp --read-only` first (query tools only);
- Connectivity troubleshooting: `hermes mcp test bacmap`.

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
| Want to submit mine from the form | Form/CLI/MCP deliberately accept only analyze/curate; mine goes through the conversational assistant (confirmed) or the Python API |

**Assistant & LLM** (setup tutorial and full table: installation guide §5)

| Symptom | Cause / fix |
|---|---|
| `payload D4 exceeds cloud limit` | Data-class block (ADR-16); since v1.4.30 the cloud assistant trims its belt automatically — if you see this, upgrade first |
| 401 / 429 (1113) / model-not-found | Key not injected, key/endpoint mismatch (GLM standard vs coding endpoint), or no quota for the model — installation guide §5.2 |
| "内置助手暂不可用" | The unified degrade notice; run `bacmap ask "hi" 2>&1` — the WARNING lines show the real per-attempt failure |
| No streaming in chat | Streaming is in the TUI and CLI `ask`/`chat` (v1.4.31); Web `/assistant` is still a full-page round trip |
| Assistant says it cannot read a path "for security" | By design: external data goes through mine registration (§2); if the task then says "sandbox unavailable", install podman (installation guide §6) |
| mine task fails with a bare "workflow ERROR" | Older builds collapsed environmental failures into that generic message; the task message now names the cause and remedy (e.g. "沙箱启动失败: no apptainer/podman on PATH → install podman") — upgrade and resubmit |

**Samples & data**

| Symptom | Cause / fix |
|---|---|
| analyze cannot find FASTQs | The sample is not registered: follow the `gs/<ID>/<ID>_R{1,2}.fastq.gz` layout or register in samples.tsv (§7, configuration guide §5); **pre-assembled FASTA can enter the closed path via the `assembly` column** (v1.4.33, skips QC/assembly) |
| A registered dataset no longer readable | The original file was moved/deleted (zero-copy registration depends on the original path); detect with `bio_inspect_dataset verify=true` |
| A task is stuck at "pending approval" | Normal: the mining/release gate awaits a human signature — use the approval card on the detail page (§4) |
