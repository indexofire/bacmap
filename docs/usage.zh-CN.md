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
bacmap task list|show|submit|approve|cancel         # 任务查询与写操作（显式、无 LLM；list 别名 ls）
bacmap task show <短前缀>                          # ID 支持 git 式短前缀：list 显示 12 位直接可用，多义时加长
bacmap task submit --type analyze --fasta-dir <目录> [--species <码|名>]
                                                   # 组装 FASTA 目录直入：自动扫描登记后提交标准
                                                   # analyze；--species 省略时逐株 gside 自动识别（v1.4.38）
bacmap task submit --type analyze --fastq-dir <目录> [--species <码|名>]
                                                   # reads 目录直入：自动识别 *_R1/_R2 配对登记；
                                                   # 物种省略登记 UNK（管线内鉴定，血清型等不路由）
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web 控制台（含助手）
bacmap mcp [--read-only] [--home H]                # MCP 服务器（stdio/HTTP）
```

查询类子命令支持 `--json`；写操作与 Web/MCP 走同一套门与审批。

顶层命令分两类:**界面/模式**(`mcp`、`web`、`tui`、`console`——接管终端或绑定端口)与
**命令**(`overview`、`task`、`sample`、`search`、`ask`、`chat`——执行一次查询/写操作后退出)。
`bacmap` 本身**就是**命令行界面,故命令直接挂在顶层(`bacmap task ls`),不再套一层 `cli`
子命令;`web`/`tui`/`console` 是并列的其他交互形态。

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

**流式输出与思考指示（v1.4.31；v1.4.32 思考内联主区）**：TUI 对话与 CLI `ask`/`chat` 走
事件流——模型思考增量（GLM 等原生 reasoning 流）**内联显示在会话主区**（dim 斜体实时滚动，
回合结束**保留全文**，`Ctrl+T` 折叠/展开最近一次），回复以打字机效果原位流式打出并以权威
文本定稿，工具调用以活动行提示（如 `⠋ 调用 bio_list_samples…`），`Esc` 取消在途请求。
Web `/assistant` 暂为整页返回（无流式）。结构化计划契约不变（ADR-10 规划型；流式仅是展示层，
最终结果仍经 pydantic-ai 完整校验）。

**云端端点下的助手（v1.4.30）**：助手路由到 `cloud` 端点（GLM、DeepSeek 等外部 API）时，
工具带按 `cloud_max_data_class` 自动裁剪——D4 元数据/检验查询（`bio_query_metadata` 等）与
D3 数据集查看（`bio_inspect_dataset`）不进会话，沙箱工具（`sandbox_run`/`sandbox_shell`）
整体排除，会话数据级别 ≤D2；本地/局域网端点则保留全量工具。要在云端获得完整的样本查询与
规划能力，管理员需把 `cloud_max_data_class` 放宽到 `"D2"`（上限，见配置文档 §3）。
ADR-16 红线不变：D3/D4 数据任何配置都不会发往云端。

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

助手读不了任意宿主路径——这是设计（ADR-11：原始数据 D3 不进 LLM 上下文），不是故障。
外部数据的唯一入口是 `mine` 任务的 `input_paths` 参数。**对话里直接给路径即可**：

```bash
$ bacmap ask "读取 /data/2026批次/st_list.csv，按 ST 统计样本数并画柱状图"
bacmap › 收到。/data/... 是外部路径，需要先走 mine 任务：
       零拷贝登记（SHA256）→ 只读挂载进沙箱 → 在沙箱内统计。
建议执行的分析计划：
  1. mine —— 登记 csv 为输入数据集；按 ST 分组计数，输出 st_counts.csv + st_counts.png
