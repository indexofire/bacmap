# GBrain：长期知识库与知识图谱（PLAN #8）

> 状态：设计提案（2026-11-09），待用户确认后进入实施。

## 定位

GBrain 是 bacmap 的**知识层**——不是对话记忆，而是经过人工审核的结构化知识。
分两个核心：

1. **长期知识库**（已有基础）：文献/指南/经验条目，经引用门审核后入库
2. **知识图谱**（已有基础）：菌株-基因-表型-文献的关联网络

```
┌──────────────────────────────────────────────────────────┐
│                    GBrain 知识层                           │
│                                                           │
│  ┌─────────────────┐       ┌─────────────────────────┐  │
│  │  长期知识库       │       │  知识图谱                │  │
│  │  (knowledge.sqlite)│   │  (GOM + evidence_edges)  │  │
│  │                  │       │                          │  │
│  │  · 文献条目       │ ←──→  │  · 菌株→基因→表型        │  │
│  │  · 操作指南       │       │  · 菌株→run→分析结果     │  │
│  │  · 经验规则       │       │  · 研究→断言→证据        │  │
│  │  · 引用关系       │       │  · 分析→文献(引用门)     │  │
│  └─────────────────┘       └─────────────────────────┘  │
│                                                           │
│  统一查询接口：bacmap knowledge search + MCP 工具          │
└──────────────────────────────────────────────────────────┘
```

## 已有基础（0.1.3）

| 组件 | 现状 | GBrain 方向 |
|---|---|---|
| `knowledge.sqlite` | 文献条目 + 引用门 | 增加：操作指南、经验规则、自动摘要 |
| `evidence_edges` | 研究对象关联（cohort/plan/claim/experiment） | 增加：基因-表型-文献边 |
| `GOM genome_objects` | 菌株分析结果（含 summary） | 增加：跨样本知识提取（如"该物种常见 AMR 基因"） |
| `bio_search_samples` | 按特征搜索样本 | 增加：按知识语义搜索（"哪些菌株blaKPC阳性且研究过？"） |
| MCP `skill://` resources | 角色说明书 | 增加：GBrain 事实源（智能体可查询的知识） |

## 新增能力（设计）

### 1. 知识条目扩展

现有 knowledge.sqlite 只存文献。扩展为多类型：

```yaml
# 知识条目类型
- literature:     # 文献（现有）
    title, authors, year, doi, abstract, full_text_hash
- guideline:      # 操作指南（新增）
    topic, content, source, reviewed_by
- experience:     # 经验规则（新增，来自 mine 结果提炼）
    rule, evidence_ids, confidence, created_by
- summary:        # 自动摘要（新增，智能体生成 + 人工审核）
    topic, content, source_ids, generated_by, reviewed_by
```

### 2. 语义查询接口

```bash
# CLI
bacmap knowledge search "blaKPC 耐药机制"
bacmap knowledge related --gene blaKPC          # 该基因关联的菌株/表型/文献
bacmap knowledge graph --study <id> --depth 2   # 可视化知识图谱

# MCP（智能体可调）
bacmap_knowledge_search(query)                   # 语义搜索
bacmap_knowledge_graph(entity, depth)            # 图谱遍历
```

### 3. 智能体知识注入

智能体在分析时自动查询 GBrain 获取上下文：

```python
# agent/interpret.py 内
knowledge = gbrain.query(f"{species} {gene} resistance mechanism")
# → 返回已审核的知识条目 + 关联的本地数据
```

### 4. 知识自动积累

```
mine 沙箱产出 → 智能体提炼经验规则 → 人审核 → knowledge.sqlite
分析报告 → 智能体生成摘要 → 人审核 → knowledge.sqlite
```

## 与外部记忆系统的区别

| | GBrain | 外部记忆（如 Mem0/Zep） |
|---|---|---|
| 数据 | 结构化、经人工审核 | 非结构化、自动提取 |
| 存储 | 本地 SQLite（数据不出网） | 通常云端 |
| 查询 | SQL + 语义搜索 | 向量搜索 |
| 信任 | 引用门 + 审核签名 | 自动（无审核） |
| 角色 | bacmap 的知识基础设施 | 智能体的会话记忆 |

GBrain **不替代**外部记忆——它是 bacmap 的**领域知识库**，独立于任何 harness
或智能体存在。智能体的会话记忆由 harness 自行管理。

## 实施优先级

1. `knowledge.sqlite` 增加条目类型（guideline/experience/summary）——迁移 + 模型
2. `bacmap knowledge search/related/graph` CLI
3. MCP `bacmap_knowledge_search` 工具（D2，只读）
4. 智能体知识注入（`agent/interpret.py` 查询 GBrain）
5. 知识图谱可视化（Web 前端，Vue3 + D3.js force graph）
