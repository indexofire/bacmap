# 概念

本节说明 bacmap 是如何组织的，以及为什么这样组织。在修改代码、审查安全边界或解读审计痕迹之前，
都应当先读这里。

<div class="grid cards" markdown>

-   **架构**

    ---

    分层、组件地图、依赖规则与请求流程。

    [架构](architecture.zh.md)

-   **数据模型**

    ---

    isolate → dataset → run、数据库、存储布局与生命周期。

    [数据模型](data-model.zh.md)

-   **任务引擎与门**

    ---

    DBOS 工作流、任务状态、四道门、恢复与审计事件。

    [任务引擎与 DBOS](task-engine.zh.md)

-   **安全与数据分级**

    ---

    D0–D4、MCP Profile、确认边界、沙箱与鉴权。

    [安全](security.zh.md)

-   **冻结设计**

    ---

    权威 ADR 正文；以中文版为准。

    [冻结设计](frozen-design.zh.md)

</div>

## 术语

| 术语 | 含义 |
|---|---|
| **isolate（菌株实体）** | 生物学菌株；跨测序批次保持稳定（`HZCPE-01`、`EVO-001-P037`） |
| **dataset（数据集）** | 一个测序文库或一个组装基因组（`HZCPE-01__ilm__20261012`） |
| **run（运行）** | 对一个或多个数据集的一次分析执行（`run_id`，不可变记录） |
| **task（任务）** | 引擎中的工作单元（`analyze`、`curate`、`mine`、`write`、`record`） |
| **plan（计划）** | 由智能体提出、带版本、需人工确认的一组类型化任务 |
| **gate（门）** | 确定性代码检查，可通过、拒绝或要求人工复核 |
| **approval（审批）** | 人工签批，使受门控的任务/发布得以继续 |
| **GOM** | Genome Object Model：不可变、带版本的分析/报告/任务对象 |
| **data class（数据分级）** | D0–D4 敏感度标签，用于约束端点与 MCP Profile |
| **profile（Profile）** | 固定的 MCP 权限上下文（`cloud` 或 `local-trusted`） |

## 阅读顺序

1. [架构](architecture.zh.md) —— 分层、组件与依赖规则。
2. [数据模型](data-model.zh.md) —— 身份标识、数据库与磁盘布局。
3. [任务引擎与门](task-engine.zh.md) —— DBOS、状态、门、恢复。
4. [安全与数据分级](security.zh.md) —— 信任边界与代码实际执行的部分。
5. [冻结设计](frozen-design.zh.md) —— 权威的 ADR 正文。

## 一次请求的端到端流程

```text
analyze task
  submit ──► DBOS workflow ──► Snakemake (fixed DAG)
                                   │
                                   ├─ gside: species
                                   ├─ gapit: screening/typing
                                   └─ gmlst: MLST/cgMLST
                                   │
                            runs/<task_id>/...
                                   │
                    run record + GOM + strain index
                                   │
                    analysis-claims gate ──► report
                                   │
                        task table / events / Web
```

**计划（plan）** 在执行前多出一个步骤：智能体创建一组类型化任务，人工确认精确的
`(plan_id, version, plan_hash)`，之后引擎才提交确定性的任务 ID。

## 有意*不*放进 bacmap 的东西

- 没有内置对话/助手（v1.6，ADR-21）；对话在外部进行。
- 对只需基因组的分析问题不实现生信算法；这些由 `gside`/`gapit`/`gmlst` 负责。
- 不允许 LLM 在运行时编辑管线；DAG 是冻结的、带版本的产物。
- 接口层不直接写存储；所有写操作都是任务。
