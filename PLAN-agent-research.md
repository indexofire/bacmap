# Agent ↔ Research 桥接开发方案（分支 `feat/agent-research-bridge`）

> 状态：工作分支方案 + 第一批实现。合并前必须通过全部质量门，并在真实 harness 上完成
> MCP prompts/resources、计划确认和图片产出的端到端验证。

## 1. 结论

Agent 由用户自选（Hermes / Pi / DSH / OpenCode / 任意 MCP 客户端），bacmap 不绑定任何
一个。能力按三层拆分：

| 层 | 归属 | 内容 | 是否随 agent 变化 |
|---|---|---|---|
| **L1 内容源** | bacmap 代码 | 全局原则、角色说明书、研究/文献工作流、MCP prompts、`skill://` resources、server instructions | 否 |
| **L2 适配层** | bacmap 生成、用户安装 | 各 harness 的 instructions/skills/MCP 配置片段、安装清单、漂移检查 | 是 |
| **L3 强制层** | bacmap 服务端 | MCP profile、计划确认、门禁、数据分级、写操作唯一入口、OS 隔离 | 否，且不可下放 |

一句话：**内容源在 bacmap，安装器只做薄适配，安全与证据强制永远在服务端。**

## 2. 为什么不是“安装时把提示词复制进 agent”

- 用户可能同时使用多个 harness，且会升级、换机、在容器/远程运行；
- 复制出去的提示词会与 bacmap 版本漂移；
- skills/extensions/hooks 可被禁用或绕过，不能作为安全边界；
- MCP prompts/resources 是协议级、agent 无关的分发方式，应作为默认通道；
- 安装器只解决“某些 harness 不会自动注入 prompts/resources”的体验问题。

## 3. 角色说明书与权限的拆分

现有 `role.yaml` 的 `tools` / `max_data_class` / `network` 是给 **bacmap 内部任务型 agent**
的，由代码强制。外部 harness agent 不受它约束，实际权限由 **MCP profile** 决定。

因此：

- `build_system_prompt(role)` 保持 internal 语义（内部任务型 agent）；
- 新增 `build_system_prompt(role, audience="external")`，把“权限边界”改为
  “本说明书只是方法论；你的实际权限由 MCP profile 决定；不能确认计划、不能直接写库”；
- MCP `bacmap_role_<role>` prompt 使用 external 版本；
- `skill://bacmap/<role>/SKILL.md` 保持纯方法论，不含权限声明。

## 4. 文献工作流

| 部分 | 归属 |
|---|---|
| 检索策略、读论文、综合、写作 | Agent |
| 联网检索 / PDF 获取 | Agent 自己的工具（查询词只能用公开信息） |
| 知识条目导入、审核、引用门、证据绑定 | bacmap（record task + citation gate） |

bacmap 不新增联网抓取；文献检索留在 agent，落库和引用判定留在 bacmap。

## 5. 发表级图片：不是“paper skill + AI 写脚本”单一方案

分三档，按“是否影响证据”划分：

| 档 | 谁生成 | 适用 | 可复现性 |
|---|---|---|---|
| **A. 确定性标准图** | bacmap | 2×2 条形图、森林图、流程图、标准统计图 | 最高：`FigureSpec` + 固定 renderer + hash |
| **B. 自定义发表图** | Agent 写脚本，bacmap 沙箱执行 | 期刊定制、组合面板、特殊标注 | 高：脚本/数据/环境/输出全部 hash + 人工签字 |
| **C. Paper skill** | Agent 使用 bacmap 提供的写作/制图规范 | 选图、配色、字号、图注、期刊格式 | 仅指导，不产生证据 |

关键约束：

- **数字只能来自 bacmap** 的 `FigureSpec`（data + stat + source IDs），agent 不得自行改数；
- B 档脚本走现有 `mine` 开放路径：无网络、只读挂载、挖掘门 + 人工签字；
- 输出必须登记 `spec_sha256`、`data_sha256`、`code_sha256`、`output_sha256`、renderer、
  环境信息；没有 provenance 的图片不能进入发表包；
- A 档优先：能用标准图表达的结果，不允许用 AI 脚本重画。

## 6. 分阶段任务

### P0 设计冻结（本分支）

- [x] 三层模型、角色/权限拆分、文献边界、图片三档
- [x] 开发方案文档

### P1 Agent 桥接（本分支）

- [x] `bacmap agent list|export|install|doctor`
- [x] harness 能力矩阵（Hermes / Pi / DSH / Codex / OpenCode / generic）
- [x] 外部角色说明书（`audience="external"`）
- [x] 安装清单 `.bacmap-agent.json` + 内容 hash + 漂移检查
- [x] MCP server instructions 增补 prompts/resources 指引
- [x] Pi 1.5.0 端到端验证（MCP 连接、只读 research/phylo/logistic、计划创建 + 人工确认、
  sandbox 缺失时的失败路径、内联 skill）
- [x] Hermes 端到端验证（0.23.0，无头 `-z` + 真实数据：MCP 连接、只读 research 工具、
      analyze 计划→人工确认→8 株副溶血弧菌 `succeeded`、mine 沙箱→挖掘门→人工签字、
      `.hermes.md` 指导注入；2026-11 记录见 docs/guide/agent-plans.md §9）
- [x] DSH 端到端验证（0.2.2-rc.1：cordis.patch 插件合成 + MCP 服务器拉起 + 浏览器
      对话层实测——用户会话中模型成功调用 `bacmap_capabilities`，会话记录证实全部
      29 个 bacmap 工具（含 `bacmap_research_figure_recipes`）注入模型上下文）
