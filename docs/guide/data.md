# Data and identity

bacmap separates four levels of identity:

```text
specimen (unique submission ID, e.g. A03-SN-001)
   ├── isolate (biological strain, 0..N per specimen)
   │      └── library (one sequencing library / assembly, 1..N per isolate)
   │             └── run (one analysis execution)
   └── library (direct specimen sequencing: mNGS/tNGS, next major release)
```

A strain may be sequenced many times; a library may be analysed many times. Results never mix
between runs, and curation never counts one isolate twice. Specimen IDs are supplied by the lab
and may be imported after registration (`bacmap specimen import`); `bacmap specimen backfill`
links unlinked isolates to same-name specimens (creating them on demand).

## 1. The samples.tsv table

Location: `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`.

```tsv
sample	species	R1	R2	longread	assembly	isolate	platform	checksum	specimen
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	<sha256>	
ASM-STD-001	Salmonella				gs/ASM-STD-001/ASM-STD-001.fasta	ASM-STD-001	ont	<sha256>	
HZCPE-01__ilm__20261012	VPA	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R1.fastq.gz	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R2.fastq.gz			HZCPE-01	ilm	<sha256>	A03-SN-001
HZCPE-01__ont__20261020	VPA	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R1.fastq.gz	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R2.fastq.gz			HZCPE-01	ont	<sha256>	A03-SN-001
ONT-ONLY-001	VPA			gs/ONT-ONLY-001/ONT-ONLY-001.fastq.gz		ONT-ONLY-001	ont	<sha256>	
HYBRID-001	VPA	gs/HYBRID-001/HYBRID-001_R1.fastq.gz	gs/HYBRID-001/HYBRID-001_R2.fastq.gz	gs/HYBRID-001/HYBRID-001.fastq.gz		HYBRID-001	ont	<sha256>	
```

| Column | Meaning |
|---|---|
| `sample` | **library ID**. Allowed: `A-Z a-z 0-9 . _ -`; never `.` or `..` (column name kept for pipeline compatibility) |
| `species` | 3-letter code or gside label/name; `UNK` for reads not yet identified |
| `R1`/`R2` | paired FASTQ paths, relative to `BACMAP_HOME` or absolute |
| `longread` | long-read FASTQ path (ONT/PacBio); alone → flye, with `R1`/`R2` → unicycler hybrid assembly |
| `assembly` | assembled FASTA path; skips QC/assembly; reads win if both are set |
| `isolate` | biological strain ID; defaults to the library ID for old tables |
| `platform` | sequencing platform (`ilm`, `ont`, `pacbio`, …); `unknown` when not provided |
| `checksum` | SHA-256 over the input file(s); maintained by registration |
| `specimen` | specimen ID (`A03-SN-001`); may be empty, backfilled with `bacmap specimen import` |

Assembly-only samples have no reads: read-level steps such as `fastp` are not added to the
DAG. The registration unit is a **library** (the `sample` column); the code and older logs
still say "dataset" for backward compatibility. Shigella serotyping is handled for both input types by the gspec `shi_sero` marker-set
library on assembled contigs; no reads are required. If the local `shi_sero` is stale
(missing `serotype.json`), back it up and rebuild:

```bash
mv ~/.local/share/gspec/db/shi_sero ~/.local/share/gspec/db/shi_sero.bak
gspec db setup -d shi_sero
```

For example, the `26OTH0027` assembly resolves to `S. flexneri 3a`.

Naming recommendation for multiple libraries of one isolate:

```text
<isolate>__<platform>[__<date>]
HZCPE-01__ilm__20261012
HZCPE-01__ont__20261020
```

## 2. Registration paths

### 2.1 Directory registration (recommended)

