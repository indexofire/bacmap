[English](architecture-frozen-v1.en.md) | **简体中文（权威）**

# BacMAP Standalone 框架设计（冻结版 v1.4.10）

- **日期**：2026-10-09（v1.1–v1.4.7 同日修订，见第 10 节）
- **状态**：冻结（Frozen）。第 8 节的验证项全部通过后，转为"已确认"
- **依据**：第一轮辩论（`dev/debate-standalone-architecture.md`，本地资料不入库）、第二轮辩论（`dev/debate-round2-harness-vs-delivery.md`）、调研证据（`dev/research-framework-evidence.md`）（下文以"证据 §x"引用）
- **变更规则**：本文中标为"冻结"的决策，修改必须新增一条 ADR 修订记录（第 10 节），写明原因、证据与迁移成本；标为"可替换"的部分，只要不改接口即可自由替换实现

---

## 0. 项目定位（核心定义）

**bacmap 是一个用 Python 实现、可独立运行的本地病原基因组分析系统，内置 AI 智能体层，并通过 MCP 把自身能力开放给外部 AI 助手。**

| 问题 | 回答 |
|---|---|
| bacmap 是 Python 实现的 AI 智能体吗？ | 是，但智能体只是其中一层。核心是确定性分析内核（管线、GOM、校验、门）；智能体层（pydantic-ai + 本地模型或 LLM API，按数据分级路由）负责理解用户意图、解读结果、执行开放任务。去掉智能体层，确定性功能照常可用（C3） |
| 需要 Hermes 等平台吗？ | **不需要。** bacmap 自带 Web 界面、CLI 和内置智能体，直连本地模型服务（默认 Strata）或 LLM API（ADR-08），独立完成全部功能。Hermes 是可选的外部客户端之一（ADR-15） |
| 多个专家角色是"多智能体"吗？ | 不是多个智能体自主对话。是**代码编排的多角色**：同一个模型，按任务步骤用不同的角色配置（说明书 + 工具白名单 + 权限）临时创建智能体实例，做完即结束，角色之间只通过 GOM 和任务工作区交换结果（ADR-10） |
| 智能体层用什么实现？ | pydantic-ai 负责单个智能体内部的"调用模型—执行工具—校验输出"循环；多角色编排、任务状态机、门、请求队列由 bacmap 自己的代码实现（ADR-08、ADR-10） |
| 生信分析怎么做？ | 标准分析一律走 Snakemake 工作流（L1，唯一权威来源）；LLM 写的 Python/R 脚本只用于沙箱内的探索性挖掘（L2），其结果不能成为权威事实，可经人工改写验证后晋升为 L1（ADR-11） |
| 本地流行特征库是什么？ | 不是分析用的参考数据库，而是**本地菌株的流行病学特征集合**：存于 GOM，汇总本地菌株的分型、耐药、cgMLST 谱与时间/地点/来源，用于新分离株的特征比对与地方流行特征挖掘（ADR-19） |
| 通过 MCP 整合 AI 智能体工具吗？ | **方向相反：bacmap 是 MCP 服务端，不靠 MCP 组装自己。** 内置智能体在进程内直接调用工具注册表；MCP 是对外通道，让 Hermes、Claude、Codex、Cursor、Strata 聊天页等任何 MCP 客户端使用 bacmap 的工具。bacmap 也可以作为 MCP 客户端接入少量可选的外部能力（如 GBrain 知识库），但不依赖它们 |
| 其他 AI 助手能整合 bacmap 吗？ | 能。任何支持 MCP 的助手都能调用 bacmap 的工具，并通过 MCP prompts/resources 获得领域说明书（SKILL.md 内容）。写操作一律走"提交任务"，因此门对所有客户端同样生效（ADR-07、ADR-12） |

```
          外部 AI 助手（可选）                       bacmap（独立运行）
  ┌───────────────────────────────┐    MCP    ┌──────────────────────────────────┐
  │ Hermes · Claude · Codex ·     │ ───────▶ │ MCP Server ─┐                      │
  │ Cursor · Strata 聊天页 · ...  │          │ Web / CLI ──┼─▶ 任务层（门） ─▶ 内核 │
  └───────────────────────────────┘          │ 内置智能体 ─┘        ▲              │
                                              │      │ OpenAI 兼容 API │              │
                                              └──────┼─────────────────┼──────────────┘
                                                     ▼                 │
                                     Strata（本地默认）/ LLM API   Snakemake 9
```

---

## 1. 范围与硬约束

**功能范围**：病原微生物基因组分析、GOM 数据管理与挖掘、本地流行特征库构建（v1.2 更正：菌株流行病学特征，存于 GOM，不是分析用参考库）、报告与论文撰写。

**硬约束（不可协商）**：

| # | 约束 | 来源 |
|---|---|---|
| C1 | 单台 Linux 工作站/服务器即可运行，离线可用 | project.md §2.1 |
| C2 | 序列数据（D3）与个人及流调可识别信息（D4）**永不**出本地网络；单株分型结果（D2）默认不发公网端点，管理员可按 ADR-16 放行至 D2 为止；LLM API 只能接收数据分级允许的内容 | 第一轮裁决，v1.2/v1.4.3 细化；**用户已批准（2026-10-09，后续调整走修订流程）** |
| C3 | **没有 LLM 也能完成全部确定性功能**（分析、特征库发布、报告） | 本文新增，由 ADR-02 依赖方向 + ADR-06 确定性路径 + ADR-09 T0 档共同保证 |
| C4 | 每个结论挂证据链 `(strain_id, run_id)`：`run_id` 指向一次分析运行的完整运行记录，含分析时间、流程版本、全部参数、参考数据库与工具的实测版本、输入文件校验值（v1.2 由三元证据链扩展，ADR-18）；结果不可覆盖 | project.md §4.5–4.6 |
| C5 | LLM 产生的文本在展示、导出、入库之前必须过门 | 第二轮裁决，ADR-07 |
| C6 | 支持信创环境（麒麟/统信，含 ARM） | 第二轮辩论 |

---

## 2. 总体架构

```
┌────────────────────────── 接口层（可并存） ──────────────────────────┐
│  Web UI (FastAPI+Jinja2+htmx)   CLI   MCP Server   Hermes 插件适配器  │
└───────────────┬──────────────────────────────┬────────────────────────┘
                │ 提交任务 / 查询                │ 只读工具 / 提交任务
┌───────────────▼──────────────────────────────▼────────────────────────┐
│  bacmap.tasks   任务层：封闭任务类型 · 状态机 · 门 · 审批              │
│                 （TaskEngine 接口，默认实现 DBOS）                      │
├───────────────────────────────┬────────────────────────────────────────┤
│  bacmap.agent  智能体层        │  bacmap.workflow  工作流层              │
│  LLM 接入 · 角色 · 意图分类    │  Snakemake 9 CLI（WorkflowRunner 接口） │
│  开放路径运行时 · 沙箱         │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  bacmap.tools   工具层：ToolSpec 注册表（唯一事实来源）                  │
├─────────────────────────────────────────────────────────────────────────┤
│  bacmap.core    领域层：engine · analysis · typing · pathogens · verify │
│  bacmap.store   存储层：GOM · 索引 · 知识库（KnowledgeStore 接口）       │
└─────────────────────────────────────────────────────────────────────────┘
        依赖方向只能自上而下；core / store / tools 不得导入 agent
```

两条路径（第二轮裁决，本轮确认）：

| 路径 | 任务类型 | 驱动者 | LLM 的作用 |
|---|---|---|---|
| 确定性路径 | 分析、特征库发布、报告 | 任务状态机（代码） | 可选：写解读，必须过门 |
| 开放路径 | 数据挖掘、论文撰写 | 内置智能体运行时（pydantic-ai） | 写脚本、检索、成稿；在沙箱内执行；产物过门 |

> 注："报告"有两类（v1.4.3 明确）：①`analyze` 任务末尾的**模板化分析报告**（确定性路径，`generate_report` 式生成，不含自由文本或仅含已过门解读）；②`write` 任务的**定制撰写**（简报、论文，开放路径，过挖掘结论门/引用门后经人工签字产出）。"报告与论文撰写"功能横跨两条路径。

---

## 3. 架构决策记录（ADR）

每条 ADR 标注：**冻结**（改动须走修订流程）或 **可替换**（接口冻结、实现可换）。

### ADR-01 语言与运行时 —— 冻结
- **决策**：Python 3.12（`>=3.12,<3.14`）；pixi 是唯一的环境管理器，同时管理 Python 依赖与生信 CLI 工具；运行时不引入 Node/Bun。
- **理由**：全部现有资产为 Python（证据 §2.1）；LLM 接入、MCP SDK、持久化执行库均为 Python 一等支持；单一环境便于离线打包（C1、C6）。
- **否决**：TypeScript 外壳（第二轮已排除）；Rust 内核（按第一轮触发条件再议）。
- **反转成本**：极高。

### ADR-02 包结构与依赖方向 —— 冻结
- **决策**：单仓库、单个发行包 `bacmap`，按第 6 节划分子包；依赖方向用 `import-linter` 在 CI 中强制。
- **规则**：
  - `core`、`store`、`tools` 不得导入 `agent`、`tasks`、接口层
  - 只有 `bacmap.agent.llm` 可以导入 LLM 库（pydantic-ai/openai）
  - 只有 `bacmap.tasks.engine` 可以导入 DBOS
  - 只有 `bacmap.workflow` 可以调用 Snakemake
  - MCP **客户端**代码只允许出现在 `bacmap.store.knowledge`（可选外部知识后端，如 GBrain）与 `bacmap.agent.llm`（如需外部工具能力）；`bacmap.interfaces.mcp` 只实现 MCP 服务端（ADR-12）
- **理由**：把三个第三方依赖（LLM 库、持久化执行库、Snakemake）各自关在一个模块里，日后替换只改一处；保证 C3（去掉 agent 层，系统仍可运行）。

### ADR-03 配置与路径 —— 冻结
- **决策**：任何路径都不由源码位置推导。数据根目录 `BACMAP_HOME`（默认 `~/.local/share/bacmap`），配置文件 `$BACMAP_HOME/config.toml`，由 pydantic 模型加载与校验；生信工具从当前 pixi 环境的 PATH 解析。
- **理由**：现有 `config.py` 把 `PIXI_BIN`、`PROJECT_ROOT` 写死在开发仓库目录，插件靠软链接加载（证据 §2.2）——这是 standalone 无法安装的根因。

