# 指南：选择一种界面

<div class="grid cards" markdown>

-   **界面**

    ---

    Web、CLI、TUI 与 JSON API：路由、命令、按键与鉴权。

    [界面](interfaces.zh.md)

-   **任务与门**

    ---

    五种任务类型、参数、状态与四道门。

    [任务与门](tasks.zh.md)

-   **数据与身份**

    ---

    isolate → dataset → run、`samples.tsv`、登记、记录与外部数据集。

    [数据与身份](data.zh.md)

-   **智能体与计划**

    ---

    MCP Profile、Hermes/Pi/DSH 配置、计划创建与人工确认。

    [智能体与计划](agent-plans.zh.md)

-   **结果与证据**

    ---

    run 级结果、报告、运行记录、GOM 对象与检索。

    [结果与证据](results.zh.md)

</div>

bacmap 有四类人工界面和一个机器接口。它们都对接同一个任务引擎，因此从 CLI 提交的任务在 Web
控制台中同样可见、可审批，经 MCP 创建的计划也在同一处确认。

| 界面 | 适用场景 | 写入能力 | 确认方式 |
|---|---|---|---|
| **Web**（`bacmap web`） | 日常工作、审阅报告、审批任务与计划 | 提交任务、审批、确认/拒绝计划 | 浏览器会话 + CSRF |
| **CLI**（`bacmap …`） | 自动化、脚本、无头服务器 | 提交/审批/取消、确认计划 | 显式命令 |
| **TUI**（`bacmap tui`） | 在工作站上监控 | 用键盘提交/审批 | 两步键盘确认 |
| **JSON API**（`/api/v1`） | 仪表盘与集成 | 提交/取消/确认 | bearer 令牌（可信界面） |
| **MCP**（`bacmap mcp`） | 外部智能体（Hermes/Pi/DSH） | **仅计划提案 / 记录类任务** | 从不确认；由人在别处确认 |

## 一张图看懂生命周期

```text
            ┌─────────────── human or agent ───────────────┐
            │                                              │
 CLI/Web/TUI submit ───────────────┐                      │
                                   ▼                      ▼
 MCP ── create plan ──► awaiting_confirmation ── human confirms ──► submitted
                                   │                      │
                                   └── reject/revise ◄────┘
                                                          │
                                                          ▼
                                  running ──► succeeded / failed / cancelled
                                                          │
                                          gate not passed │
                                                          ▼
                                                awaiting_approval
                                                          │ human signs
                                                          ▼
                                                     succeeded
```

## 常见路径

- **第一次分析**：[快速开始](../getting-started/index.zh.md) → [教程](../getting-started/tutorial.zh.md)。
- **日常提交与监控**：[界面](interfaces.zh.md)。
- **由智能体驱动的工作**：[智能体与计划](agent-plans.zh.md)。
- **样本登记与元数据**：[数据与身份](data.zh.md)。
- **结果、报告、运行记录**：[结果与证据](results.zh.md)。
- **任务类型与门**：[任务与门](tasks.zh.md)。

## 本文档使用的约定

```text
$BACMAP_HOME       data root, default ~/.local/share/bacmap
<sample_id>        dataset ID (the `sample` column in samples.tsv)
task_id            32 lowercase hex characters; CLI accepts unique prefixes
plan_id            16 hex characters; plans are versioned
run_id             immutable analysis-run identifier
D0 … D4            data classes (public → personal); see Security
```

所有命令示例都假定 `pixi shell` 已激活。任何命令都可以用 `--home DIR` 覆盖 `BACMAP_HOME`；
`--json` 让查询类命令输出机器可读结果。