```bash
# Assembled FASTA; species auto-detected with gside unless --species is given
bacmap task submit --type analyze --fasta-dir /data/genomes --species VPA

# Reads; pairs are detected from *_R1/_R2 or *_1/_2;
# unpaired files with median read length >=1 kb are registered as long reads
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

Registration is a task step, not a direct file edit: it writes `samples.tsv`, registers isolates,
and then submits the analysis. For long-read input, an unpaired FASTQ goes to the `longread`
column; its platform (`ont`/`pacbio_hifi`) is probed and can be overridden in the `platform`
column. A dataset with both `R1`/`R2` and `longread` is assembled with unicycler. The
registration function returns `added`, `reused`, `skipped` and `detected` to the workflow (the
sample list is what gets analysed); the CLI returns the submitted `task_id`, and the resulting
rows are visible in `samples.tsv`.

```json
{
  "samples": ["HZCPE-01__ilm__20261012"],
  "added": 1,
  "reused": 0,
  "skipped": [],
  "detected": {"HZCPE-01__ilm__20261012": "VPA"},
  "samples_tsv": "/home/me/.local/share/bacmap/workflows/bacmap/config/samples.tsv"
}
```

### 2.2 Manual rows

```tsv
sample	species	R1	R2	longread	assembly	isolate	platform	checksum
NEW-001	Salmonella	gs/NEW-001/NEW-001_R1.fastq.gz	gs/NEW-001/NEW-001_R2.fastq.gz			NEW-001	ilm	
```

Leave `checksum` empty if you add a row by hand; the next registration recomputes it. The pipeline
uses relative paths against `BACMAP_HOME`, exactly like the Snakefile.

## 3. Collision rules

Registering an existing dataset ID is idempotent **only when the content hash matches**:

```text
dataset_id collision: 'HZCPE-01__ilm__20261012' already registered with different content
(existing path: ...; new path: ...). Rename the file or use a distinct dataset id,
e.g. HZCPE-01__ilm__20261012__<platform>__<yyyymmdd>.
```

What happens:

- same ID + same content → reuse, no duplicate row;
- same ID + different path or content → hard error; never silently analyse the old file;
- legacy rows without `checksum` → recorded files are re-hashed before comparison.

A dataset ID that is not a valid identifier is skipped during directory registration with a reason,
so it cannot create an unreadable results directory.

## 4. Isolates, lineage and passage

```bash
bacmap isolate list
bacmap isolate show HZCPE-01
```

Isolates are created automatically from `samples.tsv`. Naming convention:

```text
EVO-001-P000
EVO-001-P001
EVO-001-P037
```

`EVO-001-P037` is parsed as lineage `EVO-001`, passage `37`. Give each passage its own isolate and
attach one or more datasets underneath it. `lineage_id` is reserved for linking passages; the
current release parses it but does not yet provide a lineage-wide API.

Curate groups by isolate and includes one representative run per isolate. The default is the latest
analysis; override explicitly:

```json
{"pathogen": "VPA", "representative_dataset": {"EVO-001-P037": "EVO-001-P037__ont__20261020"}}
```

The candidate records `representative_runs` and `superseded`, so a multi-dataset strain is not
double-counted in a baseline release.

## 5. Records: metadata, lab results and knowledge

Records are **tasks**, not direct writes. They are auditable, can be submitted from CLI/Web/MCP
(local-trusted), and never bypass the engine.

### Metadata

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 \
  --field province=Guangdong \
  --field city=Shenzhen \
  --field sample_source=food
```

Allowed fields include `isolation_date`, `collection_date`, `province`, `city`, `district`,
`sample_source`, `sample_type`, `food_category`, `food_name`, `outbreak_id`, plus laboratory/patient
fields (D4). Unknown keys are rejected. `sample_id` defaults to `strain_id`.

### Lab result

```bash
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L \
  --interpretation S --method broth_microdilution --lab "Provincial CDC"
```

Query them with `bio_query_lab_results` (local-trusted) or the Records page.


### Bulk import wet-lab data (XLSX / CSV / TSV, four layers)

Use the per-row commands for small edits; for a whole wet-lab workbook:

```bash
bacmap record import wetlab.xlsx --dry-run
bacmap record import wetlab.xlsx
```

The console **Wet-lab import** page also accepts uploads: a `user` creates a
`pending_review` proposal, and an `analyst`/`admin` must approve it before a record
task is submitted. Submitters cannot approve their own proposal (an admin may force
self-approval). Uploaded files stay locally under `imports/<job_id>/`.

When a normal `user` edits/deletes existing data or creates a specimen/isolate, the console
creates the same review proposal as a file import (`/api/v1/wetlab/proposals`). Submitters
cannot self-approve; approval rechecks that the target did not change meanwhile, and unowned
targets are claimed for the submitter after approval. Use `bacmap imports list|prune` to
review or expire local upload/proposal artifacts.

Specimen and isolate detail pages now manage wet-lab data directly (analyst/admin only;
writes still go through `record` tasks): edit or clear specimen/isolate fields, edit or
delete library metadata, add/update/delete isolate or specimen lab results, and link
isolates/datasets to a specimen. Saving waits for the record task and refreshes the page;
a normal `user` can still only upload proposals and cannot write directly.

**AI mapping advice** in the preview panel is a read-only advisor: it suggests target
fields for unrecognised columns, which columns should stay in custom `extra`, and flags
privacy/date/unit risks. It never edits the file, writes domain tables or invents GOM IDs.
Data classes are enforced by configuration: a cloud endpoint sees only column names and
aggregates; a local/LAN endpoint receives up to three truncated sample values only when
`ai_max_data_class >= D4`.

