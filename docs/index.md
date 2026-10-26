**English** | [简体中文](index.zh-CN.md)

# bacmap

A local pathogen genome analysis system for a single workstation where data never leaves the local
network. Deterministic analysis (Snakemake + gside/gapit/gmlst), gates, an immutable evidence chain,
and MCP for external agents; conversation happens in Hermes / Pi / DSH, confirmations stay in bacmap. Frozen design:
[architecture-frozen-v1.en.md](architecture-frozen-v1.en.md) (reference translation;
the Chinese version is authoritative).

| Document | Content |
|---|---|
| **[Tutorial](tutorial.md)** | **Start here** — a narrative walkthrough from install to a signed report |
| [Installation](installation.md) | Requirements, pixi setup, reference database vendoring |
| [Configuration](configuration.md) | Paths, environment variables, config.toml, data classes |
| [Usage](usage.md) | CLI, web console, MCP agent access, tasks and gates |
| [Operations](operations.md) | Health checks, backup/restore, migrations, upgrades |
| [Agent harnesses](harnesses.md) | Hermes / Pi / DSH setup, data boundary, verification record |
| [Tool Reference](tools.md) | All 26 registry tools with full parameters |

Quick start:

```bash
pixi install && pixi shell
bacmap --help          # mcp / web / version
bacmap doctor           # is this workstation ready?
bacmap tui              # task console (needs a terminal)
```
