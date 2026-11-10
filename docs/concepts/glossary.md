# Glossary (PLAN #16)

Core bacmap concepts, disambiguating common confusions.

## Data entities

| Term | Definition | Example |
|---|---|---|
| **isolate** | A physical entity — a pure culture recovered from a specimen. Has an `isolate_id` in the GOM, with lineage and passage count. | `ISO-2024-001` |
| **sample** | The sample ID for one analysis — equal to `strain_id`, the strain identifier in the GOM. One isolate can yield several samples (different batches/methods), but they usually correspond one-to-one. | `SAM-001` |
| **run** | The record of one analysis execution — input file list, tool versions, reference database versions, output directory. One run covers multiple samples. | `546857e317cd...` |
| **dataset** | Registered external data (zero-copy, SHA-256 provenance) — a FASTA directory, CSV table or any file. Mounted read-only into the mine sandbox. | `ds-f01a0256...` |

> **isolate vs sample**: nearly synonymous in daily use. Technically, isolate
> emphasises the physical entity, sample the analysis unit (the input identifier
> for the pipeline). The `species` column of bacmap's `samples.tsv` holds the
> shared `strain_id`.

## Tasks and plans

| Term | Definition | Relationship |
|---|---|---|
| **plan** | A **proposal** — a versioned list of 1–10 tasks awaiting human confirmation (or auto_confirm pre-authorisation). Nothing executes before confirmation. | 1 plan → N tasks |
| **task** | An **execution unit** — submitted automatically once the plan is confirmed, executed by the DBOS engine. Has a state machine (pending→running→succeeded/failed/awaiting_approval). | N tasks ← 1 plan |

> **task vs plan**: the plan is the "what to do" proposal (for humans); the task
> is the "doing/done" execution record (managed by the engine). A human confirms
> the plan → the engine turns each plan entry into a task and executes it.

## Task types (six kinds)

| Type | Description | Execution | Human confirmation |
|---|---|---|---|
| `analyze` | Standard genome analysis (assembly→typing→annotation→report) | Snakemake pipeline | via plan confirmation |
| `curate` | Feature library / knowledge base construction | Deterministic scripts | via plan confirmation |
| `mine` | Agent-authored custom scripts (Python/R) | Sandbox (no network, read-only mounts) | plan confirmation + mining-gate signature |
| `write` | Report/manuscript writing (LLM generation + citation gate) | In-engine + pydantic-ai | plan confirmation + export gate |
| `record` | Metadata / lab-result / knowledge writes | Deterministic | Direct submission (entry validation) |
| `research` | Research analysis (session/advstats) | Deterministic / container | via plan confirmation |

## Species naming

| Term | Definition | Example |
|---|---|---|
| **species code** | 3-letter species code = genus initial + first two letters of the species | `VPA` = *Vibrio parahaemolyticus* |
| **gside label** | Species label emitted by the gside identification tool | `V_parahaemolyticus` |
| **display name** | Chinese display name in pathogens.yaml | `副溶血性弧菌` |
| **snp_group** | Reference-genome group name for SNP analysis | `vpara` |

> Naming chain: gside emits a label → `species_code()` converts it to the
> 3-letter code → the code keys `pathogens.yaml` → lookup yields the MLST
> scheme, gspec databases, reference genomes, etc. `bacmap species list` shows
> every registered species.

## Reference genomes

| Term | Definition |
|---|---|
| **reference group** | A set of reference genomes used for SNP/phylogenetic analysis (e.g. the `salmonella` group contains the LT2 reference strain) |
| **reference manifest** | `refs/manifest.json` — records name, version and SHA-256 of every reference sequence (ADR-18 provenance) |
| **snp_group** | Group name in pathogens.yaml specifying which reference-genome group a species uses |

> bacmap manages reference genomes: `reference_accessions.yaml` (NCBI accession
> list) → `fetch_reference_genomes.py` (deployment-time download) →
> `refs/manifest.json` (runtime consumption). `bacmap reference list` shows the
> readiness state.
