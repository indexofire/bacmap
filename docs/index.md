# bacmap

**bacmap** is a local pathogen-genomics workstation: a deterministic analysis pipeline, a task
engine with gates and an immutable evidence chain, and an MCP server for external AI agents. It is
designed for a single Linux workstation where genomic and epidemiological data must never leave the
local network.

```text
sequencing reads / assembled genomes
        │
        ▼
  Snakemake pipeline ── gside (species) ── gapit (screening/serotype) ── gmlst (MLST/cgMLST)
        │
        ▼
  run-scoped results ──► GOM objects ──► run record (hashes, versions, seeds)
        │
        ▼
  gates (analysis · baseline · mining · citation) ──► human approval / report
        │
        ▼
  CLI · Web task console · TUI · MCP (Hermes / Pi / DSH / any MCP client)
```

## What you can do

| Goal | Start here |
|---|---|
| Install bacmap and run the first analysis | [Getting started](getting-started/index.md) |
| Configure samples, endpoints, MCP profiles | [Configuration](getting-started/configuration.md) |
| Follow an agent-driven end-to-end session | [Tutorial](getting-started/tutorial.md) |
| Learn the CLI, Web console, TUI and JSON API | [Interfaces](guide/interfaces.md) |
| Understand task types and their gates | [Tasks & gates](guide/tasks.md) |
| Register isolates, datasets, metadata and lab results | [Data & identity](guide/data.md) |
| Connect Hermes / Pi / DSH and confirm plans | [Agents & plans](guide/agent-plans.md) |
| Find results, run records and GOM objects | [Results & evidence](guide/results.md) |
| Understand the design and trust boundaries | [Architecture](concepts/architecture.md) · [Security](concepts/security.md) |
| Back up, upgrade or troubleshoot | [Operations](operations/index.md) |

## Five-minute smoke test

```bash
git clone <repo> bacmap && cd bacmap
pixi install                 # runtime environment (Python 3.12 + bioinformatics tools)
pixi shell
bacmap --version             # 0.1.2
bacmap doctor                # read-only health check; exit code 1 only on hard failures
bacmap web                   # http://127.0.0.1:8800
```

Run an analysis from the Web console or CLI:

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>
```

Or ask an external agent (for example Hermes) to create a plan, then confirm it yourself:

```bash
bacmap plan list
bacmap plan show <plan_id>
bacmap plan confirm <plan_id> --version 1 --hash <first-12-chars>
```

## Design principles

- **Deterministic by default.** The analysis DAG is fixed, versioned and deployed from the package;
  every run records parameters, tool/database versions, input hashes and seeds.
- **Analysis is externalised.** Species identification, gene screening/serotyping and MLST/cgMLST
  are performed by `gside`, `gapit` and `gmlst` (ADR-20). bacmap orchestrates and adapts; it does
  not re-implement bioinformatics algorithms.
- **Writes go through tasks.** Metadata, lab results, knowledge entries, analyses and open-path
  scripts are submitted as tasks, never written directly by an interface.
- **Humans confirm and sign.** Agents may propose plans; only a person can confirm a plan or sign a
  gate. A model can never self-attest confirmation.
- **Data never leaves the local network.** D3/D4 data is blocked from cloud LLM endpoints by code,
  regardless of configuration (ADR-16). MCP profiles further limit what a client may receive.
- **History is immutable.** Results are run-scoped, run records and GOM objects are append-only,
  and published baseline libraries are versioned.
- **No built-in chat.** Conversation lives in the external harness; bacmap keeps the deterministic
  pipeline and the trusted surfaces (CLI, Web, local dialog) for confirmation (ADR-21).

## Documentation map

```text
Getting started   installation, configuration, tutorial
Guide             interfaces, tasks, data, agents/plans, results
Concepts          architecture, data model, task engine/DBOS, security
Operations        health checks, backup/restore, upgrades, troubleshooting
Reference         CLI, MCP, HTTP API, configuration, tool registry
Development       environment, tests, contracts, adding capabilities
```

The authoritative design is the frozen document
[Frozen design](concepts/frozen-design.md) (Chinese version is authoritative; English is a
reference translation). The program version and the frozen-document revision are independent:
this build is **0.1.2**, the design revision is **v1.9.3**.
