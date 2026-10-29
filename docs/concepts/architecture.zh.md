# 架构

bacmap 是一个分层单体。分层由 import-linter 契约强制，而不只是约定。

## 1. 分层与依赖方向

```text
interfaces/     CLI · Web · TUI · MCP · views
     │
application/    PlanService, unified errors
     │
tasks/          DBOS engine, gates, records, events
     │
workflow/       Snakemake rules/scripts, workflow runner
     │
tools/          tool registry + bio_* handlers
     │
store/          SQLite services (GOM, runs, knowledge, metadata, datasets)
     │
core/           domain models, parsers, verifiers, species registry
```

硬性规则（ADR-02）：

- `core`、`store` 与 `tools` 不得导入 `agent`、`tasks`、`interfaces` 或 `workflow`。
- DBOS **仅**由 `bacmap.tasks.engine` 导入。
- MCP SDK 仅由 `interfaces.mcp`、`store.knowledge` 与 `agent.llm` 导入。
- LLM 库仅由 `agent.llm` 导入。

验证方式：

```bash
pixi run -e dev contracts
# Contracts: 5 kept, 0 broken.
```

## 2. 组件地图

| 组件 | 职责 | 关键模块 |
|---|---|---|
| Core | 领域类型、MLST/cgMLST 解析器、物种规范化、校验器 | `core/` |
| Store | SQLite 持久化：GOM、运行、元数据、实验室结果、知识库、数据集、菌株实体 | `store/` |
| Tools | 26 个注册工具 + 任务层工具处理器；`effect`/`data_class` 标注 | `tools/` |
| Workflow | 已部署的 Snakemake DAG、规则脚本、runner/deploy | `workflow/` |
| Tasks | DBOS 工作流/步骤、门、记录任务、事件日志 | `tasks/` |
| Application | 计划生命周期、版本/哈希确认、错误码 | `application/` |
| Agent | LLM 网关、角色提示、解读、沙箱 | `agent/` |
| Interfaces | CLI、FastAPI Web + `/api/v1`、Textual TUI、MCP 服务器 | `interfaces/` |

## 3. 请求流程

### 3.1 Analyze（闭环路径）

```text
CLI/Web/MCP plan
  → TaskEngine.submit
  → DBOS workflow
      register_inputs? → pipeline (Snakemake) → run record → GOM ingest
      → analysis-claims gate → report → cohort ingest
  → task table + events
```

管线在已部署的工作流目录 `$BACMAP_HOME/workflows/bacmap/` 中运行，结果重定向到
`$BACMAP_HOME/results/runs/<task_id>/`。输入登记在 `samples.tsv` 中；输入文件会计算哈希写入运行记录。

### 3.2 Plan（智能体路径）

```text
MCP bacmap_create_plan
  → PlanService.create (canonical JSON + input fingerprints + plan_hash)
  → state=awaiting_confirmation
human confirms in Web/CLI/local dialog
  → PlanService.confirm (re-check inputs, bind version/hash)
  → deterministic task IDs → TaskEngine.submit (idempotent)
  → plan state=submitted + task_ids
```

### 3.3 Record（写路径）

```text
CLI/Web/MCP bacmap_record_data
  → record task (metadata / lab / knowledge import / approve)
  → record step writes the corresponding store
  → task table + event
```

### 3.4 Mine（开放路径）

```text
confirmed plan
  → register input_paths zero-copy (SHA256)
  → read-only sandbox mounts
  → Python script (no network)
  → artefacts in workspace
  → mining gate → awaiting_approval → human signature
```

## 4. 外部分析工具（ADR-20）

bacmap 有意只做编排，而不重新实现：

| 问题 | 工具 |
|---|---|
| 这是什么物种？ | `gside species`（marker/panel/ANI/sketch/GTDB 档位） |
| 有哪些耐药/毒力/血清型基因？ | `gapit screen` + 分型方案 |
| MLST/cgMLST 谱是什么？ | `gmlst typing` |
| SNP 树 / 重组？ | 管线规则（IQ-TREE，可选 Gubbins） |

任何只需要基因组的新能力都应加到外部工具中并在 bacmap 侧做适配，而不是在 `core/` 里实现。

## 5. 部署与配置

- 工作流模板随包发布，部署到 `$BACMAP_HOME/workflows/bacmap/`，并带有内容哈希戳记。
- `samples.tsv` 与 `.snakemake` 状态在重新部署后保留。
- `config.yaml` 会被重写，使 `project_root` 指向 `BACMAP_HOME`。
- 路径一律来自 `bacmap.config`（环境变量 + `config.toml`），绝不来自 `__file__`。

## 6. 为什么是这个形态

- 单工作站 → SQLite + 文件目录，无服务端/守护进程。
- 可复现 → 固定 DAG、运行记录、不可变 GOM。
- 安全 → 门与人工审批位于模型之外。
- 外部智能体 → 窄的 MCP 接口面，并受 Profile 上限约束。
- 长时任务 → DBOS 步骤检查点，而不是进程内线程。

权威的理由说明与 ADR 历史见[冻结设计](frozen-design.zh.md)。
