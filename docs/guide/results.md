# Results and evidence

bacmap keeps two things apart: **result files** (per run) and **evidence records** (hashes,
versions, gates, approvals). Both are needed to answer "what did we find, and can we prove it?".

## 1. Run-scoped result layout

Physical results live under a run directory:

```text
$BACMAP_HOME/results/
├── runs/
│   └── <task_id>/
│       ├── <dataset>/               # per-sample files
│       │   ├── qc/
│       │   ├── assembly/
│       │   ├── species/
│       │   ├── typing/
│       │   ├── amr/
│       │   ├── plasmid/
│       │   └── report/
│       │       ├── <dataset>_summary.json
│       │       └── <dataset>_report.html
│       ├── snp/<group>/...
│       └── cgmlst/<group>/...
├── <dataset> -> runs/<latest_task>/<dataset>
├── snp       -> runs/<latest_task>/snp
└── cgmlst    -> runs/<latest_task>/cgmlst
```

Properties:

- Each execution writes only its own `runs/<task_id>/`; old runs are never overwritten.
- Flat paths are relative symlinks to the **latest** run for compatibility with scripts and tools.
- After the pipeline succeeds, ingestion, gates and report generation read **this run's** directory;
  a concurrent analysis of the same dataset cannot contaminate them (v1.9.3).
- Legacy flat directories are migrated to `runs/legacy-<name>/` and replaced by links. A new run
  also migrates leftovers automatically. `bacmap results migrate [--dry-run]` is available for an
  explicit upgrade step.

```bash
bacmap results migrate --dry-run
bacmap results migrate
ls -l "$BACMAP_HOME/results/SAM-TYP-001"
```

## 2. Reports

Every successful `analyze` task generates a templated HTML report:

```bash
ls "$BACMAP_HOME/results/runs/<task_id>/SAM-TYP-001/report/"
# SAM-TYP-001_summary.json
# SAM-TYP-001_report.html
```

Open it from the Web:

```text
/samples/SAM-TYP-001/report            # inline under a sandbox CSP
/samples/SAM-TYP-001/report?download=1 # attachment
```

The report is self-contained (inline style, no external requests), so it can be archived and viewed
offline. PDF generation is optional and needs a local converter.

Reports are generated automatically at the end of every analysis. Re-running an analysis
regenerates them; there is no direct MCP write tool for reports.

## 3. Run records (`runs.sqlite` + manifests)

Each analyze run creates one immutable record:

```bash
bacmap run list
bacmap run show <run_id>
bacmap run show <run_id> --json | jq .
```

A record contains:

| Group | Fields |
|---|---|
| Identity | `run_id`, `task_id`, `strain_ids`, workflow/commit/dirty |
| Time | `started_at`, `finished_at`, `ingested_at` |
| Parameters | `resolved_config`, `config_sha256`, `seeds`, `nondeterministic_steps` |
| Inputs | `input_files` (path → SHA-256) |
| Environment | `tool_versions`, `env_lock_sha256`, `host` |
| Databases | `ref_databases` (name/version/checksum) |

The same content is sealed to `$BACMAP_HOME/runs/<run_id>/run_manifest.json` with a self-hash.
`bacmap run compare` diffs two records; the manifest is what an auditor can re-hash independently.

### Compare two runs

```bash
bacmap run compare <run_a> <run_b>
```

Verdicts:

- `IDENTICAL`: provenance and results match;
- `DIFF_ATTRIBUTED`: provenance differs; the difference is attributed to
  parameters/databases/tools/inputs/workflow;
- `NOT_REPRODUCIBLE`: provenance matched but results differ.

## 4. GOM objects

Genome Object Model (GOM) objects are immutable; new results create new versions or objects.

```bash
bacmap gom list --type analysis
bacmap gom show analysis:SAM-001:<run_id>
bacmap gom show <object_id> --version 2
```

Object types include sample, analysis, report, workflow, plugin, knowledge and task. Analysis
payloads carry a flat summary view plus the original summary:

```json
{
  "analysis_type": "sample_analysis",
  "sample_id": "SAM-001",
  "run_id": "...",
  "species_verdict": "Salmonella",
  "serotype": {"sistr": "Typhimurium"},
  "mlst": "ST19",
  "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
  "summary": {"steps": {"...": "..."}}
}
```

Gate evaluations are appended as `gate.<name>` events on the relevant object; task-level gates
(mine/write/curate) use a `TASK` object.

```text
GET /api/v1/gom/objects?type=analysis&limit=20
GET /api/v1/gom/objects/<object_id>?version=2
```

## 5. Searching samples

```bash
bacmap search --query Salmonella
bacmap search --serotype Typhimurium --st 19 --gene blaCTX-M-15
bacmap sample ls
bacmap sample show SAM-001
```

Web `/search` supports free text plus serotype, ST and gene filters. `bio_search_samples` exposes the
same index to MCP clients (D2). The local genotype index (`strain_genotype_index` in `gom.sqlite`)
stores one row per dataset, updated by the latest analysis.

## 6. Evidence chain: the short version

```text
input file ──SHA256──► run record ──run_id──► GOM ANALYSIS
                             │                     │
                             │                     ├── gate events
                             └── manifest.json     └── approvals / releases
```

- **Inputs** are hashed at registration/run time.
- **Parameters/tools/databases** are captured per run.
- **Results** point at `run_id`.
- **Gates** are code checks; **approvals** are human signatures.
- **Baseline releases** store the manifest + signature and are append-only.

A claim such as "this strain belongs to the local outbreak cluster" must name the baseline version
and the run IDs behind it. That is what makes the conclusion auditable.

## 7. Retention and backup

- `results/` is not removed automatically; clean old runs deliberately after checking retention
  policy.
- `bacmap backup` includes databases and run manifests; add `--with-results` for result files.
- `bacmap events prune --days N` removes old coordination events, not gate approvals or run records.
- Restoring an older backup restores `dbos.sqlite` too, so in-flight tasks can resume.

See [Operations](../operations/index.md) for backup/restore and upgrade procedures.
