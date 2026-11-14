# Data model and storage

bacmap uses SQLite for structured state and plain directories for result files. Everything lives
under `BACMAP_HOME`.

## 1. Identity: specimen → isolate → library → run

```text
specimen: A03-SN-001                        unique specimen / submission ID
   ├── isolate: A03-ISO-01                  biological strain (0..N per specimen)
   │      ├── library: A03-ISO-01__ilm__20261012   one sequencing library
   │      │      └── run: 4f2c…                    one analysis execution
   │      └── library: A03-ISO-01__ont__20261020
   └── library: A03-SN-001__mngs__20261101  direct specimen sequencing (mNGS/tNGS, next major release)
```

- **specimen** — the unique specimen / submission ID (e.g. `A03-SN-001`). One specimen can
  yield 0..N isolates, and may also be sequenced directly (mNGS/tNGS, next major release).
  The ID may be empty when the lab has not supplied it; `bacmap specimen import` backfills it.
- **isolate** — the entity you track epidemiologically; can have lineage/passage
  (`EVO-001-P037` → lineage `EVO-001`, passage 37). An isolate belongs to one specimen.
- **library** — one input library or assembly. Its ID is the `sample` column in
  `samples.tsv` (legacy column name kept so the pipeline rules stay unchanged). A library
  hangs off exactly one isolate — or, for direct specimen sequencing, off the specimen.
- **run** — one execution of the pipeline over one or more libraries. Results are never
  shared between runs, even for the same library.

This separation lets a strain be sequenced twice without overwriting results, lets one
specimen carry several isolates, and lets curation count the strain once.

Legacy migration (v1.10.27): every pre-existing isolate received a **shadow specimen**
(`specimen_id = isolate_id`, `origin=legacy`) so queries, reports and curation behave
exactly as before until real specimen IDs are imported.

## 2. `samples.tsv` (the library registry)

```tsv
sample	species	R1	R2	longread	assembly	isolate	platform	checksum	specimen
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	<sha256>	
ASM-STD-001	Salmonella				gs/ASM-STD-001/ASM-STD-001.fasta	ASM-STD-001	ont	<sha256>	
HZCPE-01__ilm__20261012	VPA	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R1.fastq.gz	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R2.fastq.gz			HZCPE-01	ilm	<sha256>	A03-SN-001
HZCPE-01__ont__20261020	VPA	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R1.fastq.gz	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R2.fastq.gz			HZCPE-01	ont	<sha256>	A03-SN-001
```

| Column | Semantics |
|---|---|
| `sample` | **library ID**; `^[A-Za-z0-9._-]+$`, not `.`/`..` (column name kept for pipeline compatibility) |
| `species` | code or name; `UNK` when unknown |
| `R1`, `R2` | paired reads; relative to `BACMAP_HOME` or absolute |
| `longread` | long-read FASTQ; alone runs flye, with `R1`/`R2` runs unicycler |
| `assembly` | pre-assembled FASTA; skips QC/assembly |
| `isolate` | biological strain; defaults to the library ID for old tables |
| `platform` | `ilm`, `ont`, `pacbio`, `unknown` |
| `checksum` | registration-maintained content hash |
| `specimen` | specimen ID (`A03-SN-001`); may be empty, imported later with `bacmap specimen import` |

Registration writes the row and registers the isolate. A dataset ID collision with different
content is a hard error, never a silent overwrite. A dataset may be short reads (`R1`/`R2`),
long reads (`longread`), hybrid (both), or a pre-assembled FASTA (`assembly`).

## 3. Databases

| File | Tables / purpose |
|---|---|
| `tasks.sqlite` | `tasks`, `approvals`, `plans`, `events` — operational truth |
| `dbos.sqlite` | DBOS system database: workflow/step checkpoints |
| `runs.sqlite` | `analysis_runs` — immutable provenance records |
| `gom.sqlite` | genome objects, GOM events, datasets, strain genotype index, AMR gene index |
| `baseline.sqlite` | baseline candidates and published releases |
| `research.sqlite` | Research Workbench sessions, stat results, artifacts, ledger (P1) |
| `data/bacmap.sqlite` | strain metadata, lab results, isolates, specimens |
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
├── baseline.sqlite
└── research.sqlite
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
