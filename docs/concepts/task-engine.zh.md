# 任务引擎、DBOS 与门

bacmap 的任务层封装 **DBOS Transact**，这是一个持久化工作流库，把工作流与步骤状态存进 SQLite。
DBOS 属于内部执行细节：`tasks` 表才是公开的事实来源。

## 1. 为什么用 DBOS

长时间运行的生信工作必须能扛住进程重启，写操作必须可安全重试。DBOS 提供：

- 工作流（`@DBOS.workflow`）与步骤（`@DBOS.step`），带逐步检查点；
- 确定性工作流 ID（`SetWorkflowID(task_id)`），用于幂等的计划提交；
- 状态/结果查询与取消；
- 在 `DBOS.launch()` 时恢复未完成的工作流。

系统数据库为 `$BACMAP_HOME/dbos.sqlite`。它被包含在 `bacmap backup` 中，因此恢复后可以继续在线的工作。

## 2. 工作流与步骤

```python
@DBOS.workflow()
def analyze_workflow(params):
    rc = _step_run(params)                  # Snakemake
    run = _step_create_run(params)          # runs.sqlite
    _step_finish_run(run["run_id"], params) # manifest
    for sample in params["samples"]:
        summary = _load_summary(home, sample, run_dir)
        _step_ingest_gom(str(home), sample, run["run_id"], summary)
        gate = _step_gate(str(home), sample, text, str(run_dir))
        _step_report(sample, str(run_dir))
    _step_ingest_cgmlst_profiles(...)
    _step_ingest_cohorts(...)
```

| 工作流 | 步骤（节选） |
|---|---|
| `analyze_workflow` | 登记输入 → 管线 → 运行记录 → GOM → 门 → 报告 → 队列 |
| `curate_workflow` | 构建候选 → 发布门 → 审计 |
| `mine_workflow` | 登记数据集 → 沙箱 → 产物 → 挖掘门 |
| `write_workflow` | 草稿 → 引用门 → 审计 |
| `record_workflow` | 元数据 / 实验室 / 知识导入 / 审批 |

`current_step` 在步骤体内更新（`pipeline`、`run_record`、`sandbox`、`draft`、`curate_build`、`record` 等），
这样 Web/TUI 可以显示进度，而不改变工作流的执行顺序。

## 3. 任务状态与转换

```text
pending ──► running ──► succeeded
                │
                ├──► failed
                ├──► cancelled
                └──► awaiting_approval ──► succeeded | failed
```

- 终态（`succeeded`、`failed`、`cancelled`）不能被 `cancel` 改变。
- `status()` 在读取时把 DBOS 状态对账进 `tasks`；列表/计数端点调用同一套对账逻辑，
  因此仪表盘不会一直停留在 `running`。
- `approve()` 只允许从 `awaiting_approval` 发起；第二次审批是冲突（HTTP 409）。
- `cancel()` 调用 DBOS 取消，并把任务标记为 `cancelled`。

## 4. 计划与确定性提交

计划是一个带版本的任务集合。确认时绑定：

```text
(plan_id, version, plan_hash)
```

随后每个任务获得确定性 ID：

```python
plan_task_id(plan_id, version, index) = sha256(f"plan:{plan_id}:{version}:{index}")[:32]
```

`TaskEngine.submit` 使用 `INSERT OR IGNORE` 加 `SetWorkflowID(task_id)`，因此一次重复确认、
Web+CLI 的双击，或崩溃重试，都只会提交同一批任务一次。修订会创建新版本并取代旧版本；
旧哈希不能再被确认。

## 5. 门

门是 `tasks/gates.py` 中的确定性代码检查，不是 LLM 判断。

### 5.1 分析论断

在 `analyze` 结束时触发（以及由 `bio_verify_result` 触发）。输入：可选的解读文本 + 管线摘要。

- 物种规范化不受支持 → `reject`。
- NLI 反思器发现超出阈值的矛盾 → `needs_human_review`。
- 其他情况 → `pass`。

门的详情包含可验证/矛盾计数与阈值。

### 5.2 基线发布

由 `curate` 触发。要求：

- 候选非空，无重复菌株；
- 物种受支持；
- 有分离日期、地区（省或市）与样本来源；
- 特征白名单中不含 D4 键（第二道防线）。

任何问题 → `reject`；上一个发布保持不变。

### 5.3 挖掘

由 `mine` 在结束时触发，并在签批时再次触发：

- 产物非空；
- 每个产物都标记为可复现；
- `signed_by` 存在（签批人）。

未签名或为空 → `reject`。被拒绝的签批会使任务保持失败状态。

### 5.4 引用

由 `write` 触发：

- 从草稿中提取 PMID（`PMID:`、`[12345678]`）与 DOI；
- 与已批准的知识标识符（规范化后）比对；
- 未知引用 → `reject`（任务失败且不可签批）。

`known_citations=[]` 会自动加载已批准的知识库。

门结果作为 GOM `gate.<name>` 事件持久化到分析对象或任务对象上，可通过 `bacmap gom show`、
Web 与 `bacmap_task_result` 查看（cloud Profile 下仅返回计数）。

## 6. 人工确认与签批

这些**不是**门：

- **计划确认**（执行前）—— Web 页面、CLI、本机弹窗，或可选策略。
- **任务签批**（门要求人工之后）—— Web 签批卡片、TUI `Ctrl+Y`、CLI `task approve`。

操作者与时间戳会被记录（`plans.confirmed_by/confirmed_at`、`approvals` 表），并追加一条事件。
MCP elicitation 与 harness 工具审批永远不被接受为确认。

## 7. 事件与审计

`tasks.sqlite.events` 是带单调 `seq` 的只追加日志：

```bash
curl /api/v1/events?after=120
curl -N /api/v1/events/stream        # SSE, resumes from Last-Event-ID
bacmap events prune --days 180
```

事件用于协调，不是事实来源。断连之后应查询 tasks/plans。事件带 `data_class`；
cloud 接口按 Profile 过滤。

## 8. 恢复与并发

- 进程崩溃 → DBOS 从最后一个完成的步骤恢复工作流；Snakemake 从 `.snakemake` 恢复。
- 同一数据集的并发分析 → 每次运行写入自己的目录；管线之后的步骤读取该目录，
  因此看不到另一次运行的 latest 链接切换。
- 工作流部署 → 内容哈希；`samples.tsv` 与 `.snakemake` 得以保留。
- `bacmap backup` 包含 `dbos.sqlite`，因此恢复后可以继续在飞任务。

这些机制周边的信任边界见[安全](security.zh.md)。