确认提交该计划？ [y/N]
```

确认后任务执行链路：**登记 → 只读挂载 → 沙箱内跑脚本 → 产物落工作区 → 挖掘门等签字**。
脚本通过工作区 `context.json` 的 `datasets` 映射（`id → 路径`，注意是**对象不是数组**）
拿到数据位置。

`input_paths` 的规则（`store/datasets.py`）：

- 路径**必须已存在**；文件或目录均可（目录递归登记全部文件），空目录报错；
- **零拷贝**：只记哈希与身份（dev/inode/mtime），原始数据原地不动——登记后
  **不要移动/删除原文件**，否则挂载失效（数据集标记 `missing`）；
- 同内容按清单哈希**去重**（复用 `dataset_id`）；
- `bio_inspect_dataset` 指定 `dataset_id` 且 `verify=true` 时重算 SHA256，检测内容是否变化；
- 该参数**没有全局配置项**，按次随任务传入；表单/CLI/MCP 均不收 mine（见 §4 表单细则）。

**执行前提**：沙箱后端（Apptainer 或 Podman，见安装指南 §6）。缺失时任务失败并提示
「沙箱不可用」——装 `podman` 即解，无需其它配置。云端 GLM 助手可以**规划** mine 任务，
但会话内不能查看已登记数据集内容（D3 工具在云端被裁剪）或在会话内迭代脚本——
需要「看数据再改脚本」的工作流请配本地/局域网端点。

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
  （回看时停止自动滚动）· `Ctrl+P` 命令面板 · `Ctrl+Y` 确认计划/待签批。**开屏即聚焦输入框**，
  可直接输入。
- **Leader `Ctrl+G` 和弦**：`n` 新会话 · `i` 输入框 · `l` 任务 · `s` 样本 · `m` 模型/端点 · `t` 主题 ·
  `a` **签批选中的 `awaiting_approval` 任务**（提示栏显示任务与签名，`Ctrl+Y` 确认、`Esc` 取消；
  签名默认系统用户名）· `h` 帮助 · `q` 退出。
- **失败回显**：提交的任务进入 `failed`/`cancelled` 时，会话区会追加一行
  `任务 <id> failed（<step>）：<原因>`（每个任务只报一次），不必盯着侧栏。
- **斜杠命令**：`/help /new /clear /tasks /samples /search <kw> /result <样本> /model
  /approve <ID> [签名] /analyze <样本> /curate [scope] /quit`（`/analyze`、`/curate` 为显式
  无 LLM 路径；`/approve` 的 ID 支持 `task list` 显示的短前缀，无参时签批任务表选中项；
  `/result` 无参时渲染样本表选中样本的关键结果与报告路径）。

输入框即助手：规划 → 确认（`Ctrl+Y`）→ 提交。窄终端下侧栏自动折叠，宽度恢复时还原用户偏好。
`bacmap console` 仍是编号菜单，面向偏好引导式操作的用户。

## 4. Web 控制台（任务 / 助手 / 样本 / 检索）

`bacmap web` 后浏览器打开 `http://127.0.0.1:8800`：

1. **助手**（`/assistant`）——用自然语言描述需求，页面显示回复与建议计划，点按钮确认并提交
   （多轮会话保存在服务端）
2. **提交任务**（任务页）——显式表单：任务类型 + 样本列表 / 范围 JSON
3. **监控**——六态徽章（排队中/运行中/待审批/已完成/已失败/已取消），详情页每 2 秒自动刷新
4. **查询结果**——**样本**页浏览已完成样本（列表、单株详情含检出基因）。详情页有
   **查看 HTML 报告**（在浏览器**内联**渲染，带 `sandbox` CSP：禁脚本、禁外联）与
   **下载**（`?download=1`）；**检索**页按关键词或结构化字段查找
5. **审批**——任务到 `待审批` 时详情页出现审批卡：填审批人、决定（approve/reject）、签名口令，提交后过挖掘门/发布门放行

> 审批是六道门的一环：未签字的挖掘产物进不了报告、不达金标准的特征库发不了版——
> 这是设计（智能体不能自己签字），不是故障。

### 任务表单填写细则

**「样本列表」**（analyze 任务用）填的是**已注册的样本 ID**（如 `SAM-TYP-001`），
不是文件路径、不是自然语言：

- 多个样本用**英文半角逗号或换行**分隔。**中文全角逗号 `，` 不被识别**——整段会被当成
  一个非法 ID 而报「非法样本 ID」（TUI 的 `/analyze` 命令还额外支持空格分隔）；
- 样本 ID 白名单 `^[A-Za-z0-9._-]+$`：字母/数字/`.`/`_`/`-`，**不能含中文和空格**；
- 样本 ID 从哪来：`gs/<ID>/<ID>_R{1,2}.fastq.gz` 约定布局，或登记
  `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`（登记优先，见 §7 端到端示例与配置指南 §5）。

**「scope」**（curate 任务用，可选）是一个 JSON 对象，圈定纳入本地流行特征库的样本范围：
`{"pathogen": "Salmonella"}` 按病原子串筛选；`{"strains": ["SAM-001", "SAM-002"]}` 按清单筛选；
留空默认纳入全部合格样本（逐株纳入检查不通过的记入排除清单）。analyze 任务忽略此字段。

**mine/write 不走表单**：属开放路径（需脚本/草稿参数），只能经对话助手（确认后提交）
或 Python API 提交——Web 表单、CLI `task submit`、MCP 均刻意不收，防伪造请求与脚本注入。

### 远程访问：SSH 隧道（推荐方式）

bacmap web 默认只绑 `127.0.0.1`（ADR-16）。需要从其他电脑访问时，**不要**直接
`--host 0.0.0.0` 裸暴露：未设置 `BACMAP_WEB_TOKEN` 时 bacmap 会**拒绝在非回环地址启动**
（fail-fast，与 MCP HTTP 传输一致）；设了 token 虽可启动，仍建议优先用 SSH 隧道，
加密与认证全部由 SSH 承担，bacmap 侧零改动：

> `BACMAP_WEB_TOKEN`（`--token-env`）启用鉴权。默认 `bearer` 模式以 `Authorization` 头发送，
> 而**浏览器无法设置该头**——HTML 控制台会返回 **401 并附一页操作说明**，`/login` 同样给出
> 说明页（**不再重定向**，故不存在跳转死循环）。设 `BACMAP_WEB_AUTH=cookie` 改为在 `/login`
> 登录（签名 `HttpOnly` 会话 cookie + 每个状态变更 POST 的 CSRF 令牌）；TLS 部署再加
> `BACMAP_WEB_COOKIE_SECURE=1`。启动时命令行会打印访问地址与当前鉴权提示。

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

