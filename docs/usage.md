**English** | [简体中文](usage.zh-CN.md)

# Usage guide

bacmap has three entry points: the **CLI** (operations), the **web task console** (humans), and **MCP** (AI agents).

## 1. CLI

```bash
bacmap --version
bacmap web [--host 127.0.0.1] [--port 8800]   # Web 任务台（默认仅绑本机）
bacmap mcp [--read-only] [--home H]           # stdio MCP 服务器（智能体接入用）
```

## 2. Web task console (the main interface for humans)

Run `bacmap web`, then open `http://127.0.0.1:8800` in a browser:

1. **Submit a task**: pick the task type in the form on the left and fill in the sample list (analyze) or a scope JSON (curate)
2. **Monitor**: the task table on the right shows live status with six state badges (queued / running / pending approval / completed / failed / canceled); open a detail page and it refreshes itself every 2 seconds
3. **Approve**: when a task reaches `pending approval`, an amber approval card appears on the detail page. Fill in the approver, the decision (approve/reject), and the signature passphrase. After submission the task passes the mining gate / release gate and proceeds

> Approval is one of the six gates: unsigned mining output cannot enter a report, and a
> baseline library that misses the gold standard cannot be released. That is by design
> (agents cannot sign off on their own), not a fault.

### Remote access: SSH tunnel (the recommended way)

`bacmap web` binds to `127.0.0.1` only by default (ADR-16). If you need to reach it from
another computer, do **not** expose it bare with `--host 0.0.0.0` (the UI has no
authentication, so anyone on the LAN could submit or approve tasks). Use an SSH tunnel
instead: SSH carries all of the encryption and authentication, and bacmap needs zero changes:

```bash
# 在你自己的电脑上执行（user 为工作站账号，10.0.0.5 换成工作站实际 IP）：
ssh -L 8800:127.0.0.1:8800 user@10.0.0.5
# 保持连接，然后本地浏览器打开 http://127.0.0.1:8800
```

- Each user builds their own tunnel; tunnels do not interfere with each other
- Traffic is encrypted the whole way, which satisfies the requirement that genomic data (D3/D4) never leaves the local network and never appears in plaintext
- No root needed, no firewall port to open on the workstation, no authentication layer added to bacmap
- Data files are still registered on the workstation by the operator, per [configuration guide §5](configuration.md); remote upload is a planned feature (to be considered once the agent-side bioinformatics analysis features are done)

## 3. MCP agent access

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

Once connected, agents can call **22 tools**:

| Category | Tools | Notes |
|---|---|---|
| Single-step compute (20) | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` … | Return results synchronously; accept any local path |
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

## 4. Four task types and their gates

| Task | What it does | Key gate |
|---|---|---|
| `analyze` | Full pipeline: QC→assembly→typing→AMR/virulence→report | Analysis-conclusion gate (contradictory interpretations are flagged for human review) |
| `curate` | Build the local epidemiological baseline library (de-identification, aggregation) | **Release gate**: anything below the gold-standard thresholds is refused release |
| `mine` | Run custom analysis scripts inside the sandbox | **Signature gate**: unsigned output must not enter reports |
| `write` | LLM drafts reports / briefs | **Citation gate**: exports are refused if they cite entries absent from the knowledge base |

Checkpoint resume: the task engine is built on DBOS. Kill a running process and restart it, and the task continues from its checkpoint (verified in V2).

## 5. End-to-end example (new sample on the sequencer → report)

```bash
# ① 布局数据并注册
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz" \
  >> ~/.local/share/bacmap/workflows/config/samples.tsv

# ② 提交（Web 表单选 analyze 填 SAM-NEW-100，或智能体对话）
# ③ 监控直至完成；待审批任务在详情页签字
# ④ 取报告
ls ~/.local/share/bacmap/results/SAM-NEW-100/report/
```

## 6. Known capability boundaries (external tool dependencies)

| Field / capability | Status | Waiting on |
|---|---|---|
| Species identification (marker/panel/mash profiles) | ✅ integrated via gside | none |
| Serotype | ⏳ `pending_gapit` placeholder | gapit serotype subcommand (in development) |
| Genome annotation | ⏳ `pending_external_tool` placeholder | gapit annotation subcommand |
| Species identification GTDB-Tk standard profile / classification | ⏳ `pending_gside` placeholder | gside GTDB-Tk profile |

The pipeline keeps running on these fields and emits placeholder values. Once the external capability is ready, only the rules need replacing; no architectural change required.
