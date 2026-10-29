[English](tutorial.md) | **简体中文**

# 不用记命令：让智能体帮你做病原基因组分析

> bacmap 要解决的不是"再造一个生信命令行"，而是两件普通用户最头疼的事：
> **不会敲生信命令**，以及**数据和结果散落各处、说不清来龙去脉**。
> 这篇教程从头到尾用自然语言完成工作；命令行只在最后一节出现，而且是可以不看的。

## 1. 它是怎么分工的

```
你（自然语言） → 智能体（Hermes / Pi / DSH） → MCP → bacmap
                                          ├─ 生成"计划"（要做什么，参数是什么）
                                          ├─ 你确认（人或可信界面）
                                          ├─ 确定性执行（Snakemake / 外部工具）
                                          └─ 门禁 + 证据（运行记录、GOM、签名）
```

- **你**：说清"要什么"、确认计划、给结论签字。
- **智能体**：理解需求、查数据、提计划、写脚本/草稿、解释结果。
- **bacmap**：只做三件事——把计划变成可复现的执行、把结果变成有证据的事实、把危险动作挡在门外。

所以你不需要记住 `snakemake`、`shovill`、`gside` 的参数；你只需要会说清楚问题和数据在哪。

## 2. 一次性准备（十分钟）

```bash
pixi install && pixi shell     # 安装 bacmap 本体（唯一需要命令的一步）
bacmap doctor                  # 体检：目录、库、沙箱、模型、磁盘
```

然后接一个你喜欢的智能体（三选一，配置见[智能体 Harness 指南](harnesses.zh-CN.md)）：

- **Hermes**：适合手机 IM 里查结果、收通知；
- **Pi**：终端里最顺手的编码/分析助手；
- **DeepSeek Harness**：Web 界面友好。

接好后，在智能体里问一句"你能看到 bacmap 的哪些工具？"——它应该能列出计划、任务、结果等工具。
如果用云端模型，默认只给它 D0–D1 的工具；本地/内网模型可以开 `local-trusted`（见 §9）。

## 3. 完整实操：从启动 Hermes 到拿到报告

下面这条路径可以照抄。假设：bacmap 装在 `/home/you/bacmap`，数据在 `/data/run42`。

### 3.1 让 Hermes 找到 bacmap（只需一次）

编辑 `~/.hermes/config.yaml`：

```yaml
mcp_servers:
  bacmap:
    command: /home/you/bacmap/.pixi/envs/default/bin/bacmap
    args: ["mcp"]                 # 本地/内网模型可加 "--profile", "local-trusted"
```

验证：

```bash
hermes mcp test bacmap
```

```
✓ Connected (1939ms)
✓ Tools discovered: 10
  bio_list_reference_genomes, bio_diagnose,
  bacmap_capabilities, bacmap_create_plan, bacmap_revise_plan, bacmap_get_plan,
  bacmap_submit_task, bacmap_task_status, bacmap_task_cancel, bacmap_task_result
```

**注意两件事**：

1. Hermes 自己也要配模型（`hermes` 里用 `/model` 或 `/login`）。它和 bacmap 的
   `config.toml` 里那个 LLM 端点是**两套配置**：前者负责对话，后者只给任务内解读用。
2. 默认 `cloud` Profile 只能看到 10 个工具；看不到 `bio_get_result` 等属于正常（数据分级）。

### 3.2 启动并说出需求

```bash
hermes
```

进入交互界面后，第一句可以这样说（**把路径写成绝对路径**）：

> 帮我分析 /data/run42 下的 8 株副溶血弧菌 reads，跑标准流程。

Hermes 会先调用 `bacmap_capabilities` 看能力，再尝试建计划。如果路径不存在，它会收到明确的
`validation_error`（例如 `directory not found: /data/run42`），并把这句话转述给你——这时检查路径即可。

### 3.3 它给出的计划长这样

工具调用（在 Hermes 界面里通常以 `mcp__bacmap__bacmap_create_plan` 形式出现），返回：

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "tasks": [{"task_type": "analyze", "fastq_dir": "/data/run42", "species": null}],
  "plan_hash": "c1d2e3f4a5b6...（64 位）",
  "next_step": "Ask the user to review and confirm this exact version in bacmap itself: `bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6` (or the Web console). You cannot confirm it; poll bacmap_get_plan for task_ids after confirmation."
}
```

Hermes 通常会转述成："计划已创建，需要你在 bacmap 中确认。"——**它确认不了**，这是设计。

### 3.4 你来确认（不用离开对话）

计划的返回里带一个 `confirm_url`，点开就是 Web 的计划页（已登录），看完整参数后点“确认并提交”：

```
http://127.0.0.1:8800/plans/9a3f2c1b7d4e4f60?version=1
```

三种确认方式，按方便程度选：

1. **Web 链接**（默认）：点开 → 确认 → 回到 Hermes 继续；
2. **本地弹窗**（工作站有图形界面时）：对 Hermes 说“在本机弹窗确认”，它调用
   `bacmap_confirm_plan_locally`，系统对话框里点“确认”；只有 stdio 会话可用；
3. **预授权**（管理员可选）：`config.toml` 里开启 `[plans.auto_confirm]` 后，
   仅含 analyze、**引用已登记样本**且样本数不超限的计划自动确认
   （`actor=policy:auto-confirm`）；目录直入、脚本、mine/write/发布仍需人工。

计划按客户端隔离：换一个 Harness 后，它不能读取或修订另一个客户端创建的计划。
请用同一个客户端确认/完成，或重新创建一个计划。

本地弹窗的对话可以这样说：

> **你**：在本机弹窗让我确认这个计划。
>
> **智能体**：（调用 `bacmap_confirm_plan_locally`）已弹出确认框，显示计划 v1 与哈希 c1d2e3f4a5b6。

弹窗里点“确认并提交”后，它会返回 `state=submitted` 与 task_ids；点取消则计划保持待确认，
并给你 Web 链接兜底。注意：这个工具只在 Hermes 以本地进程（stdio）接入时可用。

终端命令仍可用（兜底）：

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
```

