**English** | [简体中文](tutorial.zh-CN.md)

# No commands required: doing pathogen genomics with an agent

> bacmap exists to remove two everyday pains: **nobody wants to memorise bioinformatics CLIs**, and
> **data and results end up scattered with no traceable history**. This tutorial does the work in
> natural language from start to finish. The command line appears only in the last section — and you
> can skip it.

## 1. Who does what

```
you (natural language) → agent (Hermes / Pi / DSH) → MCP → bacmap
                                                     ├─ proposes a "plan"
                                                     ├─ you confirm (human, trusted surface)
                                                     ├─ deterministic execution (Snakemake/tools)
                                                     └─ gates + evidence (run records, GOM, signatures)
```

- **You**: say what you need, confirm the plan, sign conclusions.
- **The agent**: understands, looks around, proposes plans, writes scripts/drafts, explains results.
- **bacmap**: turns a plan into reproducible execution, turns output into evidenced facts, and keeps
  dangerous actions behind gates.

You never need the flags for `snakemake`, `shovill` or `gside`; you need to describe the problem and
point at the data.

## 2. One-time setup (ten minutes)

```bash
pixi install && pixi shell     # install bacmap itself (the only command you must type)
bacmap doctor                  # health check: home, databases, sandbox, model, disk
```

Then connect one agent (pick one; configuration in the [harness guide](harnesses.md)):

- **Hermes** — result checks and notifications from a phone IM;
- **Pi** — the most comfortable terminal assistant;
- **DeepSeek Harness** — a friendly web UI.

Ask it "which bacmap tools can you see?" — it should list plan, task and result tools. With a cloud
model it starts with D0–D1 tools only; a local/LAN model can use `local-trusted` (§9).

## 3. A complete walkthrough: from launching Hermes to a report

This path is copy-pasteable. Assume bacmap lives in `/home/you/bacmap` and data in `/data/run42`.

### 3.1 Point Hermes at bacmap (once)

Edit `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  bacmap:
    command: /home/you/bacmap/.pixi/envs/default/bin/bacmap
    args: ["mcp"]                 # add "--profile", "local-trusted" for local models
```

Verify:

```bash
hermes mcp test bacmap
```

```
✓ Connected (1939ms)
✓ Tools discovered: 10
  bio_list_reference_genomes, bio_diagnose,
  bacmap_capabilities, bacmap_create_plan, bacmap_revise_plan, bacmap_get_plan,
  bacmap_submit_task, bacmap_task_status, bacmap_task_cancel, bacmap_task_result
```

Two things to know:

1. Hermes needs its **own** model configuration (`/model` or `/login` inside Hermes). That is separate
   from bacmap's `config.toml` endpoint, which only powers in-task interpretation.
2. The default `cloud` profile exposes these 10 tools; not seeing `bio_get_result` is expected (data classes).

### 3.2 Launch and state the request

```bash
hermes
```

In the chat, give an **absolute path**:

> Analyse the eight *V. parahaemolyticus* read sets in /data/run42 with the standard pipeline.

Hermes first calls `bacmap_capabilities`, then tries to create a plan. If the path is wrong it receives a
clear `validation_error` (for example `directory not found: /data/run42`) and relays it to you.

### 3.3 The plan it returns

The tool call appears as `mcp__bacmap__bacmap_create_plan`, returning:

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "tasks": [{"task_type": "analyze", "fastq_dir": "/data/run42", "species": null}],
  "plan_hash": "c1d2e3f4a5b6... (64 chars)",
  "next_step": "Ask the user to review and confirm this exact version in bacmap itself: `bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6` (or the Web console). You cannot confirm it; poll bacmap_get_plan for task_ids after confirmation."
}
```

Hermes will phrase it as "the plan is ready; confirm it in bacmap" — **it cannot confirm**, by design.

### 3.4 You confirm without leaving the chat

The plan carries a `confirm_url`; opening it lands on the Web plan page (already logged in), where
you read the full parameters and click confirm:

```
http://127.0.0.1:8800/plans/9a3f2c1b7d4e4f60?version=1
```

Three ways to confirm, easiest first:

1. **Web link** (default): click, confirm, return to Hermes;
2. **Local dialog** (workstation with a GUI): tell Hermes "confirm with a local dialog"; it calls
   `bacmap_confirm_plan_locally` and you click approve in the system dialog (stdio sessions only);
3. **Pre-authorisation** (admin option): with `[plans.auto_confirm]` in `config.toml`, analyze-only
   plans over **already registered samples** within the sample limit are confirmed automatically
   (`actor=policy:auto-confirm`); directory ingestion, scripts, mine/write/releases still require a
   human.

Plans are per-client: if you switch to another harness, it cannot read or revise a plan created by
the first one. Confirm or finish it with the same client, or create a fresh plan.

Asking for the local dialog sounds like this:

> **You**: "Pop up the confirmation dialog on this machine."
>
> **Agent**: (calls `bacmap_confirm_plan_locally`) "Dialog opened for plan v1, hash c1d2e3f4a5b6."

Click **Confirm and submit** and it returns `state=submitted` plus task IDs; cancelling leaves the plan
pending and hands you the Web link as a fallback. The tool is only available when Hermes is connected as
a local (stdio) process.

The terminal command remains as a fallback:

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
```