- [x] `bacmap agent install --with-skills` 在各 harness 的 skills 目录约定
      （2026-11 实测：Hermes `~/.hermes/skills/`（真机安装后 `hermes skills list`
      枚举到全部角色）；Pi `~/.pi/agent/skills/`；OpenCode/通用跨 agent
      `~/.agents/skills/`；DSH 无文件系统 skills 机制 → 保持 `.bacmap/skills`
      便携副本 + MCP resources/inline-roles；Codex 未实测同回退）

### P2 发表图契约（本分支）

- [x] `FigureSpec`（数据、统计量、来源、样式、期刊约束）
- [x] 会话创建时生成 `figure_spec.json` 并登记 artifact
- [x] `bacmap research figure spec|attach`
- [x] `bacmap_research_figure_spec` 只读 MCP 工具
- [x] 版本化 recipe 注册表（`association_bar` stable；`forest`/`strobe_flow`
      experimental builtin SVG（`figure render` 确定性渲染）；`heatmap`/`pca`/
      `volcano`/`tree_rectangular` 为 planned，待 CI 发布固定镜像）
- [x] B 档脚本模板（`bacmap research figure template`；mine 沙箱用法与示例见
      `docs/guide/research-workbench` §10）
- [x] mine 任务在真实沙箱镜像上的实测（2026-11：本地 `podman --cgroup-manager=cgroupfs
      build -t bacmap-figures:py312 docker/figures/py312` → mine 计划（driver 自动发现
      挂载的 figure_spec）→ matplotlib 渲染 `figure_custom.pdf` → 挖掘门签字 →
      `figure attach` 登记完整 provenance；CI registry 发布仍为多工作站可选项）
- [x] PDF/PNG 校验（v1.4.42：`attach` 质量门——PDF 字体嵌入/页数、PNG pHYs dpi/
      色彩类型/CRC、SVG 良构+拒 DTD；纯标准库，matplotlib Type3 现实已回归）

### P3 系统发育参数规划与 BEAST XML（后续）

目标：AI 参与**参数规划**，但执行仍是确定性工作流；BEAST XML 由 bacmap 从类型化
`PhyloPlan` 渲染，不由 AI 直接写自由文本 XML。

- [x] `PhyloProfile`：比对长度、taxa、缺失率、可变/信息位点、分区候选、日期范围、
      重组信号、ModelFinder 结果
- [x] `PhyloPlan`：AI 提议模型/速率异质性/时钟/树先验/MCMC 长度/burn-in/分区/外群；
      bacmap 校验边界（如 BEAST2 链长下限、日期与时钟模型一致性）
- [x] IQ-TREE 计划：`-m MFP`、bootstrap、分区合并、ascertainment bias、seed
- [x] BEAST2 XML renderer：`PhyloPlan` + alignment → XML；`beast -validate` 门；
      记录 plan hash、XML hash、BEAST 版本
- [x] 自定义 XML 走 `mine` 开放路径（策略已写入；使用既有 mine）（脚本/配置 hash + 人工签字），不直接进主流程
- [x] `bacmap research phylo profile|plan|xml` CLI 与只读 MCP 工具（D3，仅 local-trusted）
- [x] BEAUti 替代路径：AI 辅助参数、bacmap 渲染/校验 XML、人确认后运行

### P4 论文级统计与报告（第一切片已落地；高级方法需新依赖/ADR）

- [x] 多变量 logistic 回归（IRLS，第一切片）
- [ ] 混合效应 / IPTW / 匹配 / 生存分析（后续）
- [x] 缺失值摘要（回归丢弃计数 + profile 缺失率）
- [x] 样本量/把握度（`stats power`：两比例正态近似，baseline+OR 推导、session 观察
      比例作设计假设并明示非事后功效；MCP `bacmap_research_power` D2）
- [x] 外部验证（`stats validate`：推导 vs 验证队列 2×2 的 Woolf 齐性检验 Q/χ²，
      固定合并 OR；一致≠复现成功已写入文档）
- [x] STROBE checklist、supplementary 清单、投稿包
- [ ] 研究 plan 类型（是否新增 `research` 计划类型需另立 ADR）

### P5 图片运行时与风格（已落地；镜像发布属 CI）

- [x] recipe 声明 runtime（builtin/container/pixi/host）
- [x] `bacmap research figure runtimes` 检查后端
- [x] style brief 字段（journal/panel_layout/palette_colors/reference_note）
- [x] 图片运行时构建资产（`docker/figures/py312`、`r4`；发布需 CI registry）
- [x] 示例图 → style brief 字段与 `figure draft` 草稿迭代记录（agent 对话在外部）

## 7. 验收标准

- `pixi run -e dev test`、`lint`、`typecheck`、`contracts`、`docs-build` 全绿；
- `bacmap agent install` 幂等，重复执行不产生重复内容，用户文件不被覆盖；
- `bacmap agent doctor` 能发现内容漂移和缺失文件；
- 外部 prompt 不把 `role.yaml` 权限说成强制；
- `FigureSpec` 含完整来源 ID 和统计量，`attach` 拒绝缺失/不匹配的 provenance；
- 文档双语同步（`docs/guide/agent-plans.md`、`docs/reference/cli.md`、
  `docs/guide/research-workbench.md`）。

## 8. 明确不做

- 不在 bacmap 内重新引入对话式助手（ADR-21）；
- 不让 hook/extension 承担安全强制；
- 不在 bacmap 内实现联网文献抓取；
- 不用 AI 脚本替代可确定性生成的标准图；
- 不为单一 harness 写业务逻辑。
