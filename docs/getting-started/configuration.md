# Configuration

bacmap is configured by **environment variables** plus one optional TOML file at
`$BACMAP_HOME/config.toml`. No path is derived from the source-tree location (ADR-03). This page
covers the settings most installations need; the complete key-by-key reference is
[Configuration reference](../reference/configuration.md).

## 1. Where things live

```bash
export BACMAP_HOME="$HOME/.local/share/bacmap"
mkdir -p "$BACMAP_HOME"
```

```text
$BACMAP_HOME/
├── config.toml
├── data/                 # metadata.sqlite, lab results, knowledge.sqlite
├── results/              # run-scoped results + latest-run symlinks
├── workflows/bacmap/     # deployed Snakemake workflow; samples.tsv lives here
├── workflow_state/       # .snakemake logs/state
├── gs/                   # conventional raw-data layout
├── workspaces/           # mine task workspaces
├── runs/                 # run_manifest.json per run
├── tasks.sqlite          # tasks, plans, events
├── dbos.sqlite           # DBOS workflow checkpoints
├── runs.sqlite           # run records
├── gom.sqlite            # GOM objects, datasets, strain index
├── baseline.sqlite       # baseline candidates/releases
└── refs/                 # external databases + manifest.json
```

Most commands accept `--home DIR`; the environment variable is the default.

## 2. Sample registration (samples.tsv)

The standard `analyze` task requires sample IDs to be registered in
`$BACMAP_HOME/workflows/bacmap/config/samples.tsv`:

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	<sha256>
ASM-STD-001	Salmonella		gs/ASM-STD-001/ASM-STD-001.fasta			ASM-STD-001	ont	<sha256>
HZCPE-01__ilm__20261012	VPA	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R1.fastq.gz	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R2.fastq.gz			HZCPE-01	ilm	<sha256>
```

Rules:

- `sample` is the **dataset ID**; allowed characters are `A-Z a-z 0-9 . _ -` and it may not be
  `.` or `..`.
- `R1`/`R2` and `assembly` are relative to **`BACMAP_HOME`** (absolute paths also work).
- Use **either** paired reads **or** one assembled FASTA per dataset. If both are present, reads
  win.
- `species` accepts a 3-letter code (`SAL`, `ECO`, `SHI`, `VPA`, …) or a gside label/name
  (`Salmonella`, `V_parahaemolyticus`, `E. coli`). Codes are preferred.
- `isolate` is the biological strain; several datasets may point to one isolate. `platform`
  records the sequencing platform.
- Registration through the CLI computes `checksum` and detects content collisions; leave it empty
  only when adding rows by hand.

Register a directory instead of editing the table:

```bash
# Assembled FASTA: ids are derived from file names; species auto-detected with gside
bacmap task submit --type analyze --fasta-dir /data/genomes

# Reads: paired *_R1/_R2 (or *_1/_2) files; species defaults to UNK until the pipeline identifies it
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

Dataset names should follow `<isolate>__<platform>[__<date>]` when one strain is sequenced more
than once:

```text
HZCPE-01__ilm__20261012
HZCPE-01__ont__20261020
```

Registering the same dataset ID with different content is a hard error; bacmap will never silently
analyse an older file. See [Data & identity](../guide/data.md) for the full model.

## 3. LLM endpoints (optional)

bacmap's deterministic pipeline does not need an LLM. If you use the in-task interpretation/gateway
or a cloud MCP client, configure OpenAI-compatible endpoints:

```toml
# $BACMAP_HOME/config.toml
[llm.endpoints.strata]
location = "local"                      # local | lan | cloud
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.endpoints.deepseek]
location = "cloud"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"        # only the variable NAME is stored

[llm.routing]
interpretation = "deepseek"             # purpose → endpoint

[llm.data_policy]
cloud_max_data_class = "D1"             # D1 or D2 only; D3/D4 can never be raised
```

Inject the key in the same shell/systemd unit that starts bacmap:

```bash
export DEEPSEEK_API_KEY="sk-..."
bacmap overview
```

Data-class rules are enforced in code before a request is sent:

| Class | Examples | Cloud endpoint |
|---|---|---|
| D0–D1 | public data, de-identified summaries | allowed by default |
| D2 | single-strain typing detail | blocked unless the admin raises the ceiling to D2 |
| D3–D4 | sequences, personal/epidemiological identifiers | never sent to a cloud endpoint |

## 4. MCP side (agents)

A **cloud** MCP instance is the default and exposes only tools whose output is within
`cloud_max_data_class`. A **local-trusted** instance can expose up to D4 and must be enabled
explicitly:

```toml
[mcp]
allow_local_trusted = true       # must be the boolean true
```

```bash
bacmap mcp --profile local-trusted
```

Use `local-trusted` only when the harness talks to a local/LAN model. See
[Agents & plans](../guide/agent-plans.md) for client configurations.

## 5. Plan confirmation (optional pre-authorisation)

Plans are confirmed by a person on a trusted surface. For low-risk, repetitive analyses an
administrator may pre-authorise automatic confirmation:

```toml
[plans.auto_confirm]
enabled = true
max_samples = 20        # analyze only, already registered samples, no directory ingestion,
                        # no scripts; mine/write/curate are never auto-confirmed
```

The audit actor is `policy:auto-confirm`. For the default human flow (Web link, local dialog, CLI)
see [Agents & plans](../guide/agent-plans.md).

## 6. First analysis

```bash
# Register one sample manually, then submit
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>

# Results are run-scoped; the flat path is a link to the latest run
ls "$BACMAP_HOME/results/SAM-TYP-001/report/"
ls "$BACMAP_HOME/results/runs/"
```

If the task ends in `awaiting_approval`, open the Web task page or use:

```bash
bacmap task approve <task_id> --approver "Your Name" --decision approve --signature "your-signature"
```

For a guided first session, continue with the [Tutorial](tutorial.md).
