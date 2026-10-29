# 不用记命令：用智能体做病原菌基因组分析

> bacmap 存在的意义是消除两个日常痛点：**没人愿意记生信命令行**，以及
> **数据和结果最终散落各处、没有可追溯的历史**。本教程从头到尾用自然语言完成工作。
> 命令行只在最后一节出现——而且你可以跳过它。

## 1. 谁做什么

```
你（自然语言） → 智能体（Hermes / Pi / DSH） → MCP → bacmap
                                                     ├─ 提出"计划"
                                                     ├─ 你确认（人，受信界面）
                                                     ├─ 确定性执行（Snakemake/工具）
                                                     └─ 门 + 证据（运行记录、GOM、签名）
```

- **你**：说出需求、确认计划、为结论签字。
- **智能体**：理解、查看数据、提出计划、编写脚本/草稿、解释结果。
- **bacmap**：把计划变成可复现的执行，把输出变成有证据的事实，并把危险操作挡在门之后。

你永远不需要 `snakemake`、`shovill` 或 `gside` 的参数；你需要的是描述问题并指出数据在哪里。

## 2. 一次性准备（十分钟）

```bash
pixi install && pixi shell     # 安装 bacmap 本体（唯一必须输入的命令）
bacmap doctor                  # 体检：home、数据库、沙箱、模型、磁盘
```

然后接入一个智能体（任选其一；配置见 [Harness 指南](../guide/agent-plans.zh.md)）：

- **Hermes**——从手机 IM 里查结果和收通知；
- **Pi**——最顺手的终端助手；
- **DeepSeek Harness**——友好的 Web UI。

问它"你能看到哪些 bacmap 工具？"——它应当列出计划、任务和结果工具。使用云端模型时，
它一开始只有 D0–D1 工具；本地/局域网模型可以使用 `local-trusted`（§9）。

## 3. 完整走查：从启动 Hermes 到拿到报告

这条路径可以直接复制粘贴。假设 bacmap 位于 `/home/you/bacmap`，数据位于 `/data/run42`。

### 3.1 让 Hermes 指向 bacmap（一次即可）

编辑 `~/.hermes/config.yaml`：

```yaml
mcp_servers:
  bacmap:
    command: /home/you/bacmap/.pixi/envs/default/bin/bacmap
    args: ["mcp"]                 # 本地模型请加 "--profile", "local-trusted"
```

验证：

```bash
hermes mcp test bacmap
```

```
✓ Connected (1939ms)
✓ Tools discovered (cloud profile)
  bio_list_reference_genomes, bio_diagnose,
  bacmap_capabilities, bacmap_create_plan, bacmap_revise_plan, bacmap_get_plan,
  bacmap_confirm_plan_locally, bacmap_submit_task, bacmap_task_status,
  bacmap_task_cancel, bacmap_task_result
```

有两件事需要知道：

1. Hermes 需要**自己的**模型配置（在 Hermes 里用 `/model` 或 `/login`）。这与 bacmap 的
   `config.toml` 端点是两回事，后者只驱动任务内解读。
2. 默认的 `cloud` Profile 只暴露数据分级上限内的工具；看不到 `bio_get_result` 是正常的。
   确切列表由 `bacmap_capabilities` 报告。

### 3.2 启动并说出请求

```bash
hermes
```

在对话中给出**绝对路径**：

> 用标准管线分析 /data/run42 下的八套 *V. parahaemolyticus* reads。

Hermes 首先调用 `bacmap_capabilities`，然后尝试创建计划。如果路径有误，它会收到明确的
`validation_error`（例如 `directory not found: /data/run42`），并转述给你。

### 3.3 它返回的计划

工具调用会显示为 `mcp__bacmap__bacmap_create_plan`，返回：

```json
{
  "plan_id": "9a3f2c1b7d4e4f60",
  "version": 1,
  "state": "awaiting_confirmation",
  "tasks": [{"task_type": "analyze", "fastq_dir": "/data/run42", "species": null}],
  "plan_hash": "c1d2e3f4a5b6... (64 chars)",
  "next_step": "Ask the user to review and confirm this exact version in bacmap itself: `bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6` (or the Web console). You cannot confirm it; poll bacmap_get_plan for task_ids after confirmation."
}
```

Hermes 会把它表述为"计划已就绪；请在 bacmap 中确认"——**它无法确认**，这是设计使然。

### 3.4 你不离开对话即可确认

计划带有一个 `confirm_url`；打开它会落到 Web 计划页（已登录），你在此阅读完整参数并点击
确认：

```
http://127.0.0.1:8800/plans/9a3f2c1b7d4e4f60?version=1
```

三种确认方式，从最简便的开始：

1. **Web 链接**（默认）：点击、确认、回到 Hermes；
2. **本地对话框**（有图形界面的工作站）：对 Hermes 说"用本地对话框确认"；它调用
   `bacmap_confirm_plan_locally`，你在系统对话框中点击批准（仅 stdio 会话可用）；