A workbook may contain four sheets (Chinese or English names, or specify them):

```text
specimen / 样本信息 / 患者信息
specimen_id    patient_name  collection_date  sample_source
A03-SN-001     Zhang San     2026-10-01       food

isolate / wetlab / 湿实验 / 菌株信息
isolate_id  isolation_date  province  custom_field_a
HZCPE-01    2026-10-12      Guangdong value

library / 测序数据
library_id      platform   sequencing_date
HZCPE-01__ilm   illumina   2026-10-03

lab / 化验 / 药敏
library_id      category  test_name  result  unit  interpretation
HZCPE-01__ilm   mic       meropenem  0.25    mg/L  S
```

- **Specimen** rows (`specimen_id`/`样本编号`): patient, collection date, source and
  other sample-level fields. Column names are not fixed; they are stored as specimen
  metadata JSON.
- **Isolate** rows (`isolate_id`/`菌株编号`): isolation date, source, passage, etc.
  `METADATA_FIELDS` and common Chinese aliases are mapped; unknown columns go to `extra`.
- **Library** rows (`library_id`, the `sample` column in `samples.tsv`): platform, run,
  date, etc. WGS libraries link to isolate/specimen; mNGS links only to specimen.
  One isolate may have many libraries.
- **Lab** rows: long format, one test per row; default subject is isolate, and
  `--lab-subject specimen` attaches results to a specimen (e.g. mNGS). Required:
  `category`/`test_name`/`result`.
- Isolate/library keys also accept a library or specimen ID and resolve through
  `samples.tsv`/identity tables; a specimen with multiple isolates is rejected.
- One file becomes one `record` task (`kind=batch`). Every row is validated first;
  a missing key/required field/identity rejects the whole file with sheet and row numbers.
- CSV/TSV use one table and auto-detect the target; XLSX may specify
  `--specimen-sheet` / `--isolate-sheet` / `--library-sheet` / `--lab-sheet`
  (`--metadata-sheet` is a compatibility alias for `--isolate-sheet`).
- Import never creates specimens/isolates/libraries; rows must match registered entities.

### Knowledge

```bash
bacmap record knowledge-import --title "V. parahaemolyticus O3:K6 outbreak" \
  --authors "Zhang et al." --year 2024 --identifier PMID:12345678 \
  --content "cgMLST cluster ..." --entry-kind literature

bacmap record knowledge-approve 7
```

Imported entries are staged (`approved_by IS NULL`). Only approved entries become citable; approval
is recorded once and cannot be overwritten. The write task's citation gate consumes approved PMIDs
and DOIs.

## 6. External datasets (mine inputs)

`mine` tasks can read local files/directories without copying them. The engine:

1. resolves the path, walks directories, computes per-file SHA-256 and a manifest hash;
2. deduplicates identical content by manifest hash;
3. registers the dataset in `gom.sqlite` (`datasets` table) with data class, source path and
   dev/inode/mtime;
4. mounts it read-only into the sandbox (`/input/<dataset_id>`).

`mine` is accepted only as part of a plan confirmed by a human; there is no CLI shortcut:

```json
{"tasks": [{
  "task_type": "mine",
  "objective": "summarise the supplied TSV files",
  "script": "import json,pathlib; ...",
  "input_paths": ["/data/run42/analysis"],
  "input_data_class": "D3"
}]}
```

The workspace `context.json` maps dataset IDs to guest paths:

```json
{"datasets": {"ds-0123456789abcdef": "/input/ds-0123456789abcdef"}}
```

Verify integrity:

```bash
# MCP / tool call (local-trusted)
bio_inspect_dataset {"dataset_id": "ds-0123456789abcdef", "verify": true}
```

The original file must stay in place; zero-copy registration records its identity, not a copy. A
moved/deleted source becomes `missing` on verification.

## 7. Where identity appears

| Artifact | Identity |
|---|---|
| `samples.tsv` | dataset ID and isolate |
| `results/runs/<task_id>/<dataset>/` | one execution of one dataset |
| `analysis_runs.strain_ids` | dataset IDs analysed in that run |
| GOM `ANALYSIS` object | `analysis:<dataset>:<run_id>` |
| strain index | one row per dataset (latest analysis wins) |
| baseline release | one row per isolate representative |
| `approvals` / events | task/plan + human actor |

This separation is why “the same strain sequenced twice” does not overwrite results and why a
baseline can count the strain once.
