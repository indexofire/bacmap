# Getting started

This page takes you from a bare Linux workstation to a verified bacmap installation and a first
analysis. It also explains the minimum configuration needed before real samples can be processed.

## 1. Requirements

| Item | Recommended | Why |
|---|---|---|
| OS | Linux x86_64 | The bioinformatics toolchain is Linux-native |
| Memory | 64 GB | A local LLM (~45 GB) plus the pipeline can share one machine; 16 GB works for deterministic-only use |
| Disk | 50 GB+ | CARD/VFDB/MLST schemes and cgMLST schemes are large |
| Network | Installation only | Runtime analysis must not need outbound connections (ADR-16) |
| Sandbox | Apptainer or Podman | Required for `mine` tasks and external-data access |

If you do not run a local LLM, every deterministic function still works. Only the optional
in-task interpretation/gateway paths degrade (C3).

## 2. Install

```bash
git clone https://github.com/indexofire/bacmap && cd bacmap
pixi install --all    # all environments: Python 3.12 + Snakemake 9 + tools
pixi shell            # activate it
bacmap --version      # 0.1.2
```

What `pixi install` provides:

- **Snakemake and the toolchain**: fastp, shovill, bwa, minimap2, samtools, bcftools, blast,
  bedtools, iqtree, and more (see `pixi.toml`).
- **Common analysis tools** (ADR-20): `gside` (species identification), `gspec` (gene
  screening/typing), `gmlst` (MLST/cgMLST/MST).
- **A separate `recomb` environment** with Gubbins for optional recombination detection, because
  its IQ-TREE pin conflicts with the main pipeline; run it with `pixi run -e recomb …`.

The development environment is separate:

```bash
pixi install -e dev
pixi run -e dev test        # pytest (current baseline: 1703 passed)
pixi run -e dev lint        # ruff
pixi run -e dev typecheck   # mypy
pixi run -e dev contracts   # import-linter dependency contracts
pixi run -e dev docs-build  # mkdocs (both languages)
```

> Always use `-e dev` for pytest/ruff. Without it, pixi resolves the system Python and collection
> fails with `No module named 'dbos'` — an environment mistake, not a code failure.

### 2.1 Configuration template and locations

The repository root provides `config.example.toml` (TOML, not YAML). The simplest initialization is:

```bash
bacmap config init           # write $BACMAP_HOME/config.toml
bacmap config init --user    # write ~/.config/bacmap/config.toml
bacmap config init --project # write ./config.toml (gitignored in source checkouts)
```

In a pixi/source checkout, a project-local file is not discovered automatically; point to it:

```bash
cp config.example.toml config.toml
export BACMAP_CONFIG="$PWD/config.toml"
```

For a pip/conda installation, prefer:

```bash
bacmap config init --user
# ~/.config/bacmap/config.toml
```

See [Configuration](configuration.md) for the full resolution order.

### 2.1 Standalone conda and the agent environment

A pixi environment is effectively a project-local conda environment (`.pixi/envs/default`). The
currently supported and tested installation is pixi. Once bacmap ships a conda package, the intended
form will be:

```bash
conda create -n bacmap -c conda-forge -c bioconda bacmap
conda activate bacmap
bacmap doctor
```

Until then, avoid hand-assembling a conda environment: `pixi.toml` locks the bioinformatics tools,
PyPI packages and native dependencies, and a manual reconstruction is easy to get wrong.

Whether bacmap uses pixi or conda, **Hermes / Pi / DSH do not need to share its environment**:

```text
Hermes / Pi / DSH (their own installation)
        │ MCP stdio or HTTP
        ▼
bacmap (pixi/conda environment with Snakemake and bioinformatics tools)
        ▼
gside / gspec / gmlst / samtools / blast / ...
```

For stdio access to a standalone conda environment, prefer:

```yaml
command: conda
args: ["run", "--no-capture-output", "-n", "bacmap", "bacmap", "start", "mcp"]
```