**封闭与开放：LLM 的能力边界。** 四类任务分两种执行形态：`analyze`/`curate` 走**封闭路径**
（固定 Snakemake DAG，规则集合属冻结决策，运行时不可增删改）；`mine`/`write` 走**开放路径**
（LLM 生成脚本/文本，在沙箱与门约束下执行）。LLM 的分工是三层边界：

| 层 | LLM 能做什么 | 刻意不能做什么 |
|---|---|---|
| 规划层（提交前） | 决定跑哪些任务、哪些样本、什么参数；一个计划内可**任务级组合**（如 `analyze → mine(统计) → mine(绘图) → write(报告)`） | 挑选/拼接 DAG 规则；改参数以外的流程逻辑 |
| 执行层 `analyze` | ——（封闭 DAG 原样执行） | 运行时"自由搭建流程"没有入口 |
| 执行层 `mine` | 写任意 Python 处理**已产出**的数据（统计/交叉验证/绘图） | 沙箱断网、默认镜像（python:3.12-slim）不含生信工具——拼不出即兴生信流水线 |

为什么堵死"LLM 运行时编排流程"：① `analyze` 每次运行封存为带种子、工具版本与哈希的运行
记录（ADR-18），即兴流程无法封存与复现；② 固定产出才能过确定性校验器与门，自由流程没有
可预定义的校验规则；③ 生信分析外部化给 gside/gapit/gmlst，编排本身也必须确定性与版本化
（ADR-20）。**新分析能力的正确路径是开发者行为**：新增 `.smk` 规则 + 适配器 + 测试 →
版本化部署（树哈希 stamp）→ 进入封闭集合——之后所有 analyze 任务与助手规划自动可用。

## 7. 端到端示例（新样本上机 → 报告）

```bash
# ① 布局数据并注册（reads 样本；已组装 FASTA 则登记 assembly 列，R1/R2 留空）
cp /mnt/seq_run/SAM-NEW-100_R{1,2}.fastq.gz ~/.local/share/bacmap/gs/SAM-NEW-100/
echo -e "SAM-NEW-100\tSalmonella\tgs/SAM-NEW-100/SAM-NEW-100_R1.fastq.gz\tgs/SAM-NEW-100/SAM-NEW-100_R2.fastq.gz\t" \
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

## 9. 常见问题排查（FAQ）

**提交与表单**

| 现象 | 原因与处理 |
|---|---|
| 报「非法样本 ID」 | 样本 ID 含非法字符（只允许 `A-Za-z0-9._-`），或用了**中文全角逗号**分隔——改用半角 `,` 或换行 |
| 不知道「样本列表」填什么 | 填**已注册的样本 ID**（samples.tsv / `gs/` 布局注册时的名字），不是路径；见 §4 表单细则 |
| 想在表单提交 mine | 表单/CLI/MCP 刻意只收 analyze/curate；mine 经对话助手确认提交或 Python API |

**助手与 LLM**（接入教程与完整排查表见安装指南 §5）

| 现象 | 原因与处理 |
|---|---|
| `payload D4 exceeds cloud limit` | 数据分级拦截（ADR-16）；v1.4.30 起云端助手自动裁剪工具带，不应再出现——出现请先升级版本 |
| 401 / 429(1113) / 模型不存在 | 密钥未注入、密钥与端点不匹配（GLM 通用端点 vs coding 端点）、账户无该模型额度——见安装指南 §5.2 |
| 「内置助手暂不可用」 | 统一降级提示，真实原因用 `bacmap ask "你好" 2>&1` 看 WARNING 行 |
| 对话没有流式输出 | 流式在 TUI 与 CLI `ask`/`chat`（v1.4.31）；Web `/assistant` 暂为整页返回 |
| 助手说「安全问题无法读取」路径数据 | 设计行为：外部数据走 mine 登记（§2「给助手一份数据路径」）；若任务报「沙箱不可用」装 podman（安装指南 §6） |
| mine 任务失败、消息只剩「workflow ERROR」 | 旧版环境级异常被吞成笼统消息；现任务消息会指出原因与方向（如「沙箱启动失败：no apptainer/podman on PATH → 安装 podman」）——升级后重提任务即可 |

**样本与数据**

| 现象 | 原因与处理 |
|---|---|
| analyze 找不到 FASTQ | 样本未注册：按 `gs/<ID>/<ID>_R{1,2}.fastq.gz` 布局或登记 samples.tsv（§7、配置指南 §5）；**已组装 FASTA 可登记 `assembly` 列直入封闭路径**（v1.4.33，跳过 QC/组装） |
| 登记过的数据集读不到 | 原文件被移动/删除（零拷贝登记依赖原路径）；`bio_inspect_dataset verify=true` 可检测 |
| 任务停在「待审批」 | 正常：挖掘门/发布门等人工签字，详情页审批卡操作（§4） |
