[English](usage.md) | **简体中文**

# 使用指南

bacmap 有三个人口：**CLI**（运维）、**Web 任务台**（人）、**MCP**（AI 智能体）。

## 1. CLI

```bash
bacmap --version
bacmap ask "跑 SAM-001 的分析并和去年暴发株比较"   # LLM 规划 → 确认 → 提交
bacmap chat                                        # 多轮对话式分析助手
bacmap tui [--home H]                              # 全屏 TUI（Textual）
bacmap console [--home H]                          # 交互式菜单
bacmap overview [--json]                           # 系统概览
bacmap task ls|show|submit|approve|cancel          # 任务查询与写操作（显式、无 LLM）
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web 控制台（含助手）
bacmap mcp [--read-only] [--home H]                # MCP 服务器（stdio/HTTP）
```

查询类子命令支持 `--json`；写操作与 Web/MCP 走同一套门与审批。

## 2. LLM 驱动的分析助手（CLI ask/chat、TUI 对话页、Web /assistant）

内置助手把自然语言分析需求转成可执行计划，三端共用同一 **agent 会话**（`agent/session.py`，
ADR-10 规划型 + ADR-11 开放路径）：

1. **理解 + 查现状**：LLM 可调用只读工具（`bio_list_samples` / `bio_get_result` /
   `bio_search_samples` / `bio_query_metadata` / `bio_review_flags` / `bio_compare_runs`）。
2. **规划与执行**：返回封闭任务类型组成的结构化计划——多数请求是 `analyze`（标准 Snakemake 流程）
   或 `curate`；**深度挖掘**用 `mine`（自行编写 Python 脚本，沙箱执行），复杂挖掘可拆成多个
   顺序 `mine` 任务；文本产物用 `write`。规划阶段还可调用 **`sandbox_run`** 执行脚本（无网络）
   并读回 stdout/产物——可反复迭代统计与**绘图（PNG/CSV）**，成熟后再作为 `mine` 任务过挖掘门。
3. **澄清**：需求含糊时提问，不猜测。
4. **分级确认**：读类/已有结果的查询在规划阶段直接完成；**写操作仅在确认后提交**
   （CLI 交互确认，`--yes` 跳过；TUI 按 `Ctrl+Y` 或点按钮；Web 点确认按钮）。
5. **降级（C3）**：LLM 端点不可用时助手明确告知，回退到显式子命令/任务表单——确定性路径始终可用。

示例：

```bash
$ bacmap ask "把本地沙门菌按 ST 统计并画图"
bacmap › 建议先统计再绘图。
建议执行的分析计划：
  1. mine —— 按 ST 聚合本地沙门菌并输出统计 CSV
  2. mine —— 由统计 CSV 绘制 ST 分布图
确认提交该计划？ [y/N]
```

### 给助手一份数据路径

助手读不了任意宿主路径。要用你提供的本地数据：

1. 让它规划一个 `mine` 任务，把路径放进 `input_paths`——任务会**零拷贝**登记（逐文件 SHA256）
   并把数据只读挂载进沙箱的 `/input/<dataset_id>`。
2. 用 `bio_inspect_dataset` 查看已登记内容；把 `dataset_id` 传给 `sandbox_run`（`datasets` 参数），
   或让脚本从工作区 `context.json` 读取挂载点。
3. `bio_inspect_dataset` 指定 `dataset_id` 且 `verify=true` 时重算 SHA256，检测内容是否变化。

登记表存于 GOM 库。哈希用 SHA256，是**证据**（完整性/去重指纹），**不是**回收已删除原始数据的手段——
需要可移植/防删除时再要求"物化"（复制副本）。

除 `sandbox_run`（跑一段 Python）外，另有受限的 **`sandbox_shell`**：在同一沙箱内跑**一条** shell 命令，
仅放行只读/分析白名单（`ls`、`cat`、`grep`、`zcat`、`samtools`、`seqkit`、`python` 等），
其余命令会被拒绝并要求改用需签字的 `mine` 任务；仅在真实容器后端下运行（直通默认拒绝），
每次调用写入 `$BACMAP_HOME/audits/sandbox_shell.jsonl`。