### 3.5 Back in Hermes: follow the run

> Confirmed — watch the run and tell me when it finishes.

It calls `bacmap_get_plan` for the `task_ids`, then polls `bacmap_task_status`. A typical reply:

> Five of eight samples finished, three are assembling, nothing failed.

When done:

> Summarise the results, focusing on serotype and resistance.

Hermes calls `bacmap_task_result` (the cloud profile returns gate counts only; a local profile returns
per-sample verdicts) and points you to the Web sample page or `bacmap sample show HZCPE-01` for the report.

### 3.6 If it says it cannot see some tools

You are on the `cloud` profile:

- **Cloud model in Hermes**: that is the red line working; planning and explanation only. To read
  single-strain results, an administrator may raise `cloud_max_data_class` to `"D2"` (maximum).
- **Local/LAN model**: set `[mcp] allow_local_trusted = true` in `config.toml`, change `args` to
  `["mcp", "--profile", "local-trusted"]`, and restart Hermes.

## 4. Follow-up questions: make it read and compare

No tool names needed:

| You say | It does |
|---|---|
| "Any carbapenemases in this batch?" | searches ingested resistance genes |
| "Is HZCPE-03 related to last year's O3:K6 strains?" | cgMLST allele distance + thresholds (says "undetermined" when no threshold exists) |
| "Why do these two runs differ?" | compares run records: parameters, databases, tools, inputs |
| "Tabulate ST and serotype for all eight" | reads results and summarises (may propose a small script) |
| "Which samples need my review?" | lists audit flags and the reason |

Answers carry **evidence**: sample, `run_id`, database version. You can always ask "on what basis?".

## 5. Data management: hand over what only you know

Where an isolate came from, lab results, supporting papers — just say it:

> **You**: "HZCPE-01 was collected on 12 Oct 2026 from a seafood market in Shenzhen."
>
> **Agent**: (calls `bacmap_record_data`, which submits a `record` task) "Recorded. Add a
> susceptibility result too?"

> **You**: "Meropenem MIC 0.25 mg/L, interpreted S."
>
> **Agent**: "Recorded (lab_result)."

> **You**: "Add this O3:K6 paper: PMID 12345678."
>
> **Agent**: "Staged as entry 12; it becomes citable only after review. Approve now?"

All writes go through the task layer: they are auditable, not "the agent edited the database".

When the information is complete:

> **You**: "Summarise our local *V. parahaemolyticus* into a baseline release and see whether it can ship."
>
> **Agent**: (*curate* plan) "12 isolates included, 1 excluded for incomplete metadata; release
> requires your signature."

**Multiple sequencing runs of one strain are never double-counted**: bacmap groups by isolate, picks
one representative run, and records which one and why.

## 6. Deep analysis: it writes the script, you review it

For questions the standard pipeline does not cover:

> **You**: "Summarise local *V. parahaemolyticus* by ST, plot the distribution, and check for new
> clone groups after 2025."

The agent submits a `mine` plan containing the **entire script**. You do not need to write Python,
but do one thing: read what the script does (which files it reads, what it writes). After confirmation
it runs in a network-less sandbox; the artefacts pass the mining gate and need your signature.

Iterate conversationally:

> **You**: "The plot is unreadable — facet by year, and merge STs with fewer than three samples into
> 'other'."
>
> **Agent**: (revises the plan; the script diff is visible) "Confirm and I will rerun."

## 7. Reports: it drafts, gates verify

