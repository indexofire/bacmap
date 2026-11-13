# 用户管理与团队/联邦模式设计（PLAN #31/#32）

> 状态：架构设计提案（2026-11-13），待用户确认后进入分阶段实施。
> 本文整合了两轮讨论：用户管理 + 智能体融合（PLAN #31）、团队/联邦 + 多智能体借鉴（PLAN #32）。

## 1. 用户管理系统（PLAN #31）

### 1.1 设计原则

- 智能体不是独立系统，是用户在 bacmap 里的"助手席"
- 用户唯一界面 = bacmap Web Console（数据视图 + 智能体对话面板）
- 智能体以当前登录用户的身份行动，权限 = 该用户的权限
- 审批门始终在 bacmap 自有界面完成（ADR-21 不变）

### 1.2 架构

```
┌─────────────────────────────────────────────┐
│           bacmap Web Console                │  ← 用户唯一入口
│  ┌─────────────┐  ┌─────────────────────┐  │
│  │  数据视图    │  │  智能体对话面板       │  │
│  │  样本/任务/  │  │  (内嵌 DSH/Hermes)   │  │
│  │  报告/审批   │  │  以当前用户身份行动    │  │
│  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────┘
         │                        │
    REST API (cookie)        MCP (user token)
         ▼                        ▼
   ┌─────────────────────────────────┐
   │         bacmap Engine           │
   │   Tasks / Gates / GOM / Audit   │
   └─────────────────────────────────┘
```

### 1.3 用户模型

| 层面 | 设计 |
|---|---|
| 用户表 | `users` 表（username/bcrypt_password/role/enabled） |
| 认证 | Cookie session（浏览器）+ user-scoped MCP token（智能体） |
| 角色映射 | 直接映射到现有 MCP Profile 体系 |
| 智能体身份 | 智能体不需要自己的账号——持有当前用户的 token |
| 审计 | 每个操作记录 `actor=user + agent=harness_name` |
| 审批 | 无论从对话面板还是数据面板发起，审批都在 bacmap 界面 |

### 1.4 角色定义

| 角色 | MCP Profile | 数据级别 | 典型权限 |
|---|---|---|---|
| `admin` | local-trusted | D4 | 全部 + 用户管理 + 策略配置 + auto_confirm 控制 |
| `analyst` | cloud | D2 | 提交分析 + 查看结果 + 审核门（挖掘签字/引用审核） |
| `viewer` | read-only | D1 | 查看聚合统计 + 已审核结果 |

### 1.5 智能体嵌入面板的用户级 token

当前 `[[web.agent_embed]]` 使用静态 URL。多用户模式下需要改为：

1. 用户登录 bacmap → 签发 user-scoped MCP token
2. 嵌入面板的智能体 URL 动态注入该 token
3. 智能体通过此 token 调用 bacmap MCP → 自动继承用户权限
4. 用户登出 → token 失效 → 智能体失去访问

```toml
# 配置不变，但 URL 中的 token 由 bacmap 动态替换
[[web.agent_embed]]
name = "DSH"
url = "http://127.0.0.1:3080/?token={BACMAP_USER_MCP_TOKEN}"
```

### 1.6 实施清单

- [ ] `users` 表 + bcrypt + session cookie
- [ ] FastAPI middleware：角色 → 允许的路由/操作
- [ ] MCP token 按用户签发/吊销
- [ ] agent_embed 动态 token 注入
- [ ] 审计事件增加 `actor_role` 字段
- [ ] CLI `bacmap login`（获取 token）
- [ ] Web 登录页 + 用户管理界面（admin only）

## 2. 团队/联邦模式（PLAN #32）

### 2.1 核心认知：信任域决定数据流向

ADR-16 的红线是"D3/D4 永不出**本地网络**"——"本地网络"指**信任域**，不是单台机器：

| 信任域 | 举例 | D3/D4 能否流动 |
|---|---|---|
| 同一信任域 | 省疾控专网内的各市实验室 | ✅ 可以——这就是"本地网络" |
| 跨信任域 | 跨省、国际、公共互联网 | ❌ 不可以——这才是红线 |

**流行病学研判发生在同一信任域内**：省级 Hub 汇聚各市完整数据做跨市分析。

### 2.2 分层联邦架构

```
┌─────────────────────── 省疾控专网（一个信任域）───────────────────────┐
│                                                                      │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐   │
│  │ 深圳实验室│    │ 广州实验室│    │ 佛山实验室│    │ 省级分析中心  │   │
│  │ bacmap   │    │ bacmap   │    │ bacmap   │    │ bacmap Hub   │   │
│  │ D0-D4    │    │ D0-D4    │    │ D0-D4    │    │ 汇聚 D0-D4   │   │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘    └──────┬───────┘   │
│       │               │               │                  │           │
│       └─── D3/D4 在信任域内自由流动 ─────────────────────┘           │
│                                                                      │
│  省级 Hub 可以：                                                     │
│  · 拉取各市完整基因组（D3）→ 跨市 SNP 系统发育树                     │
│  · 关联流调信息（D4）→ 传播链重建                                    │
│  · 跨市暴发簇检测（cgMLST 簇匹配）                                   │
│  · 综合研判：时间×地理×基因型×表型                                    │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
         │
         │  仅 D0/D1 聚合统计
         ▼
┌──────────────────┐
│  国家级/跨省 Hub  │  ← 跨信任域：只收聚合
└──────────────────┘
```

### 2.3 各层能力

