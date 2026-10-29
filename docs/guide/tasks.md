# Tasks and gates

A **task** is the only way bacmap changes state. The task engine executes five task types, records
every step, applies gates and keeps an immutable evidence trail. Interfaces submit tasks; they never
write stores directly.

## 1. The five task types

| Type | Purpose | Input shape | Typical end state |
|---|---|---|---|
| `analyze` | run the fixed Snakemake pipeline for datasets | one of `samples`, `fasta_dir`, `fastq_dir` | `succeeded`, or `awaiting_approval` if the analysis-claims gate flags a text |
| `curate` | build a local epidemiological baseline candidate | optional `scope` | `awaiting_approval` (release gate + signature) |
| `mine` | run a user/agent Python script in a network-less sandbox | `objective`, `script`, optional `input_paths` | `awaiting_approval` (mining gate + signature) |
| `write` | gate a draft manuscript/report against the local knowledge base | `objective`, `draft`, `known_citations` | `awaiting_approval` or `failed` on unknown citations |
| `record` | metadata, lab result, knowledge import/approval | `kind` + fields | `succeeded` / `failed` |

**Closed path**: `analyze` and `curate` run a fixed DAG/algorithm. **Open path**: `mine` and `write`
carry code/text that a person must review; they are only accepted as plans confirmed by a human.

## 2. Task states

```text
pending ──► running ──► succeeded
                │
                ├──► failed
                ├──► cancelled
                └──► awaiting_approval ──► succeeded | failed
```

`pending` exists in the model but submissions normally start as `running`. `awaiting_approval` means
a gate produced `needs approval`; a human must sign or reject the task. The task table in
`tasks.sqlite` is the source of truth; DBOS state is reconciled into it when you query.

```bash
bacmap task list
bacmap task show <task_id> --json
bacmap task cancel <task_id>        # only non-terminal tasks
```

## 3. `analyze`

### Parameters

| Field | Required | Notes |
|---|---|---|
| `samples` | one of three | already registered dataset IDs |
| `fasta_dir` | one of three | absolute directory of `.fna/.fasta/.fa`; registers each genome |
| `fastq_dir` | one of three | absolute directory of paired `*_R1/_R2` (or `*_1/_2`) reads |
| `species` | only with a directory | code or name; for FASTA it is auto-detected with gside when omitted; for FASTQ it defaults to `UNK` |
| `cores` | no | Snakemake cores, default 8 |
| `interpretation_text` | no | internal/engine-level only: optional text checked by the analysis-claims gate; not a CLI/plan field and not generated automatically |

Exactly one input form is allowed. `samples` and a directory are mutually exclusive; `species`
cannot be combined with `samples`.

### Examples

```bash
# Registered datasets
bacmap task submit --type analyze --samples SAM-TYP-001,SAM-TYP-002

# Assembled genomes: scan, register and analyse; species detected per genome
bacmap task submit --type analyze --fasta-dir /data/genomes

# Reads: paired files, known species
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

As an MCP plan:

```json
{
  "tasks": [
    {"task_type": "analyze", "fasta_dir": "/data/genomes", "species": "VPA"}
  ],
  "rationale": "batch 42, assembled genomes"
}
```

The pipeline writes into `results/runs/<task_id>/<sample>/`. After success, flat paths such as
`results/<sample>` are repointed to that run. Ingestion, gates and report generation read the run
directory, never the mutable flat alias (v1.9.3).

At the end, bacmap creates:

- an immutable `analysis_runs` row + `runs/<run_id>/run_manifest.json`;
- GOM `ANALYSIS` objects (`analysis:<sample>:<run_id>`, per-sample cgMLST profiles, cohort summaries);
- a strain-index row for fast searches;
- a templated HTML report per sample.

## 4. `curate`

`curate` selects one representative run per **isolate**, checks inclusion criteria, removes D4 fields
by construction, and stores a candidate. Publishing requires the release gate and a human signature.

```bash
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task show <task_id>          # awaiting_approval when the gate passes
bacmap task approve <task_id> --approver "Jane" --decision approve --signature "jd-2026-10-30"
```

Scope fields:

| Field | Meaning |
|---|---|
| `pathogen` | species substring filter (e.g. `Salmonella`) |
| `strains` | explicit dataset or isolate IDs |
| `representative_dataset` | `{"<isolate>": "<dataset>"}` to override the default newest run |

Selection details:

- Grouping key is `isolate` from samples.tsv (falling back to the dataset ID);
- Default representative is the latest summary mtime with a stable tie-break;
- The candidate records `representative_runs` and `superseded`; excluded isolates carry a reason;
- Inclusion requires a supported species, QC data, isolation date, region and source;
- A typo in `representative_dataset` is reported as `representative_dataset_missing` /
  `representative_isolate_missing`, not silently ignored.

Plan example:

```json
{"tasks": [{"task_type": "curate", "scope": {"pathogen": "Vibrio parahaemolyticus"}}]}
```

## 5. `mine`

`mine` lets an agent analyse **already-produced** data with custom Python. The script runs inside a
container with no network; host input paths are registered zero-copy and mounted read-only.

Parameters (those available in a plan):

| Field | Required | Notes |
|---|---|---|
| `objective` | yes | 1–500 characters; what the script should produce |
| `script` | yes | full Python source, ≤20,000 characters; enters the plan hash |
| `input_paths` | no | absolute files/directories to register and mount read-only |
| `sandbox_image` | no | default `docker://python:3.12-slim` |
| `input_data_class` | no | `D2`, `D3` (default) or `D4` |