### ADR-04 工具契约 —— 冻结
- **决策**：每个工具由一个 `ToolSpec` 描述（第 4.1 节）：输入为 pydantic 模型，JSON Schema 由模型生成，取代手写的 973 行 `schemas.py`；返回统一的 `ToolResult` 信封。
- **工具元数据**（冻结字段）：`name`、`trust_layer`（L1/L2/L3）、`effect`（`read` / `compute` / `write`）、`long_running`、`version`、`output_data_class`（v1.2 新增：工具输出的数据级别 D0–D4，决定该输出能否发送给 LLM API，见 ADR-16）。
- **迁移**：现有 29 个 `handler(args: dict) -> str` 先用适配器包装接入，再逐个改写为类型化输入。
- **理由**：工具注册表是 MCP server、Hermes 插件、内置智能体三方共用的唯一事实来源（第二轮裁决）；`effect` 字段是门与权限控制的依据。

### ADR-05 工作流引擎 —— 冻结（引擎）/ 可替换（调用方式）
- **决策**：采用 Snakemake 9（v1.1 确认），pixi 中锁定为 `snakemake = "9.27.*"`，升级次版本需重跑 V1；只通过 CLI 子进程调用，封装在 `WorkflowRunner` 接口后面；保留 `.snakemake/` 断点续跑。
- **理由**：7.x 自 2023-08 停止维护；现有代码只用 CLI，且未使用 8.x 删除的指令（证据 §2.3、§4.1），升级成本低；CLI 是 7→8→9 中最稳定的契约。
- **否决**：继续锁 7.32（冻结 Python 版本）；改用 `snakemake.api` 进程内调用（必要性不足）。

### ADR-06 任务状态机 —— 冻结（接口与表）/ 可替换（执行库）
- **决策**：
  - 封闭任务类型：`analyze`、`curate`、`mine`、`write`（第 4.3 节；v1.2 将 `build_db` 更名为 `curate`，含义改为本地流行特征库构建，见 ADR-19）；新增类型需修订本 ADR
  - `TaskEngine` 接口的默认实现为 **DBOS Transact**（嵌入式、SQLite 系统库、MIT）
  - `tasks`、`approvals`、`analysis_runs`（ADR-18）、`baseline_releases`（ADR-19）四张表以及 GOM `events` 由 bacmap 自有，是对外可见的唯一状态；DBOS 系统库是内部实现细节，使用独立的 SQLite 文件
- **理由**：需要崩溃恢复、人工审批等待、长任务（96 株约 8 小时）；DBOS 是唯一同时满足"无服务进程 + SQLite + 人工等待 + 自动恢复"的方案（证据 §4.2）。自写这些的代价被两轮辩论低估。
- **兜底**：若验证项 V2 不通过，换为 `transitions` + SQLite 手写实现，接口与表不变。

### ADR-07 门 —— 冻结
- **决策**：门是任务步骤之间的代码检查点，由 `bacmap.tasks` 强制执行，任何接口层都无法绕过。
- **四道门**：

| 门 | 触发点 | 检查内容 | 不通过时 |
|---|---|---|---|
| 分析结论门 | 解读文本展示、导出或入库前 | deterministic verifier + NLI reflector（均为确定性代码，证据 §1 第 12 条） | 标记 `NEEDS_HUMAN_REVIEW`，进入审批 |
| 特征库发布门（v1.2 改） | 发布新的本地流行特征库版本前 | 纳入的每株菌：确定性校验（deterministic verifier）已通过、QC 合格、必填元数据（分离日期、地区、来源）完整、无重复菌株；个人信息已与特征数据分离；人工签名 | 拒绝发布，旧版本不变 |
| 挖掘结论门 | 挖掘产物进入报告前 | 沙箱内可复现 + 用户签字 | 产物留在工作区，不进入报告 |
| 引用门 | 论文/报告成稿前 | 每条引用都能在本地知识库中找到 | 标记缺失引用，拒绝导出 |

- **规则**：所有 `effect=write` 的操作只能经由任务提交；外部 MCP 客户端和 Hermes 不能直接写 GOM 或已发布数据库。
- **理由**：现有校验是"可选"的（第二轮 F5），本地小模型容易漏调。

### ADR-08 LLM 接入 —— 冻结（接口）/ 可替换（库）
- **决策**：pydantic-ai（锁定大版本）作为唯一的 LLM/智能体库，仅 `bacmap.agent.llm` 可导入。支持两类端点，地位相同、按配置选用（v1.2 明确）：
  - **本地模型服务**：默认 Strata（ADR-09），也兼容 vLLM、Ollama 等 OpenAI 兼容服务
  - **LLM API**：OpenAI 兼容 API（如 Z.AI GLM、DeepSeek、通义等，经 `OpenAIChatModel` + `base_url`），以及 Anthropic Messages API（经 pydantic-ai 的 Anthropic 模型）
  - 每个端点在配置中声明 `location`：`local`（本机）、`lan`（单位内网，如单位自建推理服务器，视同本地）、`cloud`（公网 API）；`cloud` 端点受 ADR-16 数据分级约束
  - 角色可分别路由到不同端点（例如意图分类用本地 Strata，文献综述成稿用 API 模型）
- **调用规则**（v1.1 按 Strata 的实际能力修订，证据 §8）：
  - 意图分类与解读生成必须使用结构化输出（JSON Schema），**解析失败即重试，最多 2 次，仍失败则按无 LLM 处理**——Strata 的结构化输出是"提示 + 事后校验"，没有语法约束解码
  - 结构化输出与工具调用**不在同一请求中混用**（Strata 拒绝 `response_format` + `tools`）：不带工具的调用用 `response_format`；带工具的智能体以"最终结果也是一个工具调用"的方式输出（pydantic-ai 的 Tool Output 模式）
  - 工具调用与分类请求一律关闭思考：`reasoning_effort: "none"`（等价于 `enable_thinking=false`）；开放路径的复杂推理可按任务开启 `low`/`medium`，并设置 `reasoning_budget_tokens`
  - Strata 部署时须安装 `jsonschema` 包，否则 `json_schema` 只校验"是否为 JSON 对象"
  - 上述规则以端点能力声明为准：配置中为每个端点标注 `supports_tools_with_schema`、`constrained_decoding`、`max_concurrency`；支持原生结构化输出的 API 端点可直接使用，代码不针对具体厂商写分支
- **理由**：同一个库覆盖结构化输出、工具调用、MCP 客户端、工具级人工审批（证据 §5.1、§6.1）；思考模式与工具调用的冲突是已知首要陷阱（证据 §5.2）。
- **否决**：LiteLLM（企业目录为付费许可、发布频繁）；直接手写 openai SDK 调用（需要自己实现校验重试与工具循环）。

### ADR-09 模型档位 —— 冻结
- **决策**：

v1.2 起，"能力档位"与"部署位置"是两个独立维度：档位决定能做什么，位置决定能看到什么数据（ADR-16）。

| 能力档位 | 示例 | 允许的用途 |
|---|---|---|
| T0 | 无 LLM | 全部确定性功能（C3） |
| T1 | 本地小模型（可选，不作默认） | 仅单步意图分类、受 Schema 约束的解读生成；**不得执行多步工具调用** |
| T2 | **Strata + Qwen3.8-Flash-Next**（本地默认）；能力相当的 LLM API 模型 | 意图分类、解读、多步工具调用、开放路径智能体 |

| 部署位置 | 示例 | 可接收的数据 |
|---|---|---|
| `local` / `lan` | Strata、单位内网推理服务器 | D0–D4 全部（仍受角色白名单约束） |
| `cloud` | GLM、DeepSeek、Claude 等公网 API | 默认 D0–D1；管理员可放宽到 D2；D3、D4 永不发送 |

- **v1.1 变更**：放弃 Qwen3-14B 作为本地默认模型；本地默认改为 Strata 运行的 Qwen3.8-Flash-Next（约 125B 参数 MoE），因此 T1 不再是必需档位，单一本地模型覆盖 T1+T2 的用途。
- **v1.2 变更**：取消原 T3 档，云端 API 按能力归入 T2，按位置受数据分级约束；本地无 GPU 的机器可只配置 API 端点运行（受数据分级约束，涉及 D2 以上数据的角色将拒绝启动）。
- **本地硬件基线**：NVIDIA/AMD 显卡 ≥12 GB 显存 + **系统内存 64 GB**（Strata 把专家权重放在内存，显存放其余部分；"64G" 按 Strata 要求理解为内存）+ SSD 约 80 GB。
- **量化档选择**：
  - 独占一台机器运行模型：IQ3_XXS（3-bit，加载部分约 47 GB，上下文 ≤128K）
  - 模型与分析管线共用一台 64 GB 机器：**IQ2_XS**（约 39 GB），或保持 IQ3_XXS 并启用 ADR-17 的资源仲裁
- 每个角色声明 `min_model_tier`；运行时发现配置的模型低于要求时，拒绝启动该角色，并提示用户改走确定性路径。
- **档位是单调的**：T2 涵盖 T1 的全部用途（配置只有 Strata 时，"最低档位 T1"的角色由 T2 模型执行）。
- **理由**：Qwen3-14B 在 BFCL V4 多轮工具调用中只有 34.8%（证据 §5.3）；Strata 在 12 GB 显存 + 64 GB 内存的普通 PC 上提供 OpenAI 兼容接口与工具调用，本机实测工具调用与结构化输出均可用（证据 §8）。Qwen3.8-Flash-Next 尚无公开的函数调用基准成绩，能否胜任以 V3 实测为准。

### ADR-10 多智能体协作 —— 冻结
- **决策**：
  - **supervisor 是代码**：意图 →（本地模型结构化分类）→ 封闭任务类型 → **拆解结果展示给用户确认** → 状态机按代码定义的步骤执行（v1.1：实测中模型给"跑样本+比较+写简报"多拆出一个未要求的 `build_db`——该任务类型 v1.2 起已更名为 `curate`，此处保留实测原貌，证据 §8）
  - **子代理串行执行**：本地模型服务是单槽位，同一时间只处理一个请求（ADR-17），子代理按队列串行运行，不并发
  - **这不是多个智能体自主对话的"多智能体系统"**，而是代码编排的多角色：按任务步骤用不同角色配置临时创建智能体实例（模型按 §4.5 路由，默认全部为本地 Strata 同一实例、串行；配置 API 端点后各角色可用异构模型），角色之间不自主对话（v1.2 明确，v1.4.3 修正"同一模型"的过时表述）
  - **角色由三类文件定义，各管一件事**（v1.2 明确）：

