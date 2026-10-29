**English** | [简体中文](README.zh-CN.md)

# bacmap

A local pathogen-genomics workstation: deterministic analysis, a durable task engine with gates and
an immutable evidence chain, and an MCP server for external AI agents. Data stays on the machine.

Frozen design: [docs/concepts/frozen-design.md](docs/concepts/frozen-design.md) (English reference;
the [Chinese version](docs/concepts/frozen-design.zh.md) is authoritative, revision **v1.9.3**).
Program version: **0.1.2**.

## What it does

- **Deterministic pipeline** — Snakemake 9 runs QC → assembly → species → typing/AMR → report.
  Species identification, gene screening/serotyping and MLST/cgMLST are delegated to
  [gside](https://github.com/indexofire/gside), `gapit` and `gmlst` (ADR-20).
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
- **Interfaces** — Web task console, CLI, TUI, JSON API `/api/v1`, MCP (stdio / Streamable HTTP).

## Quick start

```bash
git clone <repo> bacmap && cd bacmap
pixi install            # runtime environment (Python 3.12 + bioinformatics tools)
pixi shell
bacmap --version        # 0.1.2
bacmap doctor           # health check
bacmap web              # http://127.0.0.1:8800
```

First analysis:

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>
```

Agent flow:

```bash
bacmap mcp --profile local-trusted     # or plain `bacmap mcp` for cloud
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
| Architecture and DBOS | [Concepts](docs/concepts/index.md) |
| Backup, upgrades, troubleshooting | [Operations](docs/operations/index.md) |
| Exact CLI/MCP/API/config/tools | [Reference](docs/reference/index.md) |

## Development

```bash
pixi install -e dev
pixi run -e dev test        # pytest (current baseline: 1610 passed)
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
