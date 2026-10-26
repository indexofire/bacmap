# AGENTS.md — 面向 AI 编码代理的工作指南

bacmap：本地病原菌基因组分析系统（单工作站、数据不出网、MCP-only 接入）。
本文件告诉任何在此仓库工作的 AI 代理：规则是什么、命令是什么、边界在哪里。

## 黄金规则（违反任何一条即返工）

1. **冻结文档是宪法**：`docs/architecture-frozen-v1.md`（v1.8.0）中标"冻结"的决策，
   修改必须在该文档第 10 节新增一条 `v1.8.x` 修订记录（原因、证据、迁移成本），
   并同步 `dev/research-framework-evidence.md` 的对应 §10.x 证据小节。
2. **依赖方向契约（ADR-02）**：`core/store/tools` 不得导入
   `agent/tasks/interfaces/workflow`；LLM 库只在 `agent.llm`、DBOS 只在 `tasks.engine`、
   MCP SDK 只在 `interfaces.mcp`/`store.knowledge`/`agent.llm`。import-linter（5 条契约）
   + `tests/unit/test_import_boundaries.py` 强制，改 imports 后跑
   `pixi run -e dev contracts`。
3. **类型安全**：禁止 `as any` / `@ts-ignore` 等价物（`# type: ignore`、
   静默 except、伪造可选性）。pydantic 模型在信任边界，内部用类型标注表达不变量。
4. **数据红线（ADR-16）**：D3/D4 永不出本地网络；cloud LLM 端点默认 D1、
   管理员最多放宽 D2。任何新代码涉及外发数据必须过 `DataPolicy` 检查。
5. **写操作唯一入口**：MCP 只暴露 read/compute 工具 + `bacmap_submit_task`；
   新工具的 `effect` 与 `output_data_class` 必须如实标注，写类工具不得直接注册进 MCP；
   MCP 按实例 Profile 裁剪数据级别（默认 `cloud`），提交者身份由服务端认定（v1.5）。
6. **生信分析外部化（ADR-20）**：只依赖基因组的分析一律外部工具
   （gside=物种鉴定、gapit=基因筛查/血清型、gmlst=MLST/cgMLST/MST），
   bacmap 只做编排、适配与"需结合本地数据的判定"。不要在 bacmap 里写生信算法。
7. **测试基线不得回退**：当前 1537 passed。删测试来"通过"是最严重违规。
   （v1.6.0 基线由 1546 调整为 1500、v1.6.1 再调整为 1489：前者因 ADR-21 移除内置会话助手时其专属测试随之删除，后者为清理仅被该助手使用的死代码；
   功能删除导致的合法调整，需在冻结文档修订记录与 CHANGELOG 中写明；不得借机删除保留功能的测试。）
8. **dev/ 目录不入库**：开发调研资料（证据/辩论）仅本地阅读（已 gitignore），
   架构等项目说明文档放 docs/ 并随仓库提交。
9. **文档双语制与及时同步**：英文为默认语言（README.md、docs/<name>.md），
   中文版带 `.zh-CN.md` 后缀；两版顶部有语言切换链接。改文档时两版同步改，
   架构冻结文档以中文版为权威（英文版为参考翻译）。
10. **功能变更必须同步文档**：新增或修改功能（工具、路由、任务行为、CLI、
    配置项）的同一批改动中，必须更新受影响文档——README 双语、
    docs/usage|configuration|installation 双语、docs/tools 双语（注册表变化时）。
    提交前自查：这个行为变化用户能在文档里读到吗？读不到就先补文档。
    涉及冻结决策的另走第 1 条修订流程。

## 命令速查

```bash
pixi install                    # 运行时环境（default）
pixi run -e dev test            # pytest —— 注意必须 -e dev（default 无 pytest）
pixi run -e dev lint            # ruff（src + tests）
pixi run -e dev typecheck       # mypy（src/bacmap，ADR-02/规则 3）
pixi run -e dev contracts       # import-linter
pixi shell                      # 激活后可用 bacmap / gside / gapit / gmlst / snakemake
bacmap mcp --read-only          # 只读 MCP 服务器（安全冒烟；默认 cloud Profile）
```

教训（真实踩坑）：`pixi run test`（不带 `-e dev`）会落到系统 Python 的 pytest，
报 `No module named 'dbos'` 式收集错误——不是代码坏了，是环境用错。