| 层级 | 信任域 | 数据级别 | 能做什么 |
|---|---|---|---|
| 市级节点 | 各市实验室 | D0-D4 完整 | 本地分析、报告、AI 解读、自动监测 |
| 省级 Hub | 省专网（同一信任域） | 汇聚各市 D2-D4 | 跨市暴发检测、系统发育、传播链、综合研判 |
| 国家级 | 跨省（跨信任域） | 仅 D0/D1 聚合 | 全国趋势、异常信号 |

### 2.4 联邦协议

```bash
# 市级 → 省级推送（同一信任域，完整数据）
bacmap federate push --hub https://hub.cdc.gd.cn:8800 \
  --data-class D4 --scope "all,since:2026-11" \
  --token $HUB_TOKEN

# 省级 Hub 按需拉取指定市的数据
bacmap federate pull --node shenzhen.cdc.gd.cn:8800 \
  --samples "26SAL0501-26SAL0520" --include-genomes

# 省级 Hub 跨市分析
bacmap research create --run <hub-run-id> \
  --gene blaCTX-M-15 --test-name meropenem \
  --cohort "shenzhen+guangzhou+foshan"

# 跨省上报聚合（跨信任域）
bacmap federate report --national \
  --stats "species_distribution,st_distribution,amr_rates" \
  --period "2026-Q4"
```

## 3. 多智能体模式借鉴

### 3.1 核心同构关系

每个 bacmap 节点 = 一个智能体（拥有本地数据 + MCP 工具），联邦协议 = 智能体间通信协议。

| 多智能体模式 | 联邦 bacmap 对应 |
|---|---|
| Orchestrator + Workers | Hub bacmap 编排 + 各市 bacmap 执行 |
| Tool calling | MCP 工具 = 每个节点暴露的能力 |
| Shared memory / Blackboard | GOM + 证据链 = 不可变知识状态 |
| Human-in-the-loop | 审批门（plan confirm + gate signature） |
| Agent 角色权限 | MCP Profile（D1-D4 数据级别） |
| Autonomous bots | DBOS 定时工作流（常驻监测） |
| Crew / 多角色协作 | ADR-10 角色体系（analyst/curator/writer/epidemiologist） |

### 3.2 Orchestrator-Worker：跨市暴发调查

```
分析师: "调查华南地区近期沙门菌是否有跨市传播"
  ↓
Hub bacmap（Orchestrator）:
  步骤1 [并行分发]:
    → MCP调用 深圳节点.bio_search_samples(species="Salmonella", days=30)
    → MCP调用 广州节点.bio_search_samples(...)
    → MCP调用 佛山节点.bio_search_samples(...)
  步骤2 [聚合]: 合并 cgMLST 谱型 → 跨市聚类检测
  步骤3 [深入]: 发现簇 → 请求全基因组 → 跨市 SNP 树
  步骤4 [人审]: 生成调查计划 → 分析师确认
  步骤5 [产出]: 跨市研判报告 + 传播链推论 + 可视化
```

### 3.3 Bot 模式：常驻监测智能体

```yaml
[monitoring.amr_frequency]
schedule = "0 6 * * *"
rule = "AMR基因检出率环比上升>20%"
action = "创建调查计划 → 通知分析师"

[monitoring.cluster_detection]
schedule = "on_sample_ingest"
rule = "cgMLST 距离≤5 的簇包含≥3个不同来源样本"
action = "标记暴发信号 → Hub上报 → 提议深度分析"

[monitoring.cross_node_cluster]
schedule = "0 */4 * * *"   # 仅 Hub
rule = "跨市 cgMLST 簇匹配"
action = "创建跨市调查计划 → 各市分析师协同确认"
```

### 3.4 Crew 模式：多角色协同研判

```
流行病学智能体（epidemiologist role）
├── 时间-空间聚集性分析
├── 食品供应链追溯
└── 传播链假说生成
      ↓
生物信息智能体（analyst role）
├── 跨市 SNP/cgMLST 系统发育
├── 耐药基因组比对
└── 来源推断
      ↓
知识库智能体（literature role）
├── 相关文献检索
├── 阈值标准查证
└── 历史暴发案例对照
      ↓
写作智能体（writer role）
├── 综合报告起草
├── 引用门审核
└── 提交人审
```

### 3.5 技术新增

| 能力 | 实现 |
|---|---|
| 跨节点 MCP 调用 | Hub 注册远程节点工具为本地代理（`remote_<node>_<tool>`） |
| 调查任务类型 | `TaskType.INVESTIGATION`：自动分解→并行→聚合→人审→报告 |
| 监测 Bot | DBOS scheduled workflows：按规则自主触发调查 |

## 4. 实施路线

| 阶段 | 内容 | 时机 |
|---|---|---|
| **Phase 1** | 用户表 + 角色 + Cookie 登录 + agent_embed 动态 token | 单机多用户时 |
| **Phase 2** | 跨节点 MCP 调用（Hub 可查各市） + D0/D1 聚合上报 | 多实验室试点 |
| **Phase 3** | 调查任务类型（Orchestrator）+ 监测 Bot（定时工作流） | 省级网络成熟 |
| **Phase 4** | 多角色 Crew 协同研判 + 联邦查询 + 跨省预警 | 区域/国家级 |

## 5. 开放问题

- [ ] Hub 与节点间的认证：mTLS / shared secret / OAuth？
- [ ] 数据推送的冲突解决：同一样本多节点分析结果如何合并？
- [ ] 跨节点 cgMLST 簇检测的算法放 Hub 还是节点？
- [ ] 监测 Bot 的告警升级路径（节点 → Hub → 人）？
- [ ] 与现有传染病网络直报系统的对接方式？