### 3.5 回到 Hermes 追问进度

> 确认好了，帮我盯着进度，跑完告诉我结果。

它会调用 `bacmap_get_plan` 拿到 `task_ids`，再用 `bacmap_task_status` 轮询，典型回复：

> 8 个样本已完成 5 个，3 个在组装阶段，暂无失败。

跑完后：

> 把结果汇总给我，重点说血清型和耐药。

Hermes 会调用 `bacmap_task_result`（云端 Profile 只返回门结论计数；本地 Profile 才返回逐样本结论），
并提示你到 Web 的样本页或运行 `bacmap sample show HZCPE-01` 看详细报告。

### 3.6 如果它说"看不到某些工具"

说明当前是 `cloud` Profile。两种情况：

- Hermes 用云端模型：这是红线，只能让它做规划与解释；要看单株结果，请管理员把
  `cloud_max_data_class` 放宽到 `"D2"`（最多）。
- Hermes 用本地/内网模型：在 `config.toml` 设 `[mcp] allow_local_trusted = true`，并把
  `args` 改成 `["mcp", "--profile", "local-trusted"]`，重启 Hermes。

## 4. 追问：让它替你读结果、做比较

自然语言就可以，不需要知道背后是哪个工具：

| 你可以这样问 | 它会做什么 |
|---|---|
| "这批里有没有碳青霉烯酶？" | 检索已入库结果里的耐药基因 |
| "HZCPE-03 和去年 O3:K6 那批像不像？" | cgMLST 等位基因距离 + 判定阈值（无阈值时如实说"未判定"） |
| "这两次分析结果为什么不一样？" | 对比运行记录：参数/数据库/工具/输入哪个变了 |
| "把这 8 株的 ST 和血清型列个表" | 读取结果并汇总（必要时提议一个统计脚本） |
| "哪些样本需要我人工看一眼？" | 查审计标记（门/自检）并列出原因 |

它回答时会带上**证据**：哪个样本、哪次运行（`run_id`）、用的哪个库版本。你可以继续追问"依据呢？"。

## 5. 数据管理：把"人脑里的信息"交给它

这是第二个痛点。菌株从哪来、药敏结果、有没有文献支持，都可以直接说：

> **你**：HZCPE-01 是 10 月 12 日从深圳海鲜市场采的，来源是食品。
>
> **智能体**：（调用 `bacmap_record_data`，提交一个 `record` 任务）已记录。要顺便补药敏吗？

> **你**：补一条，美罗培南 MIC 0.25 mg/L，判读 S。
>
> **智能体**：已记录（lab_result）。

> **你**：这篇 O3:K6 的文献也收进去：PMID 12345678。
>
> **智能体**：已入暂存区，编号 12；需要审核后才会被引用门认可。要现在审核吗？

这些写入都走任务层：有任务、有事件、可追溯，不是"智能体直接改数据库"。

信息齐了以后：

> **你**：把本地副溶血弧菌汇总成一版特征库，看看能不能发布。
>
> **智能体**：（`curate` 计划）12 株纳入、1 株因元数据不全被排除；发布需要你签名。

**同一株测了多次也不会重复计数**：bacmap 按 isolate 归并，每个 isolate 只取一次代表运行，
并在候选清单里记录选了哪次、为什么。

## 6. 深度分析：让它写脚本，你审代码

标准流程覆盖不了的问题，让它写一段沙箱脚本：

> **你**：按 ST 统计本地副溶血弧菌，画一张分布图，顺便看看 2025 年之后有没有新克隆群。

智能体提交一个 `mine` 计划，里面带**脚本全文**。你不需要会写 Python，但要做一件事：**看一眼脚本在干什么**（读哪些文件、输出什么）。确认后它在无网络沙箱里执行，产物过"挖掘门"，再由你签字。

不满意可以继续对话：

> **你**：图看不清，按年份分面，另外把样本数少于 3 的 ST 合并成 other。
>
> **智能体**：（修订计划，脚本 diff 可见）确认后重跑。

## 7. 写报告：让它起草，门禁把关