## 3. TUI 与交互菜单

`bacmap tui` 启动**会话优先**的 Textual 工作台（参考 opencode TUI 与 hermes agent REPL）：
顶部**状态头**（LLM 端点）、可折叠**侧栏**（任务/样本）、**会话区**、**计划提示**、
**输入框**，底部**按键提示栏**。

- **直接按键**：`Enter` 发送 · `Shift/Alt+Enter` 换行 · `Esc` 中断/忽略待确认计划 ·
  `Ctrl+C` 退出 · `Ctrl+B` 侧栏 · `Ctrl+R` 刷新 · `Ctrl+L` 清屏 · `Ctrl+F` 跟随开关
  （回看时停止自动滚动）· `Ctrl+P` 命令面板 · `Ctrl+Y` 确认计划。
- **Leader `Ctrl+G` 和弦**：`n` 新会话 · `l` 任务 · `s` 样本 · `m` 模型/端点 · `t` 主题 ·
  `h` 帮助 · `q` 退出。
- **斜杠命令**：`/help /new /clear /tasks /samples /search <kw> /model /analyze <样本>
  /curate [scope] /quit`（`/analyze`、`/curate` 为显式无 LLM 路径）。

输入框即助手：规划 → 确认（`Ctrl+Y`）→ 提交。窄终端下侧栏自动折叠，宽度恢复时还原用户偏好。
`bacmap console` 仍是编号菜单，面向偏好引导式操作的用户。

## 4. Web 控制台（任务 / 助手 / 样本 / 检索）

`bacmap web` 后浏览器打开 `http://127.0.0.1:8800`：

1. **助手**（`/assistant`）——用自然语言描述需求，页面显示回复与建议计划，点按钮确认并提交
   （多轮会话保存在服务端）
2. **提交任务**（任务页）——显式表单：任务类型 + 样本列表 / 范围 JSON
3. **监控**——六态徽章（排队中/运行中/待审批/已完成/已失败/已取消），详情页每 2 秒自动刷新
4. **查询结果**——**样本**页浏览已完成样本（列表、单株详情含检出基因、HTML 报告下载），
   **检索**页按关键词或结构化字段查找
5. **审批**——任务到 `待审批` 时详情页出现审批卡：填审批人、决定（approve/reject）、签名口令，提交后过挖掘门/发布门放行

> 审批是六道门的一环：未签字的挖掘产物进不了报告、不达金标准的特征库发不了版——
> 这是设计（智能体不能自己签字），不是故障。

### 远程访问：SSH 隧道（推荐方式）

bacmap web 默认只绑 `127.0.0.1`（ADR-16）。需要从其他电脑访问时，**不要**直接
`--host 0.0.0.0` 裸暴露（界面无认证，局域网内任何人可提交/审批任务）——用 SSH 隧道，
加密与认证全部由 SSH 承担，bacmap 侧零改动：

> `BACMAP_WEB_TOKEN`（`--token-env`）为**程序化/API** 客户端增加 Bearer 校验。
> 浏览器无法发送 `Authorization` 头，因此一旦配置 token，HTML 控制台会返回 401——
> 界面仍走下面的隧道方式。

```bash
# 在你自己的电脑上执行（user 为工作站账号，10.0.0.5 换成工作站实际 IP）：
ssh -L 8800:127.0.0.1:8800 user@10.0.0.5
# 保持连接，然后本地浏览器打开 http://127.0.0.1:8800
```

- 多个用户各自建各自的隧道，互不影响
- 传输全程加密——符合基因组数据（D3/D4）不出本地网络且不落明文的要求
- 无需 root、无需在工作站开防火墙端口、无需给 bacmap 加认证层
- 数据文件仍由操作员在工作机上按[配置指南 §5](configuration.zh-CN.md)注册；
  远程上传功能属于规划项（待智能体生信分析功能完成后再考虑）

## 5. MCP 智能体接入

任意支持 MCP stdio 的客户端都能接（Hermes / Codex / OpenCode / OpenClaw / Claude…）。
客户端配置样例：