| 文件 | 内容 | 加载时机 | 能否约束权限 |
|---|---|---|---|
| `agent/principles.md`（全局原则，相当于 Hermes 的 SOUL.md） | 系统身份与通用原则：公卫合规、不编造结论、引用必须有出处、不确定时明说 | 每次都加载 | 不能 |
| `agent/skills/<角色>/SKILL.md`（说明书，agentskills.io 规范） | 该角色**怎么做**：方法、判读标准、输出格式 | 角色启动时加载 | 不能 |
| `agent/roles/<角色>.role.yaml`（角色清单，bacmap 自有格式） | 该角色**能做什么**：工具白名单、能力档位、可用端点位置、数据级别上限、文件范围、能否联网 | 由代码读取并强制 | **能，只有它能** |

  - 区分角色的依据是角色清单中的工具白名单与数据级别上限，由代码执行；SKILL.md 与全局原则只是给模型的指导
  - **子代理短生命周期**：领任务、读 GOM、写任务工作区、结束；子代理之间不直接通信
  - **不设 LLM 审核角色**：审核由门完成
- **角色表**：

| 角色 | 任务类型 | 最低档位 | 写权限 |
|---|---|---|---|
| 生信分析师 | analyze | T1（仅解读） | 无（结果由管线写入） |
| 特征库管理员（v1.2 替代"建库员"） | curate | T0 即可；T2 可选（元数据清洗建议、特征摘要） | 特征库暂存区 |
| 挖掘分析员 | mine | T2 | 任务工作区（沙箱内） |
| 文献查询员 | write、mine | T2 | 知识库导入暂存区 |
| 撰写员 | write | T2 | 任务工作区 |
| 流行病学专家 | analyze（cohort）、mine | T2 | 任务工作区 |

- **理由**：工具权限不能放在 SKILL.md 中，因为 agentskills.io 的 `allowed-tools` 仍是实验字段（证据 §7.4）；科研多智能体系统都收敛到"规划/执行 + 独立校验 + 显式溯源"的模式（第一轮附录 A）。

### ADR-11 开放路径执行与沙箱 —— 冻结（隔离要求）/ 可替换（技术）
- **决策**：开放路径由 pydantic-ai 智能体驱动；智能体写的脚本只能在沙箱中执行：
  - 默认使用 **Apptainer**：`--containall --cleanenv --network none`；任务工作区可读写挂载，GOM 导出数据只读挂载
  - SIF 镜像预先构建、带版本号、离线分发
  - 宿主机没有 Apptainer 时，回退到 rootless Podman（`--network none`）
- **L1 与 L2 的关系**（v1.2 明确）：
  - Snakemake 工作流（L1）是物种、血清型、MLST、耐药、毒力、溯源等结果的唯一权威来源；LLM 不得修改工作流规则
  - LLM 编写的脚本（L2）只产生探索性结果，过挖掘结论门并经签字后，在报告中标注为"探索性结果"引用，永不写入权威结果表
  - **晋升路径**：反复使用的 L2 脚本，由人改写为 Snakemake 规则或正式 `ToolSpec` 工具，补充测试并通过验证后进入 L1，原脚本与晋升记录写入 GOM `events`
- **理由**：Apptainer 是生信/HPC 的标准，单文件离线复现；Biomni 的教训是"必须隔离，且必须预打包环境"（证据 §6.2）；麒麟 V10 需开启非特权 userns。
- **Hermes 的定位**：不作为内置执行器（插件 API 无稳定性承诺，要求原生工具调用与 ≥64K 上下文，证据 §3.1、§6.1）；作为外部客户端经 MCP 或插件接入（ADR-15）。

### ADR-12 MCP 出口 —— 冻结
- **决策**：
  - **MCP 只用于对外**：内置智能体在进程内直接使用工具注册表（由 `ToolSpec` 生成 pydantic-ai 工具），不经过 MCP（v1.1 明确）
  - 使用官方 `mcp>=2.3,<3` 的 `MCPServer`，实现 2026-07-28 规范
  - 传输方式：stdio（本机客户端，如 Hermes）+ Streamable HTTP（仅绑定 127.0.0.1 或 unix socket，bearer token 鉴权）
  - 除 tools 外，把角色说明书（SKILL.md）以 MCP prompts/resources 暴露，使外部助手也能获得领域指引
  - 长任务返回作业句柄，另提供 `job_status`、`job_cancel` 工具；进度通过 `progressToken` 推送；Tasks 扩展等 SDK 支持后再采用
  - MCP 只暴露 `effect=read/compute` 的工具，以及"提交任务"类工具；不暴露直接写入
- **安全**：客户端配置中的启动命令写死；所有参数按 JSON Schema 严格校验；日志写 stderr（Logging 已弃用）。
- **理由**：证据 §7.1–7.3；Hermes 内置 `mcp==2.0.0` 客户端，与服务端同代（证据 §3.5）。

### ADR-13 数据层 —— 冻结（GOM）/ 可替换（知识库实现）
- **决策**：
  - SQLite（WAL）保留，GOM 表结构沿用（证据 §2.4），以 `PRAGMA user_version` + 编号 SQL 迁移脚本管理 schema 版本
  - 新增 `tasks`、`approvals`、`analysis_runs`（运行记录，ADR-18）、`baseline_releases`（本地流行特征库版本，ADR-19）四张表（v1.2：原 `db_releases` 取消）
  - 两类"数据库版本"严格区分（v1.2）：**参考数据库**（CARD、VFDB、PlasmidFinder、MLST/cgMLST 方案等，分析的输入）的版本记在运行记录中；**本地流行特征库**（分析结果的汇总）的版本记在 `baseline_releases` 中，凡结论引用了本地特征比对，同时记录所用特征库版本
  - 知识库通过 `KnowledgeStore` 接口访问；v1 实现为 SQLite FTS5（可选 sqlite-vec）；GBrain 可作为可选的 MCP 后端，不作为依赖
  - 结构化分析事实不进入向量库（project.md §8.3）
- **理由**：GOM 已经过七个版本验证。GBrain 以独立进程经 MCP 接入，Bun 运行时只存在于选择部署 GBrain 的机器上，**不进入 bacmap 运行时**，因此与 ADR-01（运行时不引入 Node/Bun）不冲突；代价是启用该后端的机器需额外维护一个 Bun 服务，故仅为可选项。

### ADR-14 Web UI —— 可替换
- **决策**：FastAPI + Jinja2 + htmx + SSE；从只读看板升级为主交互入口（任务提交、对话、审批、签名）；默认只绑定本机，局域网访问需开启鉴权。
- **理由**：一线用户不使用终端（第二轮）；不引入前端工程（ADR-01）。

### ADR-15 Hermes 的角色 —— 可替换（v1.1 重写）
- **定位**：Hermes 是 bacmap 的**可选外部客户端之一**，与 Claude、Codex、Cursor、Strata 聊天页等地位相同。bacmap 不依赖 Hermes 运行，也不把任何核心功能放在 Hermes 里。
- **不是"其他助手无法整合 bacmap"**：任何 MCP 客户端都能使用 bacmap 的全部工具与说明书（ADR-12）；门在 bacmap 任务层执行，与客户端无关（ADR-07）。
- **Hermes 相对普通 MCP 客户端多出的价值**（这是保留它的理由，而非依赖它的理由）：

| 能力 | 用途 | 证据 |
|---|---|---|
| 消息网关（Telegram、Slack、Signal 等） | 实验室人员在手机 IM 里查询结果、接收任务完成通知 | 证据 §3 |
| cron 定时任务 | 定时检查新上机数据、生成周报 | 证据 §3 |
| 插件钩子（`pre_tool_call` 可阻断、`transform_llm_output`） | 在 Hermes 对话中对解读文本再加一道门 | 证据 §3.4 |
| 已有插件资产与使用习惯 | hermes-bacmap 用户平滑过渡 | — |

- **接入方式**：仅 MCP（Hermes 配置 `mcp_servers` 指向 bacmap，stdio）。v1.4.8 用户裁定取消插件第二渠道：`bacmap.adapters.hermes` 与 `hermes_agent.plugins` entry-point 已删除（V4 实测 ✓ Connected / 22 工具）。
- **门的机制**（v1.4.8 起单一通道）：MCP 通道由 bacmap 服务端强制（只暴露 read/compute 工具 + 任务提交，ADR-12）。原插件通道的 Hermes 钩子防线（`pre_tool_call`/`transform_llm_output`）随通道取消一并废止。
- **不做的事**：不用 Hermes 作内置执行器（插件 API 无稳定性承诺，证据 §3.1）；不要求用户安装 Hermes。
- **理由**：现有 entry-point 声明不生效，插件靠软链接加载（证据 §2.2）；MCP 让 Hermes 与其他助手走同一条路径，维护一份代码。

### ADR-16 安全红线与数据分级 —— 冻结
- **数据分级**（v1.2 新增）：

| 级别 | 内容 | 能否发送给 `cloud` 端点 |
|---|---|---|
| D0 | 公开知识：文献、公共数据库条目、方法说明、用户的一般性提问 | 可以 |
| D1 | 去标识的聚合统计：如本地各 ST 的占比、某年耐药基因检出率 | 可以 |
| D2 | 单株分型结果：某株的物种、血清型、ST、耐药基因（不含个人信息与精确地点） | 默认不可，管理员可开启 |
| D3 | 序列与比对数据：reads、组装、等位基因谱、SNP 矩阵 | **永不** |
| D4 | 个人与流调可识别信息：患者姓名、电话、病例细节、精确住址 | **永不** |

- 执行方式：每个工具声明 `output_data_class`（ADR-04）；`bacmap.agent.llm` 在发出请求前检查本次上下文中所有内容的最高级别，超过端点允许级别即拒绝发送并记录事件；角色清单声明 `max_data_class`，路由到 `cloud` 端点的角色若需要更高级别数据，则拒绝启动
- 现有 `strain_metadata` 含患者姓名、电话等字段（证据 §2.4），这些字段一律为 D4，不进入发往 `cloud` 端点的请求，也不进入本地流行特征库的特征表
- 序列与流调数据不出本地网络
- 智能体生成的代码只在沙箱中运行，不联网
- 所有对外接口默认只绑定本机
- 数据库发布与报告导出需要人工签名，签名记录写入 `approvals` 与 GOM `events`