> **你**：用刚才的结果和文献，起草一份给科长的周报，重点讲暴发簇和耐药。
>
> **智能体**：（`write` 计划）草稿已生成，引用都来自已审核文献；引用门检查通过，等你签字。

未审核的文献、知识库里没有的引用，会在引用门被挡下——这是为了防止"看起来很像"的编造。

## 出问题时，先跟它说（自然语言排障）

不用先翻日志。把现象说出来，智能体会调用任务状态/诊断工具，给你原因和下一步：

> **你**：刚才那个分析任务失败了，帮我看看怎么回事。
>
> **智能体**：（`bacmap_task_status`）任务 `3f9c…` 失败，类别 `sandbox_unavailable`；
> 建议安装沙箱后端（Apptainer 或 Podman），直通模式只用于开发。

云端 Profile 下它拿不到任务消息原文（可能含样本 ID/路径），但会收到**脱敏的故障类别与处置建议**；
本地 `local-trusted` 下还能看到完整消息、调用 `bio_diagnose` 解析 Snakemake 日志。

常见问题的对话式处置：

| 现象 | 你可以说 | 它通常会答/做 |
|---|---|---|
| 任务 failed | "帮我看看失败原因" | 给出故障类别与修复命令；不会替你执行安装 |
| 沙箱缺失 | "沙箱装哪个？" | 建议 `pixi global install podman`；解释直通风险 |
| 路径不存在 | "它说找不到目录" | 指出 `validation_error: directory not found`，让你确认绝对路径后重提计划 |
| 同名数据冲突 | "为什么它不让我加这个文件？" | 解释 dataset id 冲突，建议改名 `<isolate>__<platform>__<date>` |
| 确认时报冲突 | "确认说输入变了" | 说明建计划后目录内容变了；提议修订计划（`bacmap_revise_plan`）后重新确认 |
| 数据被拦截 | "为什么它看不到这株的序列？" | 解释 D3/D4 红线；建议本地 Profile 或放宽到 D2（管理员） |
| 任务一直 running | "是不是卡住了？" | 查状态与对账结果；必要时建议取消并说明影响 |
| 要看详细日志 | "把完整报错给我" | 云端会说明受限；本地 Profile 或 `bacmap doctor` 可看 |

**边界**：智能体可以诊断、提议、改计划，但不会直接改数据库、不会绕过门禁、不会替你签字。
它给的是"下一步怎么做"，执行与确认仍在你手里。

## 8. 你始终掌握的三个动作

1. **确认计划**：看到完整参数（包括脚本/草稿全文）才确认；
2. **签字发布**：特征库、挖掘产物、报告导出；
3. **查证据**：任何结论都能追到运行记录与 GOM 版本。

## 9. 为什么它有时"看不到"一些工具

这是数据红线，不是能力问题：

| 你的模型在哪 | 默认能看到 | 想看得更多 |
|---|---|---|
| 云端 API | D0–D1 工具（计划/任务/公开信息） | 管理员把 `cloud_max_data_class` 放宽到 `D2`（最多） |
| 本地 / 内网 | `local-trusted`：单株结果、序列、元数据 | 在 `config.toml` 开 `[mcp] allow_local_trusted = true` |

序列（D3）与个人信息（D4）永远不会发给云端模型；这也是为什么"分析在本地跑、模型只负责理解和解释"。

## 10. 什么时候仍然会用命令行 / 网页

- **部署、体检、备份、升级**：`bacmap doctor`、`backup`、`restore`（见[运维指南](operations.zh-CN.md)）；
- **没有智能体时**：Web 控制台可以完成提交、确认、审批、看报告；
- **自动化/批处理**：CLI 与 `/api/v1` 更合适（见[使用指南](usage.zh-CN.md)）。

它们不是"高级用户专属"，只是**智能体不可用时的兜底**。

## 11. 可以这样跟它说（照抄即可）

- "看看本地有哪些沙门菌，最近三个月新增了哪些？"
- "把 /data/batch7 里所有组装好的基因组跑一遍标准分析。"
- "HZCPE-02 的血清型和耐药基因是什么？和 HZCPE-01 比呢？"
- "这批里有没有同一克隆簇？给我距离和判断依据。"
- "把 2025 年以来的菌株按 ST 和来源做个交叉表。"
- "这株的元数据补一下：2026-10-12，深圳，食品，海鲜。"
- "帮我起草这周的监测简报，引用只用已审核文献。"
- "上次那个分析用的 CARD 是哪个版本？"
- "在本机弹窗确认这个计划。"
- "哪些任务在等我审批？"
- "把结果和原始数据备份到 /backup。"

## 12. 一页记住

> **你说需求 → 它提计划 → 你确认 → bacmap 执行并留证 → 你签字发布。**
>
> 记不住命令没关系；记住这三件事：**数据在哪、要什么、谁来签字**。

延伸阅读：[使用指南](usage.zh-CN.md) · [智能体 Harness](harnesses.zh-CN.md) · [运维指南](operations.zh-CN.md) · [工具参考](tools.zh-CN.md)
