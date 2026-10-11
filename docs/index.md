**English** | [简体中文](index.zh-CN.md)

# bacmap

A local pathogen genome analysis system with a built-in agent layer, for a single
workstation where data never leaves the local network. Frozen design:
[architecture-frozen-v1.en.md](architecture-frozen-v1.en.md) (reference translation;
the Chinese version is authoritative).

| Document | Content |
|---|---|
| [Installation](installation.md) | Requirements, pixi setup, reference database vendoring |
| [Configuration](configuration.md) | Paths, environment variables, config.toml, data classes |
| [Usage](usage.md) | CLI, web console, MCP agent access, tasks and gates |
| [Tool Reference](tools.md) | All 23 registry tools with full parameters |

Quick start:

```bash
pixi install && pixi shell
bacmap --help          # mcp / web / version
```
