# Architecture

bacmap is a layered monolith. The layers are enforced by import-linter contracts, not just by
convention.

## 1. Layers and dependency direction

```text
interfaces/     CLI · Web · TUI · MCP · views
     │
application/    PlanService, unified errors
     │
tasks/          DBOS engine, gates, records, events
     │
workflow/       Snakemake rules/scripts, workflow runner
     │
tools/          tool registry + bio_* handlers
     │
store/          SQLite services (GOM, runs, knowledge, metadata, datasets)
     │
core/           domain models, parsers, verifiers, species registry
```

Hard rules (ADR-02):

- `core`, `store` and `tools` may not import `agent`, `tasks`, `interfaces` or `workflow`.
- DBOS is imported **only** by `bacmap.tasks.engine`.
- The MCP SDK is imported only by `interfaces.mcp`, `store.knowledge` and `agent.llm`.
- LLM libraries are imported only by `agent.llm`.

Verify with:

```bash
pixi run -e dev contracts
# Contracts: 5 kept, 0 broken.
```

## 2. Component map

| Component | Responsibility | Key modules |
|---|---|---|
| Core | domain types, MLST/cgMLST parsers, species canonicalisation, verifiers | `core/` |
| Store | SQLite persistence: GOM, runs, metadata, lab results, knowledge, datasets, isolates | `store/` |
| Tools | 26 registry tools + task-layer tool handlers; `effect`/`data_class` labels | `tools/` |
| Workflow | deployed Snakemake DAG, rule scripts, runner/deploy | `workflow/` |
| Tasks | DBOS workflows/steps, gates, record tasks, event log | `tasks/` |
| Application | plan lifecycle, version/hash confirmation, error codes | `application/` |
| Agent | LLM gateway, role prompts, interpretation, sandbox | `agent/` |
| Interfaces | CLI, FastAPI Web + `/api/v1`, Textual TUI, MCP server | `interfaces/` |

## 3. Request flows

### 3.1 Analyze (closed path)

```text
CLI/Web/MCP plan
  → TaskEngine.submit
  → DBOS workflow
      register_inputs? → pipeline (Snakemake) → run record → GOM ingest
      → analysis-claims gate → report → cohort ingest
  → task table + events
```

The pipeline runs in the deployed workflow directory
`$BACMAP_HOME/workflows/bacmap/`, with results redirected to
`$BACMAP_HOME/results/runs/<task_id>/`. Inputs are registered in `samples.tsv`; input files are
hashed into the run record.

### 3.2 Plan (agent path)

```text
MCP bacmap_create_plan
  → PlanService.create (canonical JSON + input fingerprints + plan_hash)
  → state=awaiting_confirmation
human confirms in Web/CLI/local dialog
  → PlanService.confirm (re-check inputs, bind version/hash)
  → deterministic task IDs → TaskEngine.submit (idempotent)
  → plan state=submitted + task_ids
```

### 3.3 Record (write path)

```text
CLI/Web/MCP bacmap_record_data
  → record task (metadata / lab / knowledge import / approve)
  → record step writes the corresponding store
  → task table + event
```

### 3.4 Mine (open path)

```text
confirmed plan
  → register input_paths zero-copy (SHA256)
  → read-only sandbox mounts
  → Python script (no network)
  → artefacts in workspace
  → mining gate → awaiting_approval → human signature
```

## 4. External analysis tools (ADR-20)

bacmap deliberately orchestrates rather than re-implements:

| Question | Tool |
|---|---|
| Which species is this? | `gside species` (marker/panel/ANI/sketch/GTDB profiles) |
| Which resistance/virulence/serotype genes? | `gapit screen` + typing schemes |
| What is the MLST/cgMLST profile? | `gmlst typing` |
| SNP tree / recombination? | pipeline rules (IQ-TREE, optional Gubbins) |

Any new capability that only needs the genome should be added to the external tool and adapted in
bacmap, not implemented in `core/`.

## 5. Deployment and configuration

- The workflow template ships inside the package and is deployed to
  `$BACMAP_HOME/workflows/bacmap/` with a content-hash stamp.
- `samples.tsv` and `.snakemake` state survive redeployment.
- `config.yaml` is rewritten to point `project_root` at `BACMAP_HOME`.
- Paths come from `bacmap.config` (environment + `config.toml`), never from `__file__`.

## 6. Why this shape

- A single workstation → SQLite + file directories, no server/daemon.
- Reproducibility → fixed DAG, run records, immutable GOM.
- Safety → gates and human approval outside the model.
- External agents → a narrow MCP surface with a profile ceiling.
- Long-running work → DBOS step checkpoints, not an in-process thread.

The authoritative rationale and ADR history are in the [frozen design](frozen-design.md).
