# 基因调查编排方案（PLAN #14）

> 状态：设计提案（2026-11-09），待用户确认后进入实施。

## 场景

用户输入一个基因/表型/感兴趣的领域（如"blaKPC"或"碳青霉烯耐药"），系统自动
完成端到端调查：

```
用户："调查 blaKPC 在本地的分布和耐药关联"
  ↓
┌────────────────────────────────────────────────────────┐
│ 编排引擎（bacmap research 链）                            │
│                                                         │
│  ① 本地检索      bio_search_samples --gene blaKPC      │
│  ② 关联分析      research create --gene blaKPC          │
│                 --test-name meropenem                   │
│  ③ 深度挖掘      mine（自定义统计/可视化脚本）              │
│  ④ 文献综述      智能体（外部 harness）检索 + 归纳         │
│  ⑤ 报告生成      research session → figure → report     │
│  ⑥ 知识积累      结果摘要 → GBrain（人工审核后）           │
└────────────────────────────────────────────────────────┘
  ↓
返回：结构化报告（本地数据 + 文献综述 + 统计图 + 知识图谱）
```

## 编排方案

### 入口：`bacmap research investigate`

```bash
# 一条命令启动完整调查
bacmap research investigate --gene blaKPC --test-name meropenem \
  [--run-id <限定某个 run>] [--auto] [--json]

# 或经 MCP（智能体调用）
bacmap_research_investigate(gene="blaKPC", test_name="meropenem", auto=False)
```

### 步骤分解

| 步骤 | 引擎 | 需人工确认 | 输出 |
|---|---|---|---|
| ① 本地检索 | 确定性（`bio_search_samples`） | 否 | 基因阳性菌株清单 |
| ② 关联分析 | 确定性（`research create`，P1 链路） | 否（read-only） | 2×2 表、OR/CI/p、figure spec |
| ③ 深度挖掘 | `mine` 计划（智能体脚本） | **是**（审核脚本 + 挖掘门签字） | 自定义统计/图表 |
| ④ 文献综述 | 外部智能体（harness 自行检索） | 智能体自行判断 | 文献摘要（引用本地知识库） |
| ⑤ 报告生成 | 确定性（session 产物） | 否 | report.md + figure.svg + manuscript.md |
| ⑥ 知识积累 | 智能体生成摘要 → 人审核 | **是**（知识门） | GBrain 知识条目 |

### 关键设计决策

1. **①②⑤ 是确定性的**——不需要计划确认，直接执行（read-only + P1 薄链路）
2. **③ 需要计划确认**——mine 是开放路径，脚本必须人工审核
3. **④ 在外部 harness 完成**——bacmap 不联网检索（ADR-16 红线）
4. **⑥ 需要人工审核**——知识入库必须过知识门

### 自动化级别

```toml
# config.toml
[research.investigate]
# auto = true 时，①②⑤ 自动执行，③⑥ 仍需人工确认
# auto = false 时，每步都需确认
auto = false
```

## 实现方式

### Phase 1：确定性链（①②⑤）

新增 `research investigate` 命令——串联现有功能：

```python
# research/investigate.py
def investigate(home, gene, test_name, run_id=None, auto=False):
    # ① 检索
    samples = bio_search_samples(gene=gene)
    # ② 关联分析
    session = research_create(run_id=run_id, gene=gene, test_name=test_name)
    # ⑤ 报告
    report = session.artifacts.report
    figure = session.artifacts.figure
    return {"samples": samples, "session": session, "report": report, "figure": figure}
```

### Phase 2：mine 集成（③）

智能体通过 MCP 提议 mine 计划（调查的深度挖掘部分），人确认后执行。

### Phase 3：文献综述集成（④）

智能体在 harness 中检索文献（外部工具），结果作为 `record knowledge-import`
任务写回 bacmap 知识库（引用门审核）。

### Phase 4：知识积累（⑥）

调查完成后，智能体生成摘要 → `bacmap record knowledge-import` → 人审核。

## 示例输出

```json
{
  "investigation_id": "inv-a1b2c3d4",
  "gene": "blaKPC",
  "test_name": "meropenem",
  "steps": {
    "search": {"n_positives": 12, "n_total": 156, "samples": [...]},
    "association": {"session_id": "rs-xxx", "odds_ratio": 25.3, "p_value": 0.001},
    "mining": {"task_id": "mine-xxx", "status": "awaiting_approval"},
    "literature": {"status": "delegated_to_harness"},
    "report": {"path": "research/rs-xxx/report.md"},
    "knowledge": {"status": "pending_review"}
  }
}
```

## 实施优先级

1. `research investigate` 命令（确定性链 ①②⑤）
2. MCP `bacmap_research_investigate` 工具
3. mine 计划自动提议（智能体根据调查结果提议挖掘方向）
4. 文献综述结果回流（`record knowledge-import`）