### ADR-17 本地模型资源仲裁 —— 冻结（v1.1 新增）
- **背景**：Strata 是单槽位服务，不并发处理请求；模型常驻内存约 39–47 GB，与 SPAdes/shovill 组装等内存密集步骤在 64 GB 机器上会争抢内存（本机实测：Strata 进程常驻 44.6 GB，系统可用内存约 6 GB，证据 §8）。
- **决策**：
  - `bacmap.agent.llm` 内设单一请求队列，所有 LLM 调用串行发出；每个请求带超时，超时按无 LLM 降级
  - 任务层在启动内存密集的工作流步骤前检查可用内存；不足时调用 Strata `POST /unload` 释放模型，步骤结束后 `POST /load` 重新加载（加载需 1–3 分钟），期间 LLM 请求排队或降级
  - 配置项 `llm.resources.co_located`（见 4.5 示例）：模型与管线是否同机。同机时默认启用仲裁；模型在独立主机上时关闭
- **理由**：不仲裁时，组装可能因内存不足失败，违反"同一样本重跑结果一致"的要求；把模型视为可抢占资源，保证 C3（确定性功能优先于 LLM）。

### ADR-18 运行记录与可复现性 —— 冻结（v1.2 新增）
- **背景**：同一样本多次分析可能因参数、数据库版本、工具版本不同或工具本身的随机性而得到不同结果。现状是：`pipeline_version` 为手写标签（如 `salmonella-workflow-v0.1`），工具与数据库版本是 `ingest_results.py` 中的常量而非运行时实测值，工作流参数完全不记录，`created_at` 是入库时间而非分析时间，iqtree 未固定随机种子（证据 §9）。
- **决策**：
  - 证据链由三元组扩展为 `(strain_id, run_id)`；每次执行工作流生成一条不可修改的**运行记录**（`analysis_runs` 表 + 运行目录内的 `run_manifest.json`，两者内容一致，后者带 SHA256）
  - 运行记录字段（第 4.6 节）：分析开始与结束时间、入库时间；流程版本（工作流目录的 Git commit，有未提交改动时记录差异摘要并标记 `dirty`）；**完整的解析后参数**（config.yaml 与所有覆盖项合并后的全文及其哈希）；参考数据库清单（名称、版本、文件校验值）；工具版本（运行时调用各工具 `--version` 实测，以及 `pixi.lock` 的哈希）；输入文件 SHA256；随机种子；主机与 CPU/线程数；触发者与任务 ID
  - 涉及随机性的工具一律固定种子并把种子写入参数（如 iqtree `-seed`）；无法固定的步骤在运行记录中标记 `nondeterministic_steps`
  - LLM 生成的解读另记：端点、模型标识、位置、角色清单与说明书的 Git 版本（即 `prompt_version`）、采样参数
  - 不覆盖旧结果：每次运行产生新的结果版本，GOM 对象指向 `run_id`
  - 提供"运行比较"工具：对同一样本的两次运行，逐字段比较结果，并把差异归因到参数、数据库、工具版本、输入的不同；若运行记录中这些全部相同而结果不同，标记为不可复现并告警
- **理由**：分析时间只能说明"何时"，解释不了"为何不同"；参数与版本才是差异的来源。证据链必须能回答"这个结论是用什么、怎么算出来的"。
- **验证**：V8。

### ADR-19 本地流行特征库 —— 冻结（v1.2 新增）
- **定义**：本地流行特征库不是分析用的参考数据库，而是**本辖区菌株流行病学特征的版本化集合**，存于 GOM，用于：
  - 新分离株与本地背景的特征比对：该 ST/血清型/耐药谱在本地是否常见、是否首次出现、cgMLST 最近邻与聚类归属
  - 地方流行特征挖掘：时间趋势、地区分布、来源（食品类别、临床/环境）关联、耐药变化
- **构成**：
  - 纳入菌株清单：每株指向其分析结果版本与 `run_id`
  - 特征表：分型（物种、血清型、ST、cgMLST 型/簇）、耐药与毒力基因、质粒；时间（分离日期）、地区（到区县）、来源类别；**不含 D4 个人信息**
  - cgMLST 本地参考谱：现有 `build_cgmlst_reference.py` 与 `cgmlst_projection.py`（最近邻投影与暴发/相关/无关判定）即属于本库，迁入后由特征库版本管理
  - 汇总统计快照：按病原、年份、地区、来源的分布
- **版本与发布**：`curate` 任务生成候选版本 → 特征库发布门（ADR-07）→ 人工签名 → 写入 `baseline_releases`；已发布版本不可修改，新增菌株产生新版本
- **使用规则**：凡结论用到本地特征比对（如"本地首次出现"、"与 2025 年某暴发株同簇"），证据中记录所用 `baseline_version`
- **理由**：现有 `strain_metadata`（地区、分离日期、来源、暴发编号）、`strain_genotype_index`、`strain_amr_genes`、cgMLST 本地参考库已经具备特征库的数据基础（证据 §2.4、§9），缺的是版本化、发布门和去标识。

### ADR-20 标准外部工具链 —— 冻结（v1.3 新增）
- **决策**：分型与筛查类分析采用以下三个标准外部工具，均为同一作者的 agent-first CLI（统一 JSON 输出、自带版本号、文档化退出码）：

| 职责 | 工具 | 形态 | 在工作流中的位置 |
|---|---|---|---|
| 物种鉴定 | **gside** | Python CLI（git 安装，暂未上 PyPI），MIT，**开发中——路线图包含 GTDB-Tk 鉴定档**（v1.4 确认） | `species` 规则：`gside species --mode marker\|panel\|mash_refseq\|sourmash\|all` |
| MLST / cgMLST / wgMLST 分型 + 最小生成树 | **gmlst** | PyPI `gmlst>=0.1.4`（已在环境中） | `typing` 规则：`gmlst typing mlst/cgmlst`；cohort MST 用 `gmlst visual`，替代自写 MST 脚本 |
| 基因与基因簇鉴定（AMR/毒力/质粒/血清型靶点/自定义库） | **gapit** | PyPI `gapit>=0.5`，MIT | `screen` 规则：`gapit screen`（contigs 经 BLAST，reads 经 minimap2），替代 abricate 与自写基因扫描 |

- **职责分界原则**（v1.4.5 新增，用户裁定）：**只依赖基因组的分析（基因筛查、物种鉴定、分型及其判定）一律外部工具化（gapit / gside / gmlst）**；**需要与分析结果之外的数据结合的判定留在 bacmap**——cgMLST 对本地特征库的最近邻投影与暴发/相关判定（ADR-19）、多方法物种结果的共识合并（species_consensus）、结果与流调元数据的关联。bacmap 消费分析结果，再与其他数据结合。
- **genome_annotator 归属待定**（v1.4.5 标记）：按上述原则，pyrodigal 进程内注释也应外部工具化，但 gapit/gside/gmlst 目前均无注释能力。在 gapit 提供注释子命令之前，genome_annotator 暂留 bacmap，仅作为 L1 工作流步骤被调用；gapit 具备该能力后按本 ADR 修订流程外移。
- **工具输出契约**：三者输出均含工具名与版本（gside JSON 顶层 `tool`/`version`；gapit 版本化 schema `gapit.report/1` 等；gmlst 为同族约定、以 V10 实测为准），入库时解析进 `AnalysisRun.tool_versions` 与结果 payload——ADR-18 的"运行时实测版本"以输出 JSON 内嵌版本为准，缺项时回退 CLI `--version` 探测。
- **替换关系**（对 hermes-bacmap 现有实现）：

| 现有模块 | 去向 |
|---|---|
| `analysis/species_identifier.py`、`taxonomic_validator.py`、`sourmash_identifier.py`、`ani_identifier.py`、`species_consensus.py`、五档 `bio_db_setup` | **由 gside 取代，且 v1.4.7 用户裁定立即生效**：不等第 5 步，上述模块与 `bio_validate_taxonomy`/`bio_species_compare`/`bio_db_setup`/`bio_db_status` 工具已从 bacmap 删除（注册表 29→24）；工作流 species/taxonomy/vpara_targets 规则输出 `pending_gside` 占位，第 5 步接入 `gside species` 后替换。direct blastn 编排类规则（abricate/amrfinder/vpara_virulence/kraken2_prefilter）保留至第 5 步统一换装 |
| `analysis/gene_scanner.py` 及其在 AMR/毒力/质粒筛查中的调用 | **由 gapit 取代**（contigs 与 reads 双通道，abricate 兼容 TSV + JSON） |
| ecoh / shigella / vpa 血清型模块（扫描**与判定**） | **整体迁入 gapit**（v1.4.5 裁定，v1.4.7 最终确认：不留过渡恢复——曾于 v1.4.6 作为迁移脚手架短暂恢复，用户明确推翻）。bacmap `core/typing` 与 `bacmap/typing` 垫片均已删除；工作流 ecoh/shigella/vpa 血清型规则输出 `pending_gapit` 占位（保留规则名与输出契约），第 5 步接入 gapit 血清型子命令后替换 |
| cgmlst cohort 自写 MST 脚本 | **由 `gmlst visual` 取代** |
| `engine/` 的 SequenceMatcher 抽象与 blast/kma 后端 | 筛查职责交给 gapit 后收缩；ReadMapper（bwa/bowtie2 SNP 比对）保留 |
| GTDB-Tk 标准档（101GB+140GB RAM） | **不由 bacmap 直接集成，由 gside 的 GTDB-Tk 档提供**（开发中）；该档就绪前，标准路径为 marker/panel/mash/sourmash（`all` 仲裁），与单工作站约束一致。gside 发布 GTDB-Tk 档后，`all` 仲裁自动纳入，bacmap 适配器按模式可用性探测，无需改架构 |

- **数据库版本管理**：三个工具自带的数据库（gside panel/mash sketch、gapit 的 card/vfdb/plasmidfinder 等、gmlst 的 scheme）在部署时登记进 `AnalysisRun.ref_databases`（名称、版本、目录校验值）；工具自管的下载目录通过 ADR-03 的 `BACMAP_HOME` 规划（如 `$BACMAP_HOME/refs/{gside,gapit,gmlst}/`），不再散落各仓库 `data/`。
- **依赖管理**：pixi 的 pypi-dependencies 增加 `gapit`、`gmlst`、`gside`（gside 在上 PyPI 前以 git+commit 锁定）；外部二进制 blast/minimap2/skani/mash/sourmash/kma/mummer 均已在现有 pixi 清单中。
- **标准工具质量门槛**（v1.4 新增；进入 L1 标准路径的外部工具必须满足）：
  1. **输出契约冻结**：版本化 schema（如 `gapit.report/1`）承诺向后兼容；破坏性变更必须升主版本并提前公告，bacmap 侧触发 V10 重跑
  2. **金标准回归**：对 bacmap 的 12 株 gold standard（含近缘阴性对照）100% 一致或有书面归因；工具仓库自带回归 harness 并在 CI 保持绿色
  3. **确定性**：同输入同输出字节级一致；任何随机性必须显式声明并支持固定种子
  4. **显式失败**：错误以非 0 退出码或类型化错误信封报告，不静默吞错、不降级输出
  5. **发布纪律**：语义化版本 + CHANGELOG；阈值、命中规则、数据库内容的变更必须留痕并可追溯到版本
  6. **版本与数据库自描述**：输出 JSON 内嵌工具版本与所用数据库版本（ADR-18 依赖此项）
