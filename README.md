**English** | [简体中文](README.zh-CN.md)

# bacmap

A local pathogen genome analysis system (with a built-in agent layer), built on a
standalone architecture. The frozen design is documented in
[docs/architecture-frozen-v1.md](docs/architecture-frozen-v1.md) (v1.4.8).

## Overview

A pathogen genomic epidemiology analysis system for a **single workstation**
(64 GB RAM, data never leaves the local network):

- **Tool registry** (23 `bio_*` tools): read-only and compute tools are exposed directly; every write operation goes through task submission;
- **Task engine**: DBOS workflows (four task types, analyze / curate / mine / write, all checkpoint-resumable);
- **Snakemake 9 pipelines**: QC → assembly → typing → AMR/virulence → report;
- **Agent layer**: a local LLM (Strata / OpenAI-compatible endpoint) handles intent classification and interpretation drafting, with data-classification gating across the entire chain;
- **External tool division of labor** (ADR-20): species identification belongs to [gside](https://github.com/indexofire/gside), gene screening and serotyping to gapit, MLST/cgMLST/MST to gmlst. bacmap only does orchestration and judgment;
- **Integration**: MCP only (ruled in v1.4.8, stdio transport). Local clients such as Hermes / Claude / Codex can all connect.

## Quick start

Detailed documentation: [Installation guide](docs/installation.md) · [Configuration guide](docs/configuration.md) · [Usage guide](docs/usage.md)

```bash
pixi install          # 安装运行时环境（含生信工具链）
pixi shell            # 进入环境
bacmap --help         # 统一命令行入口
```

| Command | Description |
|---|---|
| `bacmap mcp [--read-only] [--home H]` | Start the stdio MCP server (22 tools) |
| `bacmap web [--host 127.0.0.1] [--port 8800]` | Start the web console: task management plus results browsing / search / reports (localhost only by default) |
| `bacmap --version` | Print the version |

Equivalent module form: `python -m bacmap.interfaces.mcp` / `python -m bacmap.interfaces.web`.

## Development

```bash
pixi run -e dev test        # pytest（基线：1039 passed / 1 skipped）
pixi run -e dev lint        # ruff
pixi run -e dev contracts   # import-linter 依赖方向契约
```

> Note: pytest and ruff are installed in the **dev environment**, so tasks must include `-e dev`;
> the default environment ships runtime dependencies only.

## Data directory layout (ADR-03)

No path is derived from the source tree location. Everything lives under `BACMAP_HOME`
(default `~/.local/share/bacmap`, overridable through the `BACMAP_HOME` environment variable):

```
$BACMAP_HOME/
├── data/            # 数据库（bacmap.sqlite 等）与参考库（reference/、db/）
├── results/         # 分析结果
├── workflows/       # 工作流文件
├── workflow_state/  # .snakemake 运行状态与日志
├── tasks.sqlite     # 任务表
├── dbos.sqlite      # DBOS 系统库
└── config.toml      # 可选配置（LLM 端点、路由、数据策略）
```

## Configuring third-party LLM APIs

All endpoints use the **OpenAI-compatible protocol** (the `pydantic-ai` openai channel). In `$BACMAP_HOME/config.toml`:

```toml
[llm.endpoints.strata]
location = "local"                # local | lan | cloud
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.endpoints.deepseek]          # 任意 OpenAI 兼容第三方 API
location = "cloud"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"  # 密钥从环境变量读取，不落盘

[llm.routing]
intent_classifier = "strata"
interpretation = "deepseek"

[llm.data_policy]
cloud_max_data_class = "D1"       # ADR-16：cloud 端点默认 D1，管理员最多放宽到 D2；D3/D4 永不
```

## Verification status (§8)

| Item | Content | Status |
|---|---|---|
| V1 | 12-strain gold-standard end-to-end run (Snakemake 9.x) | ✅ PASS |
| V3 | Intent classification / tool calling / mining samples / license (tested live on Strata, evidence §10.20) | ✅ 99/100 · tools 45/46 · mining 3/3 · license confirmed · IQ3_XXS single profile + arbitration |
| V4 | MCP connection from Hermes (22 tools) | ✅ Connected 2038ms |
| V8 | Three re-runs, identical field by field | ✅ IDENTICAL |
| V10 | gside/gmlst/gapit integration review | ✅ 10/12 (2 attributed: limits inherent to the marker method) |
| V11 | Enforcement of the six gates | ✅ all intercepted |
| V2/V6/V7 | DBOS recovery / pydantic-ai×Strata / same-machine arbitration | ✅ (completed with the migration steps) |
| V5 | Apptainer on Xinchuang Kylin V10 | ⏳ waiting for a physical machine |
| V9 | Cloud API + data-classification interception, live test | ⏳ waiting for API credentials |

## License

[MIT](LICENSE) © 2026 indexofire