```json
// OpenCode（opencode.json）
{ "mcp": { "bacmap": { "type": "local",
  "command": ["/path/to/.pixi/envs/default/bin/bacmap", "mcp"], "enabled": true } } }
```

```toml
# Codex（~/.codex/config.toml）
[mcp_servers.bacmap]
command = "/path/to/.pixi/envs/default/bin/bacmap"
args = ["mcp"]
```

对支持 Streamable HTTP 的客户端（ADR-12）：仅绑本机或 unix socket，且 **强制 Bearer 鉴权**：

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
# 或使用 unix socket：bacmap mcp --transport http --uds /run/bacmap-mcp.sock
```

客户端指向 `http://127.0.0.1:8765/mcp`，带请求头 `Authorization: Bearer $BACMAP_MCP_TOKEN`。未设置 token 时 HTTP 传输拒绝启动。

接入后智能体可调 **23 个工具**：

| 类别 | 工具 | 说明 |
|---|---|---|
| 单步计算（21） | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` `bio_compare_runs` … | 同步返回结果，可吃任意本地路径 |
| 任务提交 | `bacmap_submit_task` | **写操作唯一入口**；analyze/curate 任务异步执行 |
| 任务查询 | `bacmap_task_status` | 轮询状态与门消息 |

智能体还可经 MCP prompts 获取领域说明书：每个已交付角色（analyst / curator / miner / literature / writer / epidemiologist）以 `bacmap_role_<名称>` prompt 暴露其说明书（全局原则 + 权限边界 + SKILL 指导）。

安全模型（对任何客户端一致）：

- MCP 通道**无直写**——写库只能经任务提交走六道门；
- 不信任的客户端先接 `bacmap mcp --read-only`（只暴露查询工具）；
- 连通性排查：`hermes mcp test bacmap`。

在智能体里的典型对话：

> "对 SAM-TYP-001 跑全套分析" → 智能体调 `bacmap_submit_task`(analyze) → 拿 task_id
> → 轮询 `bacmap_task_status` → "已完成，报告在 results/SAM-TYP-001/report/"

## 6. 四类任务与门

| 任务 | 内容 | 关键门 |
|---|---|---|
| `analyze` | 全流程管线：QC→组装→分型→AMR/毒力→报告；**任务末尾自动生成 HTML 报告**（`results/{id}/report/{id}_report.html`） | 分析结论门（矛盾解读标记人工复核） |
| `curate` | 本地流行特征库构建（去标识、汇总） | **发布门**：不达金标准阈值拒绝发布 |
| `mine` | 沙箱内跑自定义分析脚本 | **签字门**：未签字产物不得进入报告 |
| `write` | LLM 撰写报告/简报 | **引用门**：引用知识库中不存在的条目拒绝导出 |

断点恢复：任务引擎基于 DBOS，运行中 kill 进程重启后从断点继续（V2 已验证）。

## 7. 端到端示例（新样本上机 → 报告）

```bash
# ① 布局数据并注册
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz" \
  >> ~/.local/share/bacmap/workflows/bacmap/config/samples.tsv

# ② 提交（Web 表单选 analyze 填 SAM-NEW-100，或智能体对话）
# ③ 监控直至完成；待审批任务在详情页签字
# ④ 取报告
ls ~/.local/share/bacmap/results/SAM-NEW-100/report/
```

## 8. 已知能力边界（外部工具依赖）

| 字段/能力 | 状态 | 等待 |
|---|---|---|
| 物种鉴定（marker/panel/mash 档） | ✅ gside 已接入 | — |
| 血清型 | ⏳ `pending_gapit` 占位 | gapit 血清型子命令（开发中） |
| 基因组注释 | ⏳ `pending_external_tool` 占位 | gapit 注释子命令 |
| 物种鉴定 GTDB-Tk 标准档 / 分类 | ⏳ `pending_gside` 占位 | gside GTDB-Tk 档 |

管线在这些字段上照常运行并输出占位值，外部能力就绪后替换规则即可，无需改架构。