- **对 gapit 的更高要求**（v1.4，按用户要求明确）：gapit 接管全部 L1 基因筛查，是标准链中风险面最大的替换（替代经过七个版本验证的 gene_scanner + abricate），因此额外要求：
  - parity harness（abricate 冻结基线）保留为**每版必跑**的发布门槛，不随 v0.5.0 的"parity 不再是发布门"而放松——bacmap 使用的发布版必须附 parity 绿色记录
  - 命中规则（identity/coverage 阈值、overlap 处理、多命中取舍）在 SPEC.md 中逐条文档化；任何规则调整须先在 bacmap gold standard 上验证影响
  - reads 通道（minimap2）与 contigs 通道（BLAST）对同一组装的检出差异须有基准报告，供 V10 归因使用
  - 内置数据库的每次更新发布独立版本号，旧版可复得（配合 ADR-18 的 `ref_databases` 校验值登记）
- **与 MCP 的关系**（v1.4 澄清）：bacmap 内部一律以 CLI/进程内方式调用生信工具，不经工具自带的 MCP 服务绕行——这是性能与调用链简单的考虑；gapit 等工具的 MCP 能力是面向**其他智能体客户端**（Strata 聊天页、Claude、Codex 等）的独立使用渠道，与 bacmap 的 CLI 集成并行不悖。两条通道最终落到同一工具与数据库，结果一致性由工具自身保证。bacmap 自己的 MCP server 继续暴露 `bio_*` 语义工具（内部再调这些 CLI）。
- **信任层**：三者均为 L1 确定性工具；`gside species` 恒以退出码 0 结束、单法错误写入 JSON——适配器必须检查各 method 条目的错误字段，而非只看退出码。
- **验证**：V10。

---

## 4. 接口契约（冻结）

以下为签名与字段定义，实现时允许增加可选字段，不允许删改已有字段。

### 4.1 工具

```python
class TrustLayer(StrEnum):
    L1 = "L1"   # 固定管线：只调用，不改写
    L2 = "L2"   # 受控探索：沙箱 + 人审
    L3 = "L3"   # 自由对话：受门约束

class Effect(StrEnum):
    READ = "read"        # 只读查询
    COMPUTE = "compute"  # 计算但不写持久状态
    WRITE = "write"      # 写 GOM / 数据库，只能经由任务

class ToolSpec(BaseModel):
    name: str                     # 全局唯一，如 "bio_gene_scan"
    version: str
    description: str
    input_model: type[BaseModel]  # JSON Schema 由此生成
    trust_layer: TrustLayer
    effect: Effect
    long_running: bool = False    # True 时经 MCP 返回作业句柄
    output_data_class: DataClass  # D0–D4（v1.2，ADR-16）
    handler: Callable[[BaseModel, ToolContext], ToolResult]

class DataClass(IntEnum):
    D0 = 0  # 公开知识
    D1 = 1  # 去标识聚合统计
    D2 = 2  # 单株分型结果
    D3 = 3  # 序列与比对数据
    D4 = 4  # 个人与流调可识别信息

class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = {}
    error: str | None = None
    evidence: list[EvidenceRef] = []   # 指向 GOM object_id@version / file sha256
```

### 4.2 门

```python
class GateVerdict(StrEnum):
    PASS = "pass"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    REJECT = "reject"

class GateResult(BaseModel):
    gate: str                     # "analysis_claims" | "baseline_release" | "mining" | "citation"
    verdict: GateVerdict
    details: dict[str, Any]
    evaluated_at: datetime

class Gate(Protocol):
    name: str
    def evaluate(self, subject: GateSubject) -> GateResult: ...
```

每次门评估都写入一条 GOM `events` 记录（`event_type = "gate.<name>"`）。

### 4.3 任务

```python
class TaskType(StrEnum):
    ANALYZE = "analyze"
    CURATE = "curate"     # 本地流行特征库构建（v1.2，原 build_db）
    MINE = "mine"
    WRITE = "write"

class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskEngine(Protocol):
    def submit(self, task_type: TaskType, params: BaseModel, submitted_by: str) -> TaskId: ...
    def status(self, task_id: TaskId) -> TaskStatus: ...
    def cancel(self, task_id: TaskId) -> None: ...
    def approve(self, task_id: TaskId, approval: Approval) -> None: ...
```

`tasks` 表最少字段：`task_id, task_type, state, params_json, submitted_by, created_at, updated_at, workspace_path, result_object_ids`。

### 4.4 角色清单

```yaml
# roles/miner.role.yaml
name: miner                       # 与 skills/miner/SKILL.md 对应
task_types: [mine]
min_model_tier: T2
allowed_locations: [local, lan]   # 可路由的端点位置（v1.2）
max_data_class: D3                # 本角色上下文可出现的最高数据级别（v1.2）
trust_layer: L2
tools:                            # 白名单，按 ToolSpec.name
  - bio_search_samples
  - bio_query_metadata
  - bio_cgmlst
  - sandbox_run                   # 沙箱执行
fs_scope:
  read: ["${GOM_EXPORT}"]
  write: ["${TASK_WORKSPACE}"]
network: false
```

对应的 `SKILL.md` 只包含说明书，frontmatter 符合 agentskills.io：`name`、`description` 必填，版本放在 `metadata.version`。

### 4.5 模型配置

```toml
[llm.endpoints.strata]
kind = "openai_compatible"
location = "local"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"   # 共用机器时换 iq2_xs
tier = "T2"
max_concurrency = 1                     # Strata 单槽位（ADR-17）
supports_tools_with_schema = false      # 不能在同一请求中混用 tools 与 response_format
constrained_decoding = false
request_timeout_s = 300
admin_url = "http://127.0.0.1:8080"     # /load、/unload

[llm.endpoints.glm_api]
kind = "openai_compatible"
location = "cloud"
base_url = "https://open.bigmodel.cn/api/paas/v4"
model = "glm-5.x"
api_key_env = "GLM_API_KEY"             # 密钥只从环境变量读取
tier = "T2"
max_concurrency = 4
enabled = false

[llm.routing]                           # 角色/用途 → 端点
intent_classifier = "strata"
interpretation = "strata"
open_path = "strata"
writer = "strata"                       # 可改为 glm_api：仅能接收 D0–D1（或管理员允许的 D2）

[llm.data_policy]
cloud_max_data_class = "D1"             # 管理员最多可放宽到 D2；D3/D4 不可配置

[llm.resources]
co_located = true                       # 模型与管线同机时启用仲裁（ADR-17）
min_free_ram_gb_for_heavy_steps = 24
```

### 4.6 运行记录（v1.2，ADR-18）

```python
class RefDatabase(BaseModel):
    name: str                 # "card", "vfdb", "cgmlst:senterica_2", ...
    version: str
    checksum: str             # 数据库文件/目录的 SHA256

class AnalysisRun(BaseModel):
    run_id: str
    task_id: str
    strain_ids: list[str]
    workflow: str                         # "bacmap"、"snp"、"cgmlst" 等
    workflow_commit: str                  # 工作流目录 Git commit
    workflow_dirty: bool
    started_at: datetime                  # 分析开始
    finished_at: datetime | None          # 分析结束
    ingested_at: datetime | None          # 入库
    resolved_config: dict[str, Any]       # 合并全部覆盖项后的完整参数
    config_sha256: str
    ref_databases: list[RefDatabase]
    tool_versions: dict[str, str]         # 运行时实测（tool --version）
    env_lock_sha256: str                  # pixi.lock 哈希
    input_files: dict[str, str]           # 路径 → SHA256
    seeds: dict[str, int]                 # 步骤 → 随机种子
    nondeterministic_steps: list[str]
    host: dict[str, Any]                  # 主机名、CPU、线程数
    baseline_version: str | None          # 用到本地流行特征库比对时填写
    manifest_sha256: str                  # run_manifest.json 的哈希
```

LLM 解读另记 `LlmProvenance`：`endpoint`、`location`、`model`、`prompt_version`（角色清单与说明书的 Git 版本）、`sampling`、`data_class_max`。

### 4.7 辅助类型（最小定义，v1.4.3 补充——§4.1–4.3 中引用但原先未定义）

```python
TaskId = NewType("TaskId", str)

class EvidenceRef(BaseModel):
    kind: Literal["gom_object", "file"]
    object_id: str | None        # kind=gom_object：GOM 对象 ID
    version: int | None          # kind=gom_object：对象版本
    path: str | None             # kind=file：文件路径
    sha256: str | None           # kind=file：内容哈希

class ToolContext(BaseModel):
    task_id: TaskId
    role: str                    # 调用方角色（role.yaml 的 name）
    run_id: str | None           # L1 工具执行时所属的运行记录
    workspace: Path              # 任务工作区

class GateSubject(BaseModel):
    gate: str                    # 与 GateResult.gate 同域
    payload: dict[str, Any]      # 各门自定义，如 interpretation_text /
                                 # candidate_release / mining_artifact / draft

class TaskStatus(BaseModel):     # TaskEngine.status 的返回类型
    task_id: TaskId
    state: TaskState
    current_step: str | None
    message: str | None

class Approval(BaseModel):
    approver: str                # 签名人（本地账号）
    decision: Literal["approve", "reject"]
    signature: str               # 签名凭据形式，实现期细化（至少含时间戳与对象哈希）
    comment: str | None
    at: datetime
```

---

## 5. 关键流程

**确定性分析（analyze）**：提交 → 校验样本 → 生成运行记录草稿（参数、种子、数据库与工具实测版本、输入校验值）→ `WorkflowRunner` 运行 Snakemake → 补全结束时间并封存运行记录 → 入库 GOM（结果指向 `run_id`）→ deterministic verifier →（可选）与当前本地流行特征库比对（记录 `baseline_version`）→（可选）LLM 生成解读 → 分析结论门 → 报告生成 → 结束。中途崩溃时，由 DBOS 从最后完成的步骤恢复，Snakemake 依靠 `.snakemake/` 续跑。

