**English** | [简体中文](README.zh-CN.md)

# bacmap

A local pathogen-genomics workstation: deterministic analysis, a durable task engine with gates and
an immutable evidence chain, and an MCP server for external AI agents. Data stays on the machine.

Frozen design: [docs/concepts/frozen-design.md](docs/concepts/frozen-design.md) (English reference;
the [Chinese version](docs/concepts/frozen-design.zh.md) is authoritative, revision **v1.10.18**).
Program version: **0.1.5**.

## Operating in natural language (the intended entry point)

bacmap **has no built-in chat window**: the conversation happens in an external agent (Hermes, Pi,
DeepSeek Harness or any MCP client), while bacmap exposes tools, plans and evidence over MCP. The
minimal sequence is five steps:

1. install and check the environment: `pixi install && pixi shell && bacmap doctor`;
2. configure that agent to start `bacmap start mcp` (config snippets are in
   [Agents & plans](docs/guide/agent-plans.md));
3. state the goal and an **absolute path** in the chat, for example:
   > Analyse the eight *V. parahaemolyticus* read sets in `/data/run42` with the standard pipeline.
4. the agent returns a **plan** (parameters, version, hash and a confirmation link). Only **you**
   can confirm it: open the Web link, approve the local dialog, or run
   `bacmap plan confirm` in a terminal;
5. after confirmation, keep asking in natural language:
   > Where is the run? When it finishes, summarise serotype and AMR, and list the samples I need
   > to review.

For the complete dialogue walkthrough see the [tutorial](docs/getting-started/tutorial.md). If you
came looking for “commands to memorise first”, that is not the intended path; the CLI is the
fallback and operations surface.


## What it does

- **Deterministic pipeline** — Snakemake 9 runs QC → assembly → QUAST assembly QC →
  Bakta annotation → eggNOG-mapper functional classification → species → typing/AMR → report.
  Short reads assemble with shovill, ONT/PacBio long reads with flye (`--nano-hq`/`--pacbio-hifi`),
  and hybrid input with unicycler. Species identification, gene screening/serotyping and
  MLST/cgMLST are delegated to
  [gside](https://github.com/indexofire/gside), `gspec` and `gmlst` (ADR-20).
- **Five task types** — `analyze`, `curate`, `mine`, `write`, `record`. Every write goes through the
  task layer; open-path scripts/drafts require a human-confirmed plan.
- **Durable execution** — DBOS workflows checkpoint every step, so a crash resumes from the last
  completed step; Snakemake resumes from `.snakemake`.
- **Gates + human sign-off** — analysis claims, baseline release, mining and citation gates; agents
  can propose, humans confirm plans and sign releases.
- **Immutable evidence** — run-scoped results, `runs.sqlite` records, manifests with hashes/tool
  versions/seeds, and versioned GOM objects.
- **MCP-only agent access** — 26 registry tools plus plan/task/record tools, filtered by a fixed
  `cloud` (default) or `local-trusted` data-class profile. No built-in chat (ADR-21).
- **Interfaces** — Vue 3 console at `/console/` (dark / light / gray themes, charts, approvals),
  CLI, TUI, JSON API `/api/v1`, MCP (stdio / Streamable HTTP).

## Quick start

```bash
git clone <repo> bacmap && cd bacmap
pixi install            # runtime environment (Python 3.12 + bioinformatics tools)
pixi shell
bacmap --version        # 0.1.5
bacmap config init      # optional: create config from config.example.toml
bacmap doctor           # health check
bacmap start web        # http://127.0.0.1:8800/console/
```

First analysis:

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>
```

Agent flow:

```bash
bacmap start mcp --profile local-trusted     # or plain `bacmap start mcp` for cloud
bacmap plan list
bacmap plan show <plan_id>
bacmap plan confirm <plan_id> --version 1 --hash <first-12-chars>
```

## Documentation

Full bilingual site: <https://indexofire.github.io/bacmap/> (Chinese: `/zh/`).

| Start | Read |
|---|---|
| Install and verify | [Getting started](docs/getting-started/installation.md) |
| Configure endpoints, samples, MCP | [Configuration](docs/getting-started/configuration.md) |
| Agent-driven walkthrough | [Tutorial](docs/getting-started/tutorial.md) |
| CLI / Web / TUI / API | [Interfaces](docs/guide/interfaces.md) |
| Task types and gates | [Tasks & gates](docs/guide/tasks.md) |
| Identity, samples, records | [Data & identity](docs/guide/data.md) |
| Hermes / Pi / DSH + plans | [Agents & plans](docs/guide/agent-plans.md) |
| Results, runs, GOM | [Results & evidence](docs/guide/results.md) |
| Research Workbench (P1) | [Research Workbench](docs/guide/research-workbench.md) |
| Architecture and DBOS | [Concepts](docs/concepts/index.md) |
| Backup, upgrades, troubleshooting | [Operations](docs/operations/index.md) |
| Exact CLI/MCP/API/config/tools | [Reference](docs/reference/index.md) |

## Development

```bash
pixi install -e dev
pixi run -e dev test        # pytest (current baseline: 2006 passed)
pixi run -e dev lint        # ruff
pixi run -e dev typecheck   # mypy
pixi run -e dev contracts   # import-linter (5 contracts)
pixi run -e dev docs-build  # mkdocs, both languages
```

> Always use `-e dev` for pytest/ruff; the default environment has runtime dependencies only.

Dependency direction and contribution rules: [Development](docs/development/index.md) and
[AGENTS.md](AGENTS.md).

## License

See [LICENSE](LICENSE).