> **You**: "Draft a weekly report for my director from these results and papers — emphasise the
> outbreak cluster and resistance."
>
> **Agent**: (*write* plan) "Draft ready; every citation comes from approved entries; the citation
> gate passed; waiting for your signature."

Unapproved papers and citations unknown to the local knowledge base are rejected by the citation gate
— that is how "it looks plausible" stops being evidence.

## When something breaks, ask it first (natural-language troubleshooting)

You do not have to read logs. Describe the symptom; the agent calls the task/diagnostic tools and
comes back with a cause and the next step:

> **You**: "The analysis task failed — what happened?"
>
> **Agent**: (`bacmap_task_status`) "Task `3f9c…` failed with `sandbox_unavailable`; install a sandbox
> backend (Apptainer or Podman) — passthrough is for development only."

On the cloud profile it cannot see the raw message (it may contain sample IDs or paths) but it does
receive a **redacted failure kind and suggested fix**; on `local-trusted` it also sees the full message
and can call `bio_diagnose` to parse the Snakemake log.

Typical conversational fixes:

| Symptom | You say | What it does |
|---|---|---|
| Task failed | "Why did it fail?" | Returns failure kind and fix command; does not install anything for you |
| No sandbox | "Which sandbox should I install?" | Suggests `pixi global install podman`, explains passthrough risk |
| Path missing | "It says the directory does not exist" | Points at `validation_error: directory not found`; you fix the absolute path and re-plan |
| Dataset id collision | "Why won't it accept this file?" | Explains the collision, suggests `<isolate>__<platform>__<date>` |
| Confirmation conflict | "It says the input changed" | Explains the directory changed after planning; proposes a revision (`bacmap_revise_plan`) to re-confirm |
| Data blocked | "Why can't it see the sequences?" | Explains the D3/D4 red line; local profile or raise the cloud cap to D2 (admin) |
| Stuck running | "Is it hung?" | Checks status/reconciliation; if needed proposes cancellation and the impact |
| Wants full logs | "Give me the full error" | Cloud explains the limit; local profile or `bacmap doctor` shows details |

**Boundary**: the agent may diagnose, propose and revise plans, but it never edits the database,
bypasses gates or signs for you. It gives you the next step; execution and approval stay with you.

## 8. Three actions that always stay yours

1. **Confirm the plan** — after reading the full parameters (including script/draft text);
2. **Sign releases** — baseline, mining artefacts, exported reports;
3. **Audit** — every claim traces to a run record and a GOM version.

## 9. Why some tools are invisible

That is the data red line, not a capability gap:

| Where your model runs | Default tools | To see more |
|---|---|---|
| Cloud API | D0–D1 (plans, tasks, public info) | an administrator raises `cloud_max_data_class` to `D2` (the maximum) |
| Local / LAN | `local-trusted`: single-strain results, sequences, metadata | set `[mcp] allow_local_trusted = true` in `config.toml` |

Sequences (D3) and personal data (D4) never go to a cloud model — which is exactly why analysis runs
locally and the model handles understanding and explanation.

## 10. When you still use the CLI or web console

- **Deployment, health checks, backup, upgrade**: `bacmap doctor`, `backup`, `restore`
  ([operations guide](operations.md));
- **No agent available**: the Web console covers submission, confirmation, approval and reports;
- **Automation/batch**: CLI and `/api/v1` ([usage guide](usage.md)).

They are the fallback, not an "expert-only" tier.

## 11. Things you can simply say

- "Which Salmonella do we have locally, and what arrived in the last three months?"
- "Run the standard analysis on every assembled genome in /data/batch7."
- "What are HZCPE-02's serotype and resistance genes? Compare with HZCPE-01."
- "Is there a clone cluster in this batch? Give me distances and the reasoning."
- "Cross-tab ST by source for everything since 2025."
- "Add metadata for this isolate: 12 Oct 2026, Shenzhen, food, seafood."
- "Draft this week's surveillance brief; use approved papers only."
- "Which CARD version did that earlier run use?"
- "Pop up the local confirmation dialog for this plan."
- "Which tasks are waiting for my approval?"
- "Back up results and raw data to /backup."

## 12. One line to remember

> **You describe → it proposes → you confirm → bacmap executes and records → you sign.**
>
> If you forget the commands, remember three things: **where the data is, what you need, and who signs.**

Further reading: [usage guide](usage.md) · [agent harnesses](harnesses.md) · [operations](operations.md) · [tool reference](tools.md)