3. **预授权**（管理员选项）：在 `config.toml` 中配置 `[plans.auto_confirm]` 后，仅含 analyze、
   针对**已登记样本**且在样本上限内的计划会被自动确认（`actor=policy:auto-confirm`）；
   目录摄入、脚本、mine/write/发布仍然需要人工。

计划按客户端隔离：如果你切换到另一个 Harness，它无法读取或修订第一个客户端创建的计划。
请用同一个客户端确认或完成它，或者创建一个新计划。

请求本地对话框的说法大致如下：

> **你**："在这台机器上弹出确认对话框。"
>
> **智能体**：（调用 `bacmap_confirm_plan_locally`）"已为计划 v1 打开对话框，哈希 c1d2e3f4a5b6。"

点击 **确认并提交** 后返回 `state=submitted` 以及任务 ID；取消则计划保持待确认，并把
Web 链接作为兜底交给你。该工具仅在 Hermes 以本地（stdio）进程连接时可用。

终端命令仍可作为兜底：

```bash
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
```

### 3.5 回到 Hermes：跟踪运行

> 已确认——盯着这次运行，完成后告诉我。

它会针对 `task_ids` 调用 `bacmap_get_plan`，然后轮询 `bacmap_task_status`。典型回复：

> 八个样本中五个已完成，三个正在组装，没有失败。

完成后：

> 汇总结果，重点讲血清型和耐药。

Hermes 调用 `bacmap_task_result`（云端 Profile 只返回门的计数；本地 Profile 返回逐样本
结论），并指引你到 Web 样本页，或运行 `bacmap sample show HZCPE-01` 查看报告。

### 3.6 如果它说看不到某些工具

说明你在 `cloud` Profile 上：

- **Hermes 使用云端模型**：这正是红线在起作用；只能做规划与解释。要读取单菌株结果，
  管理员可以将 `cloud_max_data_class` 提高到 `"D2"`（上限）。
- **本地/局域网模型**：在 `config.toml` 中设置 `[mcp] allow_local_trusted = true`，把 `args`
  改为 `["mcp", "--profile", "local-trusted"]`，然后重启 Hermes。

## 4. 追问：让它读取并比较

无需知道工具名：

| 你说 | 它做 |
|---|---|
| "这批里有没有碳青霉烯酶？" | 检索已入库的耐药基因 |
| "HZCPE-03 和去年的 O3:K6 菌株有关系吗？" | cgMLST 等位基因距离 + 阈值（无阈值时回答"未判定"） |
| "这两次运行为什么不同？" | 对比运行记录：参数、数据库、工具、输入 |
| "把八株的 ST 和血清型列成表" | 读取结果并汇总（可能提议写一个小脚本） |
| "哪些样本需要我复核？" | 列出审计标记及原因 |

回答会带上**证据**：样本、`run_id`、数据库版本。你随时可以问"依据是什么？"。

## 5. 数据管理：交给你才知道的信息

菌株来自哪里、实验室结果、支持性文献——直接说出来即可：

> **你**："HZCPE-01 于 2026 年 10 月 12 日采集自深圳一个海鲜市场。"
>
> **智能体**：（调用 `bacmap_record_data`，它提交一个 `record` 任务）"已记录。要顺便添加一条
> 药敏结果吗？"

> **你**："美罗培南 MIC 0.25 mg/L，判读为 S。"
>
> **智能体**："已记录（lab_result）。"

> **你**："把这篇文章加上：PMID 12345678。"
>
> **智能体**："已作为条目 12 暂存；只有通过审核后才能被引用。现在就批准吗？"

所有写入都走任务层：它们可审计，而不是"智能体直接改了数据库"。
MCP 的 `bacmap_record_data` 只在 **local-trusted** Profile 下注册；默认 `cloud` Profile 请用
Web 的 **记录 / Records** 页面或 `bacmap record …`，走的是同一条任务路径。

当信息完整后：

> **你**："把我们本地的 *V. parahaemolyticus* 汇总成一个基线发布版，看看能不能发。"
>
> **智能体**：（*curate* 计划）"纳入 12 个菌株实体，1 个因元数据不完整被排除；发布需要你的
> 签名。"

**同一菌株的多次测序运行绝不会被重复计数**：bacmap 按菌株实体归并，选取一个有代表性的
运行，并记录选了哪个以及为什么。

## 6. 深度分析：它写脚本，你审阅

对于标准管线覆盖不了的问题：

> **你**："按 ST 汇总本地 *V. parahaemolyticus*，画出分布，并检查 2025 年之后是否有新的
> 克隆群。"

智能体提交一个 `mine` 计划，其中包含**完整脚本**。你不需要写 Python，但要做一件事：阅读
脚本做了什么（读了哪些文件，写了什么）。确认后它在无网络沙箱中运行；产物需通过挖掘门并
由你签字。

以对话方式迭代：

> **你**："图看不清——按年份分面，并把样本少于三个的 ST 合并为 'other'。"
>
> **智能体**：（修订计划；脚本 diff 可见）"确认后我就重跑。"

