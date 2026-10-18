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
bacmap task ls|show|submit|approve|cancel          # 任务查询与写操作（显式、无 LLM）
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web 控制台（含助手）
bacmap mcp [--read-only] [--home H]                # MCP 服务器（stdio/HTTP）
```

Query subcommands accept `--json`. Writes always go through the same gates as Web/MCP.

Top-level commands fall into two kinds: **interfaces/modes** (`mcp`, `web`, `tui`, `console`)
that take over a terminal or bind a port, and **commands** (`overview`, `task`, `sample`,
`search`, `ask`, `chat`) that perform one query or write and exit. `bacmap` itself *is* the
CLI, so commands stay at the top level (`bacmap task ls`) rather than nested under a `cli`
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

The assistant cannot read arbitrary host paths. To use data you provide:

1. Have it plan a `mine` task with the path in `input_paths` — the task registers it
   **zero-copy** (per-file SHA256) and bind-mounts it read-only into the sandbox at
   `/input/<dataset_id>`.
2. Inspect what was registered with `bio_inspect_dataset`; pass the `dataset_id` to
   `sandbox_run` (its `datasets` argument), or have the script read the mount from
   `context.json`.
3. `bio_inspect_dataset` with a `dataset_id` and `verify=true` recomputes SHA256 to detect
   content changes.

The registry lives in the GOM DB. Hashes are SHA256 and are **evidence** (a fingerprint for
integrity/dedup), not a way to recover a deleted original — ask for materialization (a copy)
if you need durability or portability.

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
   with detected genes, HTML report download); Search finds samples by keyword or filters.
3. **Approve**: when a task reaches `pending approval`, an amber approval card appears on the detail page. Fill in the approver, the decision (approve/reject), and the signature passphrase. After submission the task passes the mining gate / release gate and proceeds

> Approval is one of the six gates: unsigned mining output cannot enter a report, and a
> baseline library that misses the gold standard cannot be released. That is by design
> (agents cannot sign off on their own), not a fault.

### Remote access: SSH tunnel (the recommended way)

`bacmap web` binds to `127.0.0.1` only by default (ADR-16). If you need to reach it from
another computer, do **not** expose it bare with `--host 0.0.0.0` (the UI has no
authentication, so anyone on the LAN could submit or approve tasks). Use an SSH tunnel
instead: SSH carries all of the encryption and authentication, and bacmap needs zero changes:

> `BACMAP_WEB_TOKEN` (`--token-env`) adds authentication. In the default `bearer` mode it is
> sent as an `Authorization` header, which **browsers cannot set** — so the HTML console
> returns 401 and the tunnel-first workflow below is the way in. Set
> `BACMAP_WEB_AUTH=cookie` to instead log in at `/login` (signed `HttpOnly` session cookie +
> CSRF token on every state-changing POST); with `BACMAP_WEB_COOKIE_SECURE=1` add `Secure`
> for TLS deployments.

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

## 7. End-to-end example (new sample on the sequencer → report)

```bash
# ① 布局数据并注册
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz" \
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