**本地流行特征库构建（curate）**：提交（指定纳入范围，如某病原、某时间段）→ 从 GOM 选取候选菌株 → 逐株检查纳入条件（确定性校验已通过、QC 合格、元数据完整、去重）→ 剥离 D4 个人信息，生成特征表、cgMLST 本地参考谱与汇总统计 →（可选，T2）LLM 给出元数据清洗建议与特征摘要 → 特征库发布门 → `AWAITING_APPROVAL` → 人工签名 → 写入 `baseline_releases` 新版本。

**开放挖掘（mine）/ 撰写（write）**：提交 → 按角色清单启动 pydantic-ai 智能体（权限受白名单限制）→ 脚本在 Apptainer 沙箱中运行 → 产物写入任务工作区 → 挖掘结论门 / 引用门 → 用户签字 → 可进入报告。

---

## 6. 包结构

```
bacmap/
├── pixi.toml                    # 唯一环境定义（Python + 生信工具）
├── pyproject.toml               # 包名 bacmap；import-linter 规则
├── src/bacmap/
│   ├── config.py                # BACMAP_HOME + config.toml（ADR-03）
│   ├── core/                    # 领域层：engine / analysis / pathogen_registry（typing 已外移 gapit，v1.4.5）
│   │   └── verify/              # deterministic_verifier、nli_reflector
│   ├── store/                   # GOM、strain_index、metadata、lab_results、migrations/、knowledge/
│   │   ├── runs/                # 运行记录 analysis_runs（ADR-18）
│   │   └── baseline/            # 本地流行特征库 baseline_releases（ADR-19）
│   ├── tools/                   # ToolSpec 注册表；工具集合随版本演进（迁移起点为现有 29 个，ADR-20 替换后有增减）（ADR-04）
│   ├── workflow/                # WorkflowRunner + Snakemake 9 工作流文件
│   ├── tasks/                   # TaskEngine、任务类型、门、审批（ADR-06/07）
│   │   └── engine/              # 唯一导入 DBOS 的位置
│   ├── agent/                   # 智能体层
│   │   ├── llm/                 # 唯一导入 pydantic-ai 的位置（ADR-08）
│   │   ├── principles.md        # 全局原则（相当于 Hermes 的 SOUL.md）
│   │   ├── roles/               # *.role.yaml
│   │   ├── skills/              # agentskills.io 规范的 SKILL.md
│   │   ├── intent.py            # 意图 → 任务类型
│   │   └── sandbox/             # Apptainer / Podman 后端（ADR-11）
│   ├── interfaces/
│   │   ├── web/                 # FastAPI + Jinja2 + htmx
│   │   ├── cli/
│   │   └── mcp/                 # MCPServer（ADR-12）
├── sandbox/                     # SIF 镜像定义文件
└── tests/
```

---

## 7. 冻结边界一览

| 冻结（修改需走修订流程） | 可替换（接口不变即可更换实现） |
|---|---|
| Python 3.12 + pixi | Web 前端技术细节 |
| 包结构与依赖方向 | 持久化执行库（DBOS → 手写） |
| `ToolSpec` / `ToolResult` / `Gate` / `TaskEngine` 接口 | LLM 库（pydantic-ai → 其他） |
| 封闭任务类型集合 | 沙箱技术（Apptainer → Podman 等） |
| 四道门与"写操作只经由任务" | 知识库实现（FTS5 → sqlite-vec / GBrain） |
| 模型档位与部署位置规则 | 具体模型、推理服务与 API 厂商（当前默认 Strata） |
| GOM 表结构与证据链 `(strain_id, run_id)` | Hermes 适配器与其他外部客户端 |
| 运行记录字段（`AnalysisRun`） | 运行比较工具的展示方式 |
| 本地流行特征库的构成、版本与发布规则 | 特征统计的具体指标 |
| 角色三类文件的分工（权限只由角色清单决定） | 说明书与全局原则的具体内容 |
| MCP 规范版本与暴露范围（只对外） | |
| 本地模型资源仲裁与串行队列 | |
| 数据分级 D0–D4 与安全红线 | |
| 标准工具链 gside / gmlst / gapit 的职责划分（ADR-20） | 工具自身版本（跟随上游发布） |

---

## 8. 动工前验证项（每项 1–3 天）

这些是冻结设计中依赖、但尚未在本机实测的假设。任一项不通过，按"不通过时"一栏修订对应 ADR，**不允许绕过**。

| # | 验证内容 | 通过标准 | 不通过时 |
|---|---|---|---|
| V1 | Snakemake 9.x 在 pixi 环境中运行现有工作流（v1.4.7 范围修订） | 12 株 gold standard 端到端重跑；比对范围 = QC/组装/MLST/SISTR/AMR/pathotype/vpa_virulence/注释/报告；物种（→gside）与血清型（→gapit）字段两侧一致剔除计为 SKIP；其余字段与 7.32 逐字段一致 | 定位不兼容规则后修正；不回退 7.x |
| V2 | DBOS（SQLite 系统库）运行 `analyze` 任务 | 运行中 kill 进程，重启后从断点继续；审批等待超过 24 小时仍可恢复 | 改用 `transitions` + SQLite（ADR-06 兜底） |
| V3 | Strata + Qwen3.8-Flash-Next 能力实测（IQ3_XXS 与 IQ2_XS 各测一遍） | 意图拆解准确率 ≥95%（自建 100 条中文测试集，含跨任务语句）；注册表内全部工具（迁移起点 29 个）的单步调用参数正确率 ≥95%；完成 3 个挖掘样例任务；确认模型与量化版本的许可证可用于本项目 | IQ2_XS 不达标则同机部署只用 IQ3_XXS + 仲裁；整体不达标则调整角色的 `min_model_tier` |
| V4 | `mcp` 2.x MCPServer 接入 Hermes 与至少一个其他客户端（如 Claude/Codex/Strata 聊天页） | 两个客户端经 MCP 调用工具、读取说明书，长任务句柄可轮询；写操作只能经提交任务 | 修订 ADR-12 的传输方式 |
| V5 | Apptainer 在目标信创系统上运行 | 麒麟 V10（x86 与 ARM 各一台）`--containall --network none` 正常执行 Python/R 脚本 | 改用 rootless Podman |
| V6 | pydantic-ai 对接 Strata | 结构化输出（提示+校验）重试后失败率 <1%；Tool Output 模式下多步工具调用可完成；Strata 环境已安装 `jsonschema` | 评估更换 LLM 库或自写薄层（ADR-08 接口不变） |
| V7 | 模型与管线同机运行（v1.1 新增） | 64 GB 机器上 Strata 加载时运行 shovill 组装：启用仲裁后组装成功、结果与模型未加载时一致；记录 unload/load 往返耗时 | 同机部署改为 IQ2_XS，或要求模型独立主机 |
| V8 | 可复现性（v1.2 新增） | 同一样本、相同运行配置（参数、数据库、工具、种子均相同）连续运行 3 次，结果逐字段一致；仅改一个参数后，运行比较工具能把差异归因到该参数 | 定位随机来源并固定种子；无法固定的步骤登记为 `nondeterministic_steps` |
| V9 | LLM API 与数据分级（v1.2 新增） | 配置一个 `cloud` 端点：D0–D1 请求正常；含 D2 以上内容的请求被拦截并记录事件；路由到该端点且 `max_data_class` 超限的角色拒绝启动 | 修正分级检查实现，未通过前禁用 `cloud` 端点 |
| V10 | 标准工具链接入（v1.3 新增，v1.4 扩充） | gside（marker 与 panel 模式）、gmlst（typing + visual MST）、gapit（screen contigs 与 reads）在 pixi 环境可用；三者的 JSON/TSV 输出能完整解析入库（含内嵌版本号），`ref_databases` 能登记各自数据库版本与校验值；用 hermes-bacmap 的 12 株 gold standard 复核：gside 判定、gapit 基因检出与原 species_identifier/gene_scanner 结果一致或有明确归因；gapit 质量门槛核查：所用发布版附 parity 绿色记录、同输入重复运行字节级一致、reads 与 contigs 通道差异有基准报告 | 定位差异：阈值或规则版本不同则对齐参数；工具缺陷则回退对应原实现并在 ADR-20 记录 |
| V11 | 门的强制力（v1.4.1 新增；v1.4.2 改为分阶段，与迁移步骤对齐） | **第 6 步（门框架落地）**：①构造的矛盾解读文本（固定样例，不必来自 LLM）在展示/导出/入库三处均被分析结论门拦截并标记 `NEEDS_HUMAN_REVIEW`；②CLI 与内部 API 直写 GOM/已发布数据库被拒绝。**第 7 步**：③不达金标准阈值的特征库候选版本被发布门拒绝且旧版本不变。**第 8 步**：④MCP write 类直写被拒绝。**第 10 步**：⑤未签字挖掘产物无法进入报告；⑥含知识库中不存在引用的成稿被引用门拒绝导出。**第 9 步后**：用 LLM 真实生成的解读回归① | 任一子项未拦截属架构级缺陷，冻结 C5 失效——修复后方可进入下一步骤 |

---

## 9. 从 hermes-bacmap 迁移的顺序

1. **骨架**：建立第 6 节的包结构、`config.py`、import-linter 规则
2. **领域与存储**：平移 `engine`、`analysis`、`typing`、`services`，修正路径推导；跑通原有单元测试
3. **工具注册表**：`ToolSpec` + 适配器包装现有 29 个 handler；从注册表生成 Hermes 插件，修正 entry-point
4. **工作流与运行记录**：完成 V1，升级 Snakemake 9，接入 `WorkflowRunner`；实现运行记录（工具版本实测、参数快照、iqtree 等固定种子），完成 V8
5. **标准工具链**：接入 gside / gmlst / gapit（ADR-20），完成 V10；替换物种鉴定、基因筛查与 cohort MST 规则；血清型判定整体切至 gapit（依赖 gapit 仓库完成三个血清型模块的移植与验证，`core/typing` 已删除、适配器在本步实现）
6. **任务与门**：完成 V2 与 V11 子项①②，实现 `analyze` 任务、门框架与分析结论门（此时达到 C3：无 LLM 可完成全流程）
7. **本地流行特征库**：迁入 cgMLST 本地参考库与菌株元数据，实现 `curate` 任务、去标识与特征库发布门（V11 子项③）
8. **接口**：MCP server（V4、V11 子项④）、Web 任务页
9. **智能体**：完成 V3、V6、V7、V9，接入 Strata 与 LLM API、请求队列、资源仲裁与数据分级，实现意图分类与解读；用真实 LLM 解读回归 V11 子项①
10. **开放路径**：完成 V5，实现 `mine`、`write` 与对应的门（V11 子项⑤⑥）