## 7. 报告：它起草，门负责核验

> **你**："用这些结果和文献给我的主管起草一份周报——强调暴发簇和耐药。"
>
> **智能体**：（*write* 计划）"草稿已就绪；每条引用都来自已批准的条目；引用门已通过；
> 等待你签字。"

未批准的文献以及本地知识库不认识的引用会被引用门拒绝——这就是让"看起来合理"不再算作
证据的方式。

## 出问题时，先问它（自然语言排障）

你不必读日志。描述现象；智能体会调用任务/诊断工具，并带着原因和下一步回来：

> **你**："分析任务失败了——发生了什么？"
>
> **智能体**：（`bacmap_task_status`）"任务 `3f9c…` 以 `sandbox_unavailable` 失败；请安装
> 沙箱后端（Apptainer 或 Podman）——直通模式仅用于开发。"

在 cloud Profile 上它看不到原始消息（其中可能包含样本 ID 或路径），但它会收到**脱敏的
故障类型和建议修复**；在 `local-trusted` 上它还能看到完整消息，并可以调用 `bio_diagnose`
解析 Snakemake 日志。

典型的对话式修复：

| 现象 | 你说 | 它做什么 |
|---|---|---|
| 任务失败 | "为什么失败？" | 返回故障类型和修复命令；不会替你安装任何东西 |
| 没有沙箱 | "我该装哪个沙箱？" | 建议 `pixi global install podman`，解释直通风险 |
| 路径缺失 | "它说目录不存在" | 指出 `validation_error: directory not found`；你修正绝对路径并重新规划 |
| 数据集 ID 冲突 | "为什么它不接受这个文件？" | 解释冲突，建议 `<isolate>__<platform>__<date>` |
| 确认冲突 | "它说输入变了" | 解释规划后目录发生变化；提议修订（`bacmap_revise_plan`）以重新确认 |
| 数据被阻止 | "为什么它看不到序列？" | 解释 D3/D4 红线；使用本地 Profile 或由管理员把云端上限提高到 D2 |
| 一直 running | "是不是卡住了？" | 检查状态/对账；必要时提议取消及其影响 |
| 想看完整日志 | "把完整错误给我" | 云端会解释限制；本地 Profile 或 `bacmap doctor` 显示细节 |

**边界**：智能体可以诊断、提议和修订计划，但它绝不编辑数据库、不绕过门、也不替你签字。
它给你下一步；执行与审批仍在你手中。

## 8. 始终属于你的三个动作

1. **确认计划**——在阅读完整参数（包括脚本/草稿文本）之后；
2. **为发布签字**——基线、挖掘产物、导出的报告；
3. **审计**——每一条断言都可追溯到运行记录和 GOM 版本。

## 9. 为什么有些工具不可见

那是数据红线，不是能力缺失：

| 你的模型运行在哪里 | 默认工具 | 想看到更多 |
|---|---|---|
| 云端 API | D0–D1（计划、任务、公开信息） | 管理员把 `cloud_max_data_class` 提高到 `D2`（上限） |
| 本地 / 局域网 | `local-trusted`：单菌株结果、序列、元数据 | 在 `config.toml` 中设置 `[mcp] allow_local_trusted = true` |

序列（D3）和个人数据（D4）永不发往云端模型——这正是分析在本地运行、模型只负责理解与
解释的原因。

## 10. 什么时候仍然使用 CLI 或 Web 控制台

- **部署、体检、备份、升级**：`bacmap doctor`、`backup`、`restore`
  （[运维指南](../operations/index.zh.md)）；
- **没有可用智能体时**：Web 控制台涵盖提交、确认、审批和报告；
- **自动化/批处理**：CLI 与 `/api/v1`（[界面指南](../guide/interfaces.zh.md)）。

它们是兜底，而不是"专家专属"层级。

## 11. 你可以直接说的话

- "我们本地有哪些沙门菌，最近三个月新增了什么？"
- "对 /data/batch7 里每个组装好的基因组跑标准分析。"
- "HZCPE-02 的血清型和耐药基因是什么？和 HZCPE-01 比一下。"
- "这批里有没有克隆簇？给我距离和推理依据。"
- "把 2025 年以来的所有数据按来源对 ST 做交叉表。"
- "给这个菌株添加元数据：2026 年 10 月 12 日，深圳，食品，海鲜。"
- "起草本周的监测简报；只使用已批准的文献。"
- "之前那次运行用的是哪个 CARD 版本？"
- "为这个计划弹出本地确认对话框。"
- "哪些任务在等我的审批？"
- "把结果和原始数据备份到 /backup。"

## 12. 一行话记住

> **你描述 → 它提议 → 你确认 → bacmap 执行并记录 → 你签字。**
>
> 如果你忘了命令，记住三件事：**数据在哪里、你需要什么、谁来签字。**

延伸阅读：[界面指南](../guide/interfaces.zh.md) · [智能体 Harness](../guide/agent-plans.zh.md) · [运维](../operations/index.zh.md) · [工具参考](../reference/tools.zh.md)