## 代码结构导览（src/bacmap/）

| 子包 | 职责 | 关键约束 |
|---|---|---|
| `core/` | 领域模型、表定义 | 最底层，不依赖任何上层 |
| `store/` | GOM/知识库持久化 | 只依赖 core |
| `tools/` | 工具注册表 + 26 个 bio_* 工具 | 只依赖 core/store |
| `workflow/` | Snakemake 规则（10 个 .smk）与脚本 | pending_gapit/pending_external_tool 占位等外部工具；物种鉴定整体交 gside |
| `tasks/` | DBOS 任务引擎、门、特征库 | 唯一导入 dbos 的模块（ADR-02） |
| `agent/` | 意图分类、LLM 网关、任务内智能体（解读）、沙箱、仲裁 | 仅 `agent.llm` 导入 pydantic-ai |
| `application/` | 应用服务（v1.5）：`PlanService` 版本化计划、统一错误 | 不得导入 interfaces/agent |
| `interfaces/` | mcp/（MCPServer）、web/（FastAPI + /api/v1）、cli/（bacmap 命令）、tui/（Textual 任务台）、views.py（共享只读视图） | 最上层 |

## v1.6 方向（ADR-21，改动前必读）

- 面向用户的对话交互由外部 Harness（Hermes / Pi / DSH）经 MCP 承担；**内置会话助手已于 v1.6.0 移除**
  （CLI ask/chat、Web /assistant、TUI 对话与计划确认）。不要重建对话 UI；任务内 pydantic-ai 智能体（解读、sandbox）保留。
- 计划确认与审批只在 bacmap 自有界面（Web/CLI）完成；MCP elicitation、Harness 工具审批不是确认证据。
  外部智能体的写入路径是 `bacmap_create_plan` → 人在 `bacmap plan confirm` 或 Web `/plans` 确认
  （`application/plans.py::PlanService` 是 CLI/Web/MCP 共用实现，不要在接口层另写一套）。
- 计划/任务关键转换写领域事件（`tasks/events.py`）；对外 JSON 接口放 `/api/v1`（`interfaces/web/api.py`），
  错误用 `application/errors.py` 的统一码。
- 接 Harness 的步骤与实测记录见 `docs/harnesses.md`（含 Hermes 0.17 全新 data root 引导失败的上游问题）。
- SQLite 表结构变更一律走 `store/migrations.py` 的编号迁移（只追加，不改已发布迁移）；
  不再新增裸 `CREATE TABLE IF NOT EXISTS` 式建表。

## 外部工具依赖（pixi [pypi-dependencies]）

- `gside`：PyPI 发布版（当前 ==0.1.4）
- `gapit ==0.5.6`、`gmlst ==0.5.5`：PyPI 发布版
- 升级这些工具后必须复核：CLI 接口签名 + bacmap 侧解析器 + V10 式单株冒烟

## 已知占位（等外部能力就绪后替换）

| 位置 | 占位值 | 等待 |
|---|---|---|
| `workflow/rules/dec_shigella.smk`、`vpara.smk` 血清型 | `pending_gapit` | gapit 血清型子命令 |
| `workflow/rules/annotation.smk` | `pending_external_tool` | gapit 注释子命令 |

> 物种与分类学鉴定已整体由 gside 承担（`species_identify` 规则 + `species_mode` 档位），
> 原 `species_ani`/`species_sourmash`/`taxonomy`/`vpara_targets` 占位规则已删除（v1.4.10）。

## 工作流（改动前必读）

1. 动手前读冻结文档中对应 ADR 条款；不确定是否冻结 → 当作冻结处理。
2. 完成后：`pixi run -e dev test && pixi run -e dev lint && pixi run -e dev typecheck && pixi run -e dev contracts`
   四绿才算完（CI `.github/workflows/ci.yml` 同序执行）；涉及行为变化的补证据小节（evidence §10.x，编号顺延）；
   按第 10 条同步文档后跑一次 `pixi run -e dev docs-build` 确认文档站可构建。
3. 提交信息跟随仓库风格（简短祈使句）；不主动 commit/push，除非用户明示。
4. 版本号：`vX.Y.Z`（冻结架构文档修订）与程序版本（`pyproject.toml`/`pixi.toml`）互相独立。
   文档修订不要顺手改程序版本；程序版本由用户裁定后显式升级（当前 0.1.1）。