The script reads `context.json` from its workspace:

```json
{
  "backend": "apptainer",
  "results_dir": "/data/results",
  "gom_db": "/data/gom.sqlite",
  "datasets": {
    "ds-0123456789abcdef": "/input/ds-0123456789abcdef"
  }
}
```

`datasets` is an **object** mapping dataset ID to path. A minimal script:

```python
import json, pathlib, statistics

ctx = json.loads(pathlib.Path("context.json").read_text())
rows = []
for ds_id, root in ctx["datasets"].items():
    for path in pathlib.Path(root).rglob("*.tsv"):
        rows.append({"dataset": ds_id, "file": path.name, "bytes": path.stat().st_size})

out = {"n_files": len(rows), "median_bytes": statistics.median(r["bytes"] for r in rows) if rows else 0}
pathlib.Path("summary.json").write_text(json.dumps(out, indent=2))
```

Files created in the workspace (except `analysis.py` and `context.json`) become artefacts. They pass
the mining gate only after a human signs; unsigned artefacts never enter a report.

## 6. `write`

`write` applies the **citation gate** to a complete draft. A citation is accepted only if it matches
an approved local knowledge entry (PMID or DOI).

| Field | Required | Notes |
|---|---|---|
| `objective` | yes | 1–500 characters |
| `draft` | yes | full text, ≤40,000 characters; enters the plan hash |
| `known_citations` | no | identifiers to accept; an **empty list** means "use the approved knowledge base". A non-empty list replaces the knowledge-base set, so it is reviewed with the plan |

```json
{
  "tasks": [{
    "task_type": "write",
    "objective": "weekly V. parahaemolyticus brief",
    "draft": "In week 43 ... (PMID:12345678)",
    "known_citations": []
  }]
}
```

Unknown citations cause the task to fail before approval. If an entry is staged but not approved,
approve it first:

```bash
bacmap record knowledge-approve 12
```

## 7. `record`

Record tasks are the only path for metadata, lab results and knowledge. They are auditable and never
modify stores directly. `bacmap_record_data` exposes them over MCP **only** on the `local-trusted`
profile.

| Kind | Required | Optional |
|---|---|---|
| `metadata` | `strain_id`, `fields` | `sample_id` |
| `lab_result` | `strain_id`, `category`, `test_name`, `result` | unit, method, interpretation, standard, tested_date, tested_by, lab, notes |
| `knowledge_import` | `title` | authors, year, source, identifier, content, entry_kind (`literature`/`method`/`report`) |
| `knowledge_approve` | `entry_id` | — |

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L --interpretation S
bacmap record knowledge-import --title "Outbreak paper" --identifier PMID:12345678
bacmap record knowledge-approve 7
```

Metadata fields are whitelisted; unknown keys are rejected. Knowledge approval is **single-shot**:
a later reviewer cannot overwrite the original approver.

## 8. Gates at a glance

| Gate | Trigger | Passes when | Failure mode |
|---|---|---|---|
| `analysis_claims` | analyze end / `bio_verify_result` | species is supported and the optional interpretation text does not contradict pipeline facts | `reject` or `needs_human_review` |
| `baseline_release` | curate end | non-empty, no duplicates, species/date/region/source complete, no D4 leak | `reject`; no release |
| `mining` | mine end + approval | non-empty artefacts, each reproducible, signed by a human | `reject`; task fails |
| `citation` | write end | every PMID/DOI appears in approved knowledge | `reject`; task fails |

Plan confirmation and task approval are **not gates** in this table: they are human actions on a
trusted surface. See [Task engine & gates](../concepts/task-engine.md) for implementation details.

## 9. Reproducibility

Every `analyze` run records resolved config, hashes, tool versions, reference database versions,
seeds, workflow commit and input hashes. Compare two runs:

```bash
bacmap run list
bacmap run show <run_id>
bacmap run compare <run_a> <run_b>
```

`NOT_REPRODUCIBLE` means provenance matched but results differed; `DIFF_ATTRIBUTED` means the
difference is explained by parameters/databases/tools/inputs/workflow.

## 10. Cancellation and recovery

```bash
bacmap task cancel <task_id>
```

Only non-terminal tasks can be cancelled. The engine is built on DBOS: if the process dies, a
restart resumes the workflow from the last completed step; Snakemake resumes from `.snakemake`.
Plan confirmation uses deterministic task IDs, so re-confirming after a crash does not create a
second task.
