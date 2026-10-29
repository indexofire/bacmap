# Data model and storage

bacmap uses SQLite for structured state and plain directories for result files. Everything lives
under `BACMAP_HOME`.

## 1. Identity: isolate → dataset → run

```text
isolate: HZCPE-01                  biological strain (stable)
   ├── dataset: HZCPE-01__ilm__20261012   one sequencing library
   │      └── run: 4f2c…                   one analysis execution
   └── dataset: HZCPE-01__ont__20261020
          └── run: 9a31…
```

- **isolate** — the entity you track epidemiologically; can have lineage/passage
  (`EVO-001-P037` → lineage `EVO-001`, passage 37).
- **dataset** — one input library or assembly. Its ID is the `sample` column in `samples.tsv`.
- **run** — one execution of the pipeline over one or more datasets. Results are never shared
  between runs, even for the same dataset.

This separation lets a strain be sequenced twice without overwriting results, and lets curation
count the strain once.

## 2. `samples.tsv` (the dataset registry)

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	a1b2…
ASM-STD-001	Salmonella		gs/ASM-STD-001/ASM-STD-001.fasta			ASM-STD-001	ont	c3d4…
```

| Column | Semantics |
|---|---|
| `sample` | dataset ID; `^[A-Za-z0-9._-]+$`, not `.`/`..` |
| `species` | code or name; `UNK` when unknown |
| `R1`, `R2` | paired reads; relative to `BACMAP_HOME` or absolute |
| `assembly` | pre-assembled FASTA; skips QC/assembly |
| `isolate` | biological strain; defaults to dataset ID |
| `platform` | `ilm`, `ont`, `pacbio`, `unknown` |
| `checksum` | registration-maintained content hash |

Registration writes the row and registers the isolate. A dataset ID collision with different
content is a hard error, never a silent overwrite.

## 3. Databases

| File | Tables / purpose |
|---|---|
| `tasks.sqlite` | `tasks`, `approvals`, `plans`, `events` — operational truth |
| `dbos.sqlite` | DBOS system database: workflow/step checkpoints |
| `runs.sqlite` | `analysis_runs` — immutable provenance records |
| `gom.sqlite` | genome objects, GOM events, datasets, strain genotype index, AMR gene index |
| `baseline.sqlite` | baseline candidates and published releases |
| `data/bacmap.sqlite` | strain metadata, lab results, isolates |
| `data/knowledge.sqlite` | literature/method entries + FTS5 index |
| `refs/manifest.json` | external database versions/checksums |

Migrations:

- Each file has a numbered list and `PRAGMA user_version`.
- Migrations run in one `BEGIN IMMEDIATE` transaction after a backup `<db>.bak-v<N>`.
- A database newer than the running code is refused (no silent downgrade).
- Lists are append-only.

See `store/migrations.py` and `store/schema.py`.

## 4. On-disk layout

```text
$BACMAP_HOME/
├── config.toml
├── data/
│   ├── bacmap.sqlite
│   └── knowledge.sqlite
├── results/
│   ├── runs/<task_id>/...
│   ├── <dataset> -> runs/<latest>/<dataset>
│   ├── snp -> runs/<latest>/snp
│   └── cgmlst -> runs/<latest>/cgmlst
├── workflows/bacmap/          # deployed DAG + config/samples.tsv
├── workflow_state/            # Snakemake logs/state
├── gs/<dataset>/...           # conventional raw inputs
├── workspaces/<task_id>/      # mine workspace (analysis.py, context.json, artefacts)
├── runs/<run_id>/run_manifest.json
├── refs/
├── tasks.sqlite
├── dbos.sqlite
├── runs.sqlite
├── gom.sqlite
└── baseline.sqlite
```

`results/runs/<task_id>/` is the only place a run writes. Flat paths are relative symlinks to the
latest run. Ingestion/gates/reports read the run directory, not the alias (v1.9.3).

## 5. Lifecycle of an analysis record

```text
input file(s)
  │  registration → samples.tsv (+ checksum)
  ▼
task submitted (task_id)
  │  DBOS workflow
  ├─ Snakemake writes results/runs/<task_id>/
  ├─ create analysis_runs row + manifest (hashes, versions, seeds)
  ├─ GOM ANALYSIS objects + strain index
  ├─ analysis-claims gate event
  └─ report HTML
  ▼
task state succeeded / awaiting_approval
```

## 6. GOM objects

`GenomeObject` is immutable and versioned:

```python
GenomeObject(
    object_id="analysis:SAM-001:<run_id>",
    object_type=ObjectType.ANALYSIS,
    version=1,
    schema_version="1.0.0",
    payload={...},
    pipeline_version=...,
    database_versions={...},
    tool_versions={...},
    organism="Salmonella",
    strain_id="SAM-001",
)
```

- Creating the same `(object_id, version)` twice raises `GOMImmutableError` (idempotent retry).
- New content means a new object or `create_new_version`.
- GOM events record gate evaluations (`gate.<name>`) and lifecycle events.

## 7. Baseline library

A `curate` candidate contains:

- one representative run per isolate (`representative_runs`),
- `superseded` datasets and reasons,
- `excluded` records (missing metadata, unsupported species, failed QC),
- a feature table restricted to a whitelist (no personal fields by construction).

Publishing writes a new `baseline_releases` row with signature and parent version. Published
releases are append-only. See the [frozen design](frozen-design.md) ADR-19.