（v1.4.8 修订：插件通道已取消——迁移全程以 `bacmap mcp --read-only` 作为持续可用的外部通道。）

---

## 10. 修订记录

| 版本 | 日期 | 变更 | 依据 |
|---|---|---|---|
| v1 | 2026-10-09 | 初版冻结 | 两轮辩论 + 调研证据 |
| v1.1 | 2026-10-09 | 新增第 0 节项目定位；ADR-05 锁定 Snakemake 9.27.*；ADR-08 按 Strata 能力修订调用规则；ADR-09 本地默认模型改为 Strata + Qwen3.8-Flash-Next，放弃 Qwen3-14B；ADR-10 拆解结果需用户确认、子代理串行；ADR-12 明确 MCP 只用于对外；ADR-15 重写 Hermes 定位；新增 ADR-17 资源仲裁；V3/V4/V6 修订，新增 V7 | 用户决策 + Strata 源码与本机实测（证据 §8） |
| v1.2 | 2026-10-09 | 第 0 节补充多角色、智能体实现、生信分析路径与特征库定义；C2、C4 修订；ADR-04 新增 `output_data_class`；ADR-06 任务类型 `build_db` 更名为 `curate`；ADR-07 建库发布门改为特征库发布门；ADR-08 明确支持本地模型与 LLM API 两类端点；ADR-09 档位与部署位置分离，取消 T3；ADR-10 明确非多智能体对话及角色三类文件分工；ADR-11 明确 L1/L2 关系与晋升路径；ADR-13 区分参考数据库与本地特征库版本；ADR-16 新增数据分级 D0–D4；新增 ADR-18 运行记录、ADR-19 本地流行特征库；新增接口 4.6；新增 V8、V9 | 用户补充 + hermes-bacmap 运行记录现状核查（证据 §9） |
| v1.3 | 2026-10-09 | 新增 ADR-20 标准外部工具链（gside 物种鉴定 / gmlst 分型与 MST / gapit 基因与基因簇鉴定）及替换关系表；鉴定档位改为 gside 数据分层，GTDB-Tk 退出标准路径；工具数据库纳入 `ref_databases` 登记与 `BACMAP_HOME` 规划；新增 V10；迁移顺序插入"标准工具链"步骤 | 用户申明 + 三工具源码/仓库核实（证据 §10） |
| v1.4 | 2026-10-09 | ADR-20：gside 标注开发中、路线图含 GTDB-Tk 档（GTDB-Tk 改为由 gside 提供，不由 bacmap 直接集成）；新增标准工具质量门槛与对 gapit 的更高要求（parity 每版必跑、规则文档化、双通道差异基准、数据库版本可复得）；澄清工具自带 MCP 与 bacmap CLI 集成并行不悖；V10 扩充质量核查 | 用户对 v1.3 五点决策的逐项裁定 |
| v1.4.1 | 2026-10-09 | 全文审核勘误：修复 ADR-13 GBrain 理由自相矛盾（改为"独立进程经 MCP 接入，不进 bacmap 运行时"）；4.2 门枚举 `db_release` 更名 `baseline_release`（v1.2 改名残留）；ADR-17 配置名统一为 `llm.resources.co_located`；ADR-10 v1.1 注记标注 `build_db` 为 `curate` 旧名；§6 与 V3 的"29 个工具"改为"注册表全部工具（迁移起点 29 个）"；ADR-02 新增 MCP 客户端模块归属规则；ADR-09 声明档位单调性；ADR-15 澄清两条通道门机制不同；ADR-07 特征库发布门检查项改为 deterministic verifier；C3 依据改为 ADR-02/06/09；新增 V11 门的强制力验证并挂到迁移第 6 步 | 全文复审 |
| v1.4.2 | 2026-10-09 | 第二轮全文复审勘误：修复 ADR-06 "两张表"与 ADR-13 "四张表"矛盾（统一为四张）；§5 curate 流程"分析结论门已通过"同步改为确定性校验（v1.4.1 遗漏）；**V11 时序矛盾**——原文要求第 6 步测试 LLM 解读与 MCP 拦截，但智能体第 9 步、MCP 第 8 步才存在，改为分阶段子项①–⑥并对齐迁移步骤；ADR-20 中 gmlst 版本内嵌声明降级为"以 V10 实测为准"；V1 与 V10 金标准株数统一为 12 株；V8 "同一运行记录"改为"相同运行配置"；ADR 顺序修正（ADR-16 原误排在 ADR-20 之后，移回 ADR-15 与 ADR-17 之间） | 第二轮全文复审 |
| v1.4.3 | 2026-10-09 | 第三轮全文复审：**修复 C2 与 ADR-16 的政策级矛盾**——C2 原写"菌株级明细（D2）不出本地网络"为绝对约束，与 ADR-16 "D2 管理员可放行"冲突，C2 改为"D3/D4 永不、D2 默认不发可放行"（**此政策选择待用户批准**，见 ADR-16）；§0 定位表与 ADR-10 "同一模型/本地模型"的过时表述更新（支持 API 端点后角色可异构）；§2 补"两类报告"注（analyze 模板报告=确定性路径，write 定制撰写=开放路径）；新增 §4.7 辅助类型最小定义（TaskId、EvidenceRef、ToolContext、GateSubject、TaskStatus、Approval——原先被 §4.1–4.3 引用但未定义，且 TaskStatus/TaskState 命名不一致） | 第三轮全文复审 |
| v1.4.4 | 2026-10-09 | D2 数据政策获用户批准：D3/D4 永不出本地网络；D2 默认不发公网端点、管理员可放行至 D2 为止（C2 与 ADR-16 一致生效）；后续调整按本文变更规则走 ADR 修订 | 用户批准 |
| v1.4.5 | 2026-10-09 | ADR-20 修订（用户裁定）：**血清型判定层也归 gapit**，推翻 v1.3"判定逻辑保留"条款；新增职责分界原则——只依赖基因组的分析一律外部工具化，需与分析结果之外数据结合的判定留在 bacmap（cgMLST 本地投影、共识合并保留）；genome_annotator 归属标记待定（gapit 具备注释能力前暂留）；bacmap `core/typing` 已删除（8 个模块 + 4 个测试文件），测试基线 839 passed / 2 skipped，ruff 与 import-linter 契约保持全绿 | 用户裁定 + 实施验证 |
| v1.4.7 | 2026-10-09 | **两条用户裁定即时生效**：①血清型三模块彻底放弃（推翻 v1.4.6 迁移脚手架式的临时恢复），gapit 承接，规则改 `pending_gapit` 占位；②**物种鉴定分析能力全部外移 gside**——species_identifier/taxonomic_validator/sourmash_identifier/ani_identifier/species_consensus 五模块与 4 个物种类工具（validate_taxonomy/species_compare/db_setup/db_status）立即删除（注册表 24 工具），species/taxonomy/vpara_targets 规则改 `pending_gside` 占位；测试基线 1004 passed / 1 skipped，ruff 与契约全绿；V1 比对范围相应修订（物种/血清型字段 SKIP）；deploy() 修复（重部署保留 .snakemake 续跑状态） | 用户两条裁定 + 实施验证 |
| v1.4.8 | 2026-10-10 | **用户裁定：取消插件通道，仅保留 MCP**——`bacmap.adapters` 包、`hermes_agent.plugins` entry-point、importlinter forbidden 层中的 adapters 条目删除；Hermes 侧 `~/.hermes/plugins/hermes_bacmap` 目录与 plugins.enabled 条目移除（该插件自 09-18 起已因语法错误加载失败）；ADR-15 接入方式修订为 MCP 唯一通道，插件钩子防线条款废止。前置事实：V4 已实测 MCP 通路（✓ Connected 2038ms / 22 工具全量发现，含写操作唯一入口 bacmap_submit_task） | 用户裁定 + 实施验证 |
| v1.4.9 | 2026-10-15 | **ADR-20 实现落地：vpara_virulence 完成 gapit 换装**——删除内联 blastn 筛查，改用 gapit 自定义库 `vpara_virulence`（tdh/trh/tlh）；库由部署期 `workflow/scripts/build_gapit_db.py` 构建于 `$BACMAP_HOME/refs/gapit/` 并登记 `refs/manifest.json`（ADR-18 `ref_databases` 可追溯）；规则输出归一化为既有 `virulence.json` 契约并新增 tool/database/hits 溯源字段。至此 ADR-20 替换表中的 direct blastn 编排类规则仅余 amrfinderplus（NCBI 专用工具）与 kraken2_prefilter（reads 级预筛），二者不在 gapit 三库职责范围内，维持现状。测试基线 1101 passed / 1 skipped | 实施验证（含真实 gapit 建库 + Snakemake 规则端到端冒烟） |
| v1.4.10 | 2026-10-15 | **清理 gside 已覆盖的专项占位规则**：删除 `species_ani`/`species_sourmash`（alternate 物种鉴定档——gside `all` 模式内部已完成多法仲裁并自动纳入 GTDB-Tk 档）、`taxonomy.smk`（`taxonomy_validation`，属 gside GTDB-Tk 能力）、`vpara_targets`（vpara 物种靶点判定，属 gside species）；Snakefile 移除 `_ALT_*`/`_STANDARD_ACTIVE` 档位门控（`.smk` 11→10）。物种与分类学鉴定收敛为单一入口 `species_identify`（`gside species`，档位由 `species_mode` 选择）。测试基线 1101 passed / 1 skipped | 用户裁定 + 实施验证 |
| v1.4.11 | 2026-10-17 | **GOM 分析入库层落地（ingest 契约修复）**：此前生产 analyze 只向 GOM 写 SAMPLE 对象（payload `{summary,run_id}`），而六处消费点（`snp_tree`/`cgmlst_traceback`/`search_samples`/`review_flags`/`nli_reflector`/`strain_index.rebuild_from_gom`）按 ANALYSIS 过滤、且读 `BACMAP_DB_PATH`（`data/bacmap.sqlite`），与写入的 `gom.sqlite` 分属两库——导致"人审回流、队列树、cgMLST 溯源、菌株检索"在生产中**静默空转**（本机实测两库均未生成，故长期未暴露）。本次统一三处：①**库路径**——GOM 对象/事件一律落 `BACMAP_GOM_DB`（`$BACMAP_HOME/gom.sqlite`），GOM 读工具（含 `nli_reflector`、报告自检）同步改用之；`BACMAP_DB_PATH` 仅承载菌株元数据/化验/特征索引表；②**对象类型**——analyze 落 ANALYSIS 对象：单样本 `sample_analysis`（扁平分型视图 `species_verdict/serotype/mlst/amr/dec/plasmid` + 完整 `summary` + `run_id`）、逐样本 `cgmlst_profile`、队列 `cohort:<group>-snp` / `cohort:<group>-cgmlst`，并同步填充 `strain_genotype_index`；③**证据链**——`AnalysisRun.workflow_commit`/`workflow_dirty` 由工作流目录 Git 采集（ADR-18 原为常量空值），ANALYSIS 校验放宽为 `pipeline_version` + （`database_versions` **或** `tool_versions`），与 C4"参考数据库与工具的实测版本"一致。测试基线 1199 passed / 1 skipped，ruff/mypy/contracts 全绿 | 用户裁定（完整档）+ 实施验证（含端到端 analyze→入库→工具读回） |
| v1.4.12 | 2026-10-17 | **外部数据访问能力（A+B+D，ADR-11 补完）**：此前助手无法使用用户给定的数据路径——没有接受路径的工具、`fs_scope` 只声明不强制、沙箱只挂任务工作区（且 `context.json` 宣称的 results/GOM 路径未真正挂载）。本次补完：①**数据登记（A）**——`store/datasets.py` 在 GOM 库新增 `datasets` 表，**零拷贝**登记用户路径（逐文件 SHA256 + 清单哈希去重、来源描述符 dev/inode/mtime、数据级别），`mine` 任务新增 `input_paths` 参数在沙箱前登记并把数据**只读 bind-mount** 到 `/input/<dataset_id>`（ADR-11"数据只读挂载"，不复制、不落副本）；②**只读工具（B）**——新增 `bio_inspect_dataset`（read/L1，注册表 25 项：8 read/14 compute/3 write）列出/查看已登记数据集与挂载点；③**沙箱访问面与边界（D）**——`SandboxSpec` 新增 `allowed_readonly_roots` 白名单，只读挂载越权即拒绝（fs_scope 代码化）；`context.json` 与实际后端一致（容器用 `/data/*`、`/input/<id>` guest 路径，直通用宿主路径），并修正 results/GOM 未挂载的缺陷。哈希用 SHA256（与 file_artifacts/ADR-18 一致）；按需物化（副本）留作可选、默认关。测试基线 1216 passed / 1 skipped，ruff/mypy/contracts 全绿 | 用户裁定（A+B+D）+ 实施验证 |
| v1.4.13 | 2026-10-17 | **受限通用 shell（方案 C 收窄形态）+ Web/TUI 十轮巡检**：①**`sandbox_shell`**（会话内部工具，不入注册表/MCP）在同一沙箱内执行**一条** shell 命令——只读/分析白名单（ls/cat/grep/zcat/samtools/seqkit/python 等）直通，其余命令拒绝并引导改用需签字的 `mine` 任务，禁用清单（podman/docker/nsenter/mount/curl/…）硬拒；**仅在真实容器后端运行**（直通模式默认拒绝，`BACMAP_SANDBOX_ALLOW_SHELL_PASSTHROUGH=1` 仅开发）；每次调用写审计 `$BACMAP_HOME/audits/sandbox_shell.jsonl`。②**Web 巡检**：新增安全响应头中间件（严格 CSP + nosniff + frame-deny + referrer-policy + COOP，鉴权 401 亦覆盖）；内联轮询脚本外置为 `/static/js/task_poll.js`、内联 style 改工具类以配合严格 CSP；HTML 报告改为**附件下载**（消除同源内联渲染 XSS 面）；助手会话 **LRU 上限 32** 防无界增长；助手输入限长（空→400、超长→413）。③**TUI 巡检**：修复**连按 Ctrl+Y 重复提交同一计划**（确认即清 pending）、`_start_chat` 误用线程 worker、线程 worker 内直接调 `refresh_tasks`（改 `call_from_thread`）、leader 模式残键落回输入框、新会话未取消在途请求；提示词限长。测试基线 1235 passed / 1 skipped，ruff/mypy/contracts/docs-build 全绿 | 用户裁定（落地 C + web/tui 十轮巡检）+ 实施验证 |
| v1.4.14 | 2026-10-18 | **逐模块巡检（config/utils/analysis/engine/agent/tasks/cli/mcp）与行为收紧**：①**config**——`DATA_DIR` 解析改为 env > `config.toml[paths].data_dir`（展开 `~` 并 resolve）> `$BACMAP_HOME/data`（此前 toml 会静默覆盖 env 且未规范化）；`CHECKM2_DB` 环境变量名与文档对齐（原代码误读 `CHECKM2DB`，保留旧名兼容）。②**tasks/gates**——四道门对畸形输入改为 **fail-closed（REJECT）**，不再在门内抛异常（保 C5 强制力）；`DbosTaskEngine.cancel()` 仅允许非终态任务（原实现会把已完成/已失败任务改写成 CANCELLED）；**`analyze` 提交必须含样本**（原会落成静默 FAILED 任务），Web/MCP/CLI 三端同步返回清晰错误。③**CLI**——不可信样本值统一经 `rich.markup.escape`（防 Rich 标记改版式）；`bacmap --help` 显式区分"界面/模式（mcp/web/tui/console）"与"命令（overview/task/sample/search/ask/chat）"，命令**保持顶层**、不新增 `cli` 子命令（`bacmap` 本身即 CLI，零 BC 破坏）。④**engine**——`get_backend` 大小写归一化（`BLASTP` 原会退化为 `blastn`）。⑤**agent**——`RoleDef` 枚举字段校验（坏清单加载即报错）+ 全部角色工具白名单一致性测试。⑥**mcp**——`submit_task` 对引擎校验错误返回错误信封。测试基线 1260 passed / 1 skipped，ruff/mypy/contracts/docs-build 全绿 | 逐模块代码质量巡检（用户指定）+ 实施验证 |
| v1.4.15 | 2026-10-18 | **Web 浏览器端鉴权：token → cookie + CSRF（ADR-14 补完）**：默认 `BACMAP_WEB_AUTH=bearer` **保持向后兼容**（仅 `Authorization: Bearer`，供 API 客户端）；新增 `cookie` 模式——`/login` 输入部署令牌（常量时间比较 + Origin 校验）→ 签发 `sid.exp.HMAC-SHA256` **无状态会话 cookie**（`HttpOnly; SameSite=Strict; Path=/`；登录即换新 sid **防会话固定**；`BACMAP_WEB_COOKIE_SECURE=1` 加 `Secure`），另设非 HttpOnly 的 `bacmap_csrf` cookie；**状态变更 POST 三重 CSRF 防护**：SameSite=Strict + Origin/Referer 同源校验 + `csrf` 表单字段与 cookie **双提交一致**；未鉴权 HTML 请求 303 跳 `/login`、XHR 401；`/logout` 清 cookie；`next` 仅限站内（防开放重定向）。签名密钥取 `BACMAP_WEB_SECRET`（缺省由 token 派生）。测试基线 1275 passed / 1 skipped，ruff/mypy/contracts/docs-build 全绿 | 用户裁定（web token→cookie+CSRF 立项后实施）+ 实施验证 |
| v1.4.16 | 2026-10-18 | **病原注册表重建（码为准）+ 三字母物种码**：`pathogens.yaml` 由"仅 4 种肠道病原、名称键、含 marker 基因"重建为**覆盖 gside `D1_marker` 全部 40 条物种标签**的注册表，键改为**三字母物种码**（新 `core/species_codes.py`：规则"属首字母+种前 2 字母"，覆盖 SAL/SHI/ECO/EFM/CDP；VCH 有意合并 cholerae/O1/O139；`UNK` 哨兵；冲突检测）。**marker 基因删除**（鉴定归 gside，ADR-20）；新增 `gside_labels`/`gapit_screens`/`serotype_engine`/`plan{snp,cgmlst,recombination}` 字段。**SNP/cgMLST 分组改为通用机制**：组成员由 `snp_group` 声明**派生**，不再在 yaml 里手列 species。消费者（`snp.smk`/`cgmlst.smk`/`typing_amr.smk`）改经 `resolve_species()` **双接受**（码 / gside 标签 / 显示名）取键；`samples.tsv.species` 双接受。参考基因组将随 Stage C 从 NCBI 供给（accession 清单/智能体 skill）；种以下判定（DEC 致病型等）走 **gapit** 库（`ecoli_dec`/`ecoh`/`lm_doumith`/`kpsc`/`ab_k` 等）；重组检测用 **Gubbins**（外部工具，Stage C）。测试基线 1287 passed，ruff/mypy/contracts/docs-build 全绿 | 用户裁定（registry 重建 + 码为准 + 双接受）+ 实施验证 |
| v1.4.17 | 2026-10-18 | **Stage C：鉴定升级 + 参考供给 + 重组检测（含编排修复）**：①**升级阶梯**——`gside_species.py` 支持 `--escalation`：未定种时按 `marker→panel→mash_refseq→sourmash→all` 升档直至可识别，每档结果记入 `attempts`；库未就绪的档自动落空（不崩溃），全档失败仍 `Unknown` 并带诊断（配置 `species_escalation`/`species_mode_max`，默认关）。②**参考基因组供给（NCBI）**——新增 `workflow/config/reference_accessions.yaml`（`group→out+accessions`，多复制子拼接）与 `scripts/fetch_reference_genomes.py`（efetch 取回 → `data/reference/genomes/` → 登记 `refs/manifest.json` 供 ADR-18 溯源；离线失败不中断，`--strict` 非零退出）。③**重组检测（Gubbins）**——新增 `scripts/run_recombination.py`（仅编排+格式适配）与 `rules/recombination.smk`；`plan.recombination` 为唯一开关，**工具缺失写 `status=skipped`（不静默）**；Gubbins 置于**独立 `recomb` pixi 环境**（其 `iqtree 2.0.3.*` 与管线 `3.1.2.*` 冲突，故 `no-default-feature` 独立求解）。④**编排修复**——`run_analysis.py` 删除硬编码分组表（改由 registry 派生 + `resolve_species` 双接受，修正码/名称混用的失配）；`--snp` 目标由错误的单文件路径改为**按组**（并附重组目标），修正 ≥2 样本计数（曾按去重码计数）。真实 Gubbins 冒烟通过（3.4.3，产出 GFF+树）。测试基线 1313 passed，ruff/mypy(88)/contracts/docs-build 全绿 | 用户裁定（继续 Stage C）+ 实施验证 |