`--no-capture-output` keeps MCP stdio unbuffered. Full client configuration is in
[Agents and plans](../guide/agent-plans.md).

## 3. Data root and first health check

bacmap stores everything under `BACMAP_HOME` (default `~/.local/share/bacmap`):

```text
$BACMAP_HOME/
├── config.toml              # optional; defaults apply when absent
├── data/                    # metadata, lab results, knowledge, reference data
├── results/
│   └── runs/<task_id>/<sample>/...   # physical output of each execution
├── workflows/bacmap/        # deployed Snakemake workflow + config/samples.tsv
├── workflow_state/          # .snakemake logs/state
├── gs/<sample>/             # conventional raw-data layout
├── workspaces/<task_id>/    # mine task workspaces
├── runs/                    # run manifests (evidence chain)
├── tasks.sqlite             # task/plan/event tables
├── dbos.sqlite              # DBOS workflow checkpoints
├── runs.sqlite              # immutable analysis run records
├── gom.sqlite               # GOM objects, datasets, strain index
├── baseline.sqlite          # baseline candidates/releases
└── refs/                    # external databases + manifest.json
```

```bash
export BACMAP_HOME="$HOME/.local/share/bacmap"   # optional override
bacmap doctor                                    # human-readable
bacmap doctor --json                             # machine-readable
```

`doctor` checks writability, task-database schema version, sandbox backend, LLM endpoint, free
disk and external tools. It exits `1` only for `fail` items; warnings do not fail the command.

## 4. Sandbox backend

`mine` tasks execute Python in a network-less container:

```bash
sudo apt-get install podman        # recommended on a single workstation
# or: sudo apt-get install apptainer
which apptainer podman             # either one suffices
```

Fallback order is Apptainer → Podman. With neither installed, `mine` fails with a clear
`sandbox unavailable` message. Direct host execution is refused unless
`BACMAP_ALLOW_UNSANDBOXED=1` is explicitly set for controlled development. Docker is deliberately
not supported.

## 5. Reference databases

cgMLST schemes are downloaded once and cached in the pixi environment:

```bash
gmlst scheme download senterica_2
gmlst scheme list                       # ✓ = cached
gmlst scheme download ecoli_2
```

The cache is lost when the pixi environment is rebuilt; rerun the download after rebuilding.
EnteroBase rate-limits anonymous downloads, so retry patiently.

Large optional databases (CheckM2, GTDB-Tk) are located through environment variables:

```bash
export CHECKM2_DB=/srv/db/checkm2
export GTDBTK_DATA_PATH=/srv/db/gtdbtk
```

Register external tool databases in `$BACMAP_HOME/refs/manifest.json` so every run record can name
the exact versions used:

```json
{"databases": [
  {"name": "gspec:card", "version": "3.2.6", "checksum": "sha256:..."},
  {"name": "gmlst:senterica_2", "version": "2026-09", "checksum": "sha256:..."}
]}
```

## 6. First verification

```bash
bacmap --version
bacmap doctor
bacmap start web &                        # http://127.0.0.1:8800
bacmap start mcp --read-only < /dev/null  # stdio smoke test; should exit cleanly
```

If these pass, continue with [Configuration](configuration.md) and the
[Tutorial](tutorial.md). For an external agent, follow [Agents & plans](../guide/agent-plans.md).

## 7. Common installation problems

| Symptom | Fix |
|---|---|
| `No module named 'dbos'` from pytest | Use `pixi run -e dev …`, not the system Python |
| `bacmap: command not found` | Run `pixi shell` or use `.pixi/envs/default/bin/bacmap` |
| `snakemake: command not found` | The workflow must run inside the pixi environment; activate it or run via `bacmap` |
| `sandbox unavailable` | Install Apptainer or Podman; `mine` cannot run without one |
| cgMLST scheme missing after rebuild | Re-run `gmlst scheme download <scheme>` |
| `database schema version N is newer` | You downgraded bacmap; restore the matching backup instead of opening it with older code |
