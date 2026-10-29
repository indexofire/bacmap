[English](README.md) | **简体中文**

# bacmap

本地病原菌基因组分析工作站：确定性分析管线、带门与不可变证据链的持久任务引擎，以及供外部
AI 智能体使用的 MCP 服务。数据不出本地网络。

冻结设计：[docs/concepts/frozen-design.zh.md](docs/concepts/frozen-design.zh.md)（中文权威，修订
**v1.9.3**）；[英文参考翻译](docs/concepts/frozen-design.md)。程序版本：**0.1.2**。

## 功能概览

- **确定性管线** — Snakemake 9：QC → 组装 → 物种 → 分型/耐药 → 报告。物种鉴定、基因筛查/血清型、
  MLST/cgMLST 分别交给 [gside](https://github.com/indexofire/gside)、`gapit`、`gmlst`（ADR-20）。
- **五类任务** — `analyze`、`curate`、`mine`、`write`、`record`。所有写入都经任务层；开放路径的
  脚本/草稿必须由人确认计划后才能执行。
- **持久执行** — DBOS 工作流逐步检查点，进程崩溃后从最后完成的步骤恢复；Snakemake 用
  `.snakemake` 续跑。
- **门 + 人工签字** — 分析结论、特征库发布、挖掘、引用四道门；智能体只能提议，计划确认与发布
  签字由人完成。
- **不可变证据** — run 级结果、`runs.sqlite` 运行记录、含哈希/工具版本/种子的 manifest、版本化
  GOM 对象。
- **仅 MCP 的智能体接入** — 26 个注册表工具 + 计划/任务/记录工具，按固定的 `cloud`（默认）或
  `local-trusted` 数据分级 Profile 裁剪。无内置对话（ADR-21）。
- **多种界面** — Web 任务台、CLI、TUI、JSON API `/api/v1`、MCP（stdio / Streamable HTTP）。

## 快速开始

```bash
git clone <repo> bacmap && cd bacmap
pixi install            # 运行时环境（Python 3.12 + 生信工具链）
pixi shell
bacmap --version        # 0.1.2
bacmap doctor           # 只读体检
bacmap web              # http://127.0.0.1:8800
```

第一次分析：

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>
```

智能体流程：

```bash
bacmap mcp --profile local-trusted     # 或直接用 bacmap mcp（cloud）
bacmap plan list
bacmap plan show <plan_id>
bacmap plan confirm <plan_id> --version 1 --hash <前12位>
```

## 文档

完整双语文档站：<https://indexofire.github.io/bacmap/>（中文 `/zh/`）。

| 我想… | 阅读 |
|---|---|
| 安装并验证 | [快速开始](docs/getting-started/installation.zh.md) |
| 配置端点、样本、MCP | [配置](docs/getting-started/configuration.zh.md) |
| 跟着智能体走一遍 | [教程](docs/getting-started/tutorial.zh.md) |
| CLI / Web / TUI / API | [界面](docs/guide/interfaces.zh.md) |
| 任务类型与门 | [任务与门](docs/guide/tasks.zh.md) |
| 身份、样本、记录 | [数据与身份](docs/guide/data.zh.md) |
| Hermes / Pi / DSH + 计划 | [智能体与计划](docs/guide/agent-plans.zh.md) |
| 结果、运行记录、GOM | [结果与证据](docs/guide/results.zh.md) |
| 架构与 DBOS | [核心概念](docs/concepts/index.zh.md) |
| 备份、升级、排障 | [运维](docs/operations/index.zh.md) |
| CLI/MCP/API/配置/工具精确参考 | [参考](docs/reference/index.zh.md) |

## 开发

```bash
pixi install -e dev
pixi run -e dev test        # pytest（当前基线：1610 passed）
pixi run -e dev lint        # ruff
pixi run -e dev typecheck   # mypy
pixi run -e dev contracts   # import-linter（5 条契约）
pixi run -e dev docs-build  # mkdocs，中英双语
```

> pytest/ruff 只在 dev 环境；必须带 `-e dev`，默认环境只有运行时依赖。

依赖方向与贡献规则：[开发](docs/development/index.zh.md) 与 [AGENTS.md](AGENTS.md)。

## 许可证

见 [LICENSE](LICENSE)。
