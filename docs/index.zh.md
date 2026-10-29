# bacmap

**bacmap** 是一个本地病原菌基因组工作站：一条确定性分析管线、一个带门且拥有不可变证据链的任务
引擎，以及一个面向外部 AI 智能体的 MCP 服务器。它专为单台 Linux 工作站设计——基因组与流行病学
数据永不离开本地网络。

```text
测序 reads / 组装好的基因组
        │
        ▼
  Snakemake 管线 ── gside（物种） ── gapit（筛查/血清型） ── gmlst（MLST/cgMLST）
        │
        ▼
  运行范围的结果 ──► GOM 对象 ──► 运行记录（哈希、版本、种子）
        │
        ▼
  门（分析 · 基线 · 挖掘 · 引用） ──► 人工签批 / 报告
        │
        ▼
  CLI · Web 任务台 · TUI · MCP（Hermes / Pi / DSH / 任意 MCP 客户端）
```

## 你能做什么

| 目标 | 从这里开始 |
|---|---|
| 安装 bacmap 并跑第一次分析 | [快速开始](getting-started/index.zh.md) |
| 配置样本、端点、MCP Profile | [配置](getting-started/configuration.zh.md) |
| 跟着智能体完成一次端到端会话 | [教程](getting-started/tutorial.zh.md) |
| 了解 CLI、Web 控制台、TUI 与 JSON API | [界面](guide/interfaces.zh.md) |
| 理解任务类型及其门 | [任务与门](guide/tasks.zh.md) |
| 登记菌株实体、数据集、元数据与实验室结果 | [数据与身份](guide/data.zh.md) |
| 接入 Hermes / Pi / DSH 并确认计划 | [智能体与计划](guide/agent-plans.zh.md) |
| 查找结果、运行记录与 GOM 对象 | [结果与证据](guide/results.zh.md) |
| 理解设计与信任边界 | [架构](concepts/architecture.zh.md) · [安全](concepts/security.zh.md) |
| 备份、升级或排障 | [运维](operations/index.zh.md) |

## 五分钟冒烟测试

```bash
git clone <repo> bacmap && cd bacmap
pixi install                 # 运行时环境（Python 3.12 + 生信工具）
pixi shell
bacmap --version             # 0.1.2
bacmap doctor                # 只读体检；仅在硬性失败时返回码为 1
bacmap web                   # http://127.0.0.1:8800
```

从 Web 控制台或 CLI 跑一次分析：

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>
```

或者让外部智能体（例如 Hermes）创建一个计划，然后由你亲自确认：

```bash
bacmap plan list
bacmap plan show <plan_id>
bacmap plan confirm <plan_id> --version 1 --hash <first-12-chars>
```

## 设计原则

- **默认确定性。** 分析 DAG 是固定的、版本化的，并从软件包部署；每次运行都会记录参数、
  工具/数据库版本、输入哈希与种子。
- **分析外部化。** 物种鉴定、基因筛查/血清型与 MLST/cgMLST 由 `gside`、`gapit` 和 `gmlst`
  完成（ADR-20）。bacmap 只做编排与适配，不重新实现生信算法。
- **写入都走任务。** 元数据、实验室结果、知识条目、分析与开放路径脚本都以任务形式提交，
  任何界面都不会直接写入。
- **人来确认与签字。** 智能体可以提出计划；只有人才能确认计划或在门上签字。模型永远无法
  自我证明已完成确认。
- **数据永不离开本地网络。** 无论配置如何，D3/D4 数据都由代码层面阻止发往云端 LLM 端点
  （ADR-16）。MCP Profile 进一步限制客户端可以收到什么。
- **历史不可变。** 结果是运行范围的，运行记录与 GOM 对象只追加，已发布的基线与特征库
  带版本。
- **没有内置对话。** 对话位于外部 Harness 中；bacmap 保留确定性管线，以及用于确认的受信
  界面（CLI、Web、本地对话框）（ADR-21）。

## 文档地图

```text
快速开始   安装、配置、教程
使用指南   界面、任务、数据、智能体/计划、结果
核心概念   架构、数据模型、任务引擎/DBOS、安全
运维       体检、备份/恢复、升级、排障
参考       CLI、MCP、HTTP API、配置、工具注册表
开发       环境、测试、契约、扩展能力
```

权威设计是冻结文档 [冻结设计](concepts/frozen-design.zh.md)（中文版为权威，英文版为参考
翻译）。程序版本与冻结文档修订相互独立：当前构建为 **0.1.2**，设计修订为 **v1.9.3**。
