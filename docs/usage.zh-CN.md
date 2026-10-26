[English](usage.md) | **简体中文**

# 使用指南

bacmap 有三个人口：**CLI**（运维）、**Web 任务台**（人）、**MCP**（AI 智能体）。
对话在外部智能体 Harness（Hermes / Pi / DSH）的原生界面里进行，经 MCP 接入——见
[智能体 Harness 指南](harnesses.zh-CN.md)；v1.6 起内置助手已移除（ADR-21）。

## 1. CLI

```bash
bacmap --version
bacmap tui [--home H]                              # 全屏任务台（Textual）
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
bacmap plan ls|show|confirm|reject                 # 审阅/确认智能体提出的计划（v1.5.1）
bacmap record metadata|lab|knowledge-import|knowledge-approve
                                                   # 经任务层录入元数据/化验/知识库（v1.7）
bacmap sample ls|show                              # 样本浏览
bacmap search --query <kw>                          # 样本检索
bacmap web [--host 127.0.0.1] [--port 8800]        # Web 控制台（任务 / 计划 / 样本）
bacmap mcp [--read-only] [--profile cloud|local-trusted] [--home H]
                                                   # MCP 服务器（stdio/HTTP），默认 cloud Profile
```

查询类子命令支持 `--json`；写操作与 Web/MCP 走同一套门与审批。
日常运维（体检、备份、恢复、事件保留）见[运维指南](operations.zh-CN.md)。

顶层命令分两类:**界面/模式**(`mcp`、`web`、`tui`、`console`——接管终端或绑定端口)与
**命令**(`overview`、`task`、`sample`、`search`、`ask`、`chat`——执行一次查询/写操作后退出)。
`bacmap` 本身**就是**命令行界面,故命令直接挂在顶层(`bacmap task ls`),不再套一层 `cli`
子命令;`web`/`tui`/`console` 是并列的其他交互形态。

## 2. 与 bacmap 对话：外部智能体与计划

内置对话已移除（ADR-21）。在 Hermes、Pi、DSH（或任意 MCP 客户端）里与 bacmap 对话；
智能体提出**计划**，由你在 bacmap 中确认该确切版本：

```bash
bacmap plan ls                       # 各计划的最新版本
bacmap plan show <plan_id>           # 完整参数、哈希、输入指纹
bacmap plan confirm <plan_id> --hash <前 12 位>
bacmap plan reject <plan_id> --version 1 --reason "样本选错"
```

Web 控制台的 **计划**（`/plans`）页面提供同样操作。客户端配置见
[智能体 Harness 指南](harnesses.zh-CN.md)，MCP 工具面见 §5。

### 给 mine 任务一份数据路径

智能体读不了任意宿主路径——这是设计（ADR-11：原始数据 D3 不进 LLM 上下文）。外部数据只经
`mine` 任务的 `input_paths` 参数进入：向智能体要一个 `mine` 计划、确认后任务执行——**零拷贝登记
（SHA256）→ 只读挂载进沙箱 → 跑脚本 → 产物落工作区 → 挖掘门等签字**。脚本通过工作区
`context.json` 的 `datasets` 映射（`id → 路径`，注意是**对象不是数组**）拿到数据位置。

`input_paths` 的规则（`store/datasets.py`）：

- 路径**必须已存在**；文件或目录均可（目录递归登记全部文件），空目录报错；
- **零拷贝**：只记哈希与身份（dev/inode/mtime），原始数据原地不动——登记后
  **不要移动/删除原文件**，否则挂载失效（数据集标记 `missing`）；
- 同内容按清单哈希**去重**（复用 `dataset_id`）；
- `bio_inspect_dataset` 指定 `dataset_id` 且 `verify=true` 时重算 SHA256，检测内容是否变化；
- 该参数**没有全局配置项**，按次随任务传入；表单/CLI/MCP 均不收 mine（见 §4 表单细则）。

**执行前提**：沙箱后端（Apptainer 或 Podman，见安装指南 §6）。缺失时任务失败并提示
「沙箱不可用」——装 `podman` 即解，无需其它配置。

除 `sandbox_run`（跑一段 Python）外，另有受限的 **`sandbox_shell`**：在同一沙箱内跑**一条** shell 命令，
仅放行只读/分析白名单（`ls`、`cat`、`grep`、`zcat`、`samtools`、`seqkit`、`python` 等），
其余命令会被拒绝并要求改用需签字的 `mine` 任务；仅在真实容器后端下运行（直通默认拒绝），
每次调用写入 `$BACMAP_HOME/audits/sandbox_shell.jsonl`。这两个工具属于**任务内**智能体，
MCP 客户端永远看不到它们。

## 3. TUI 与交互菜单

`bacmap tui` 是一个**任务台**：状态头（LLM 端点）、可折叠侧栏（任务 / 样本）、操作日志与命令输入框，
底部为按键提示。它是查看与少量显式操作的界面——没有对话。

- **直接按键**：`Enter` 执行命令 · `Esc` 取消待签批 / 聚焦输入框 · `Ctrl+C` 退出 · `Ctrl+B` 侧栏 ·
  `Ctrl+R` 刷新 · `Ctrl+L` 清屏 · `Ctrl+Y` 确认待签批。输入框开屏即聚焦。
- **Leader `Ctrl+G`** 和弦（输入框聚焦时同样有效）：`i` 输入框 · `l` 任务 · `s` 样本 · `m` 端点 ·
  `t` 主题 · `a` **签批选中的 `awaiting_approval` 任务**（提示栏显示任务与签名；`Ctrl+Y` 确认、
  `Esc` 取消；签名默认取系统用户名）· `h` 帮助 · `q` 退出。
- **失败回显**：任务结束为 `failed`/`cancelled` 时日志追加一行
  `任务 <id> failed（<step>）：<原因>`，无需盯着侧栏。
- **斜杠命令**：`/help /clear /tasks /samples /search <kw> /model /result <样本>`
  `/approve <ID> [签名]` `/analyze <样本> /curate [scope] /quit`（`/analyze`、`/curate` 是显式的
  无 LLM 路径；`/approve` 接受 `task list` 显示的短前缀，无参时签批选中行；`/result` 渲染选中样本的
  关键结果与报告路径）。

窄终端自动折叠侧栏，宽度恢复时回到你的偏好。自然语言交互请用外部 Harness（ADR-21）；
`bacmap console` 仍是给偏好提示式操作的用户准备的编号菜单。

## 4. Web 控制台（任务 / 计划 / 样本 / 检索）

`bacmap web` 后浏览器打开 `http://127.0.0.1:8800`：

1. **计划**（`/plans`）——智能体经 MCP 提出的计划，显示完整参数、哈希与输入指纹；在此确认或拒绝
   （等同 `bacmap plan`）
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

**「scope」**（curate 任务用，可选）是一个 JSON 对象，圈定纳入本地流行特征库的 isolate 范围。
同一 isolate 有多个 dataset 时只纳入一次：默认选最新分析，也可用
`{"representative_dataset": {"<isolate>": "<dataset>"}}` 显式指定（候选清单在
`representative_runs` 记录选择，在 `superseded` 列出未选中的 dataset）。
`{"pathogen": "Salmonella"}` 按病原子串筛选；`{"strains": ["SAM-001", "SAM-002"]}` 按清单筛选；
留空默认纳入全部合格样本（逐株纳入检查不通过的记入排除清单）。analyze 任务忽略此字段。

**mine/write 不走表单**：属开放路径（需脚本/草稿参数），只能经人工确认的计划（向外部 Harness 要）
或 Python API 提交——Web 表单、CLI `task submit`、MCP 均刻意不收，防伪造请求与脚本注入。

### 数据录入：元数据 / 化验 / 知识库（v1.7）

这三类输入不是可以直接调用的注册表工具——它们经任务层写入，因此每次都有任务与事件审计。
用 **记录** 页（`/records`）或命令行：

```bash
bacmap record metadata --strain-id S1 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id S1 --category mic --test-name meropenem --result 0.25 --unit mg/L
bacmap record knowledge-import --title "论文标题" --identifier PMID:12345678
bacmap record knowledge-approve 7        # 引用门只认已审核条目
```

每条命令提交一个 `record` 任务，`bacmap task show <id>` 查看结果。知识库条目先入暂存
（`approved_by` 为空），执行 `knowledge-approve` 后才成为可引用来源。record 任务不进计划，
也绝不经 MCP 暴露（D4 写）。

### JSON API `/api/v1`（v1.5.2）

Web 服务同时提供版本化 JSON API，与页面共用鉴权。它是**可信界面**：持有 Web 令牌即操作员，
切勿把该令牌交给 Harness。

| 方法与路径 | 用途 |
|---|---|
| `GET /api/v1/capabilities` | API 版本、bacmap 版本、可计划任务类型、功能清单 |
| `GET /api/v1/tasks` · `GET /api/v1/tasks/{id}` · `POST /api/v1/tasks/{id}/cancel` | 任务 |
| `GET /api/v1/plans` · `GET /api/v1/plans/{id}?version=` | 计划 |
| `POST /api/v1/plans/{id}/confirm` `{"version", "plan_hash", "confirmer"}` · `POST /api/v1/plans/{id}/reject` `{"version", "reason"}` | 确认或拒绝计划 |
| `GET /api/v1/events?after=&task_id=&plan_id=` | 游标之后的领域事件（`last_seq`） |
| `GET /api/v1/events/stream` | Server-Sent Events，按 `Last-Event-ID` 续传 |
| `GET /api/v1/samples?cursor=&limit=` | 游标分页的样本列表（只解析请求的那一页） |
| `GET /api/v1/runs` · `GET /api/v1/runs/{id}` · `GET /api/v1/runs/{id}/compare?other=` | 运行记录与来源比较（v1.7.1） |
| `GET /api/v1/gom/objects?type=&limit=` · `GET /api/v1/gom/objects/{id}?version=` | GOM 对象，默认最新版本（v1.7.1） |

错误统一为 `{"code": "validation_error" | "not_found" | "conflict", "error": "..."}`，HTTP 400/404/409。
cookie 模式下的状态变更请求须带 `X-CSRF-Token` 头，值等于 `bacmap_csrf` cookie。事件记录计划与任务的
转换（创建、确认、提交、步骤、状态、审批）；事件不是真相来源，断线后客户端应重新读取任务或计划。

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

v1.5 起，与 bacmap **对话**的推荐方式是外部智能体 Harness 的原生界面——**Hermes、Pi（≥0.99）或 DeepSeek Harness（DSH）**——经 MCP 接入（冻结 ADR-21）。bacmap 保留 CLI 与 Web 控制台承担确定性操作以及**计划确认与审批**（这两件事不在 Harness 内完成）。其他支持 MCP 的客户端（Codex / OpenCode / OpenClaw / Claude…）同样可接。

```yaml
# Hermes（~/.hermes/config.yaml）
mcp_servers:
  bacmap:
    command: /path/to/.pixi/envs/default/bin/bacmap
    args: ["mcp"]                       # 本地模型时追加 "--profile", "local-trusted"
```

```json
// Pi（~/.pi/agent/mcp.json，Pi ≥ 0.99）
{ "mcpServers": { "bacmap": {
  "command": "/path/to/.pixi/envs/default/bin/bacmap", "args": ["mcp"] } } }
```

```yaml
# DSH（$DSH_HOME/cordis.patch.yml；新增条目必须包在 insert: 下）
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: /path/to/.pixi/envs/default/bin/bacmap
      args: ['mcp']
```

其他客户端配置样例：

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

### Profile：客户端能看到什么（v1.5）

每个 MCP 服务实例在启动时绑定一个 **Profile**，客户端无法更改——MCP 客户端背后可能是 bacmap 无法验证的云端模型（ADR-16）。

| Profile | 可见工具 | 开启方式 |
|---|---|---|
| `cloud`（默认） | 输出数据级别 ≤ `[llm.data_policy].cloud_max_data_class`（默认 D1，最多 D2）的读/算工具；开箱即为 `bio_list_reference_genomes`、`bio_diagnose` 与任务工具 | 无需配置 |
| `local-trusted` | 全部读/算工具，至 D4（序列、元数据、检验结果） | 管理员在 `config.toml` 设置 `[mcp] allow_local_trusted = true`，再以 `bacmap mcp --profile local-trusted` 启动；未设置时拒绝启动 |

只有 Harness 使用**本地或内网模型**时才用 `local-trusted`。被隐藏的工具在调用层也会被再次拒绝。HTTP 下需要同时提供两种 Profile 时，以不同端口、不同 token 各起一个实例。

任务提交者由服务端认定（`mcp-stdio:<profile>:<OS 账户>` 或 `mcp-http:<profile>`）；`bacmap_submit_task` 不再接受 `submitted_by` 参数。

接入后智能体可调（`local-trusted` 下；`cloud` 只见 D0–D1/D2 子集）：

| 类别 | 工具 | 说明 |
|---|---|---|
| 能力协商 | `bacmap_capabilities` | 版本、Profile 与数据级别上限、可计划任务类型、长任务机制——建议先调用 |
| 读/算（22） | `bio_fastq_qc` `bio_align` `bio_blast` `bio_samtools` `bio_variant` `bio_gene_scan` `bio_seq_stats` `bio_compare_runs` … | 同步返回结果，可吃任意本地路径 |
| 计划（v1.5.1） | `bacmap_create_plan` `bacmap_revise_plan` `bacmap_get_plan` | **推荐的写入路径**：智能体提出类型化的 analyze/curate 任务；在 bacmap 中由人确认该确切版本前不执行 |
| 任务提交 | `bacmap_submit_task` | 兼容入口（直接提交）；analyze/curate 任务异步执行 |
| 任务查询 | `bacmap_task_status` `bacmap_task_result` | 状态（`cloud` 下不回传消息）；结果摘要含运行 ID 与门结论（`cloud` 下只给计数） |
| 任务控制 | `bacmap_task_cancel` | 取消本客户端直接提交或经其自建计划提交、仍在运行的任务 |

智能体还可经 MCP prompts 获取领域说明书：每个已交付角色（analyst / curator / miner / literature / writer / epidemiologist）以 `bacmap_role_<名称>` prompt 暴露其说明书（全局原则 + 权限边界 + SKILL 指导）。`SKILL.md` 原文另以资源 `skill://bacmap/<角色>/SKILL.md` 发布，元数据带 `sha256` 摘要。各 Harness 的接入步骤见[智能体 Harness 指南](harnesses.zh-CN.md)。

安全模型（对任何客户端一致）：

- MCP 通道**无直写**——写库只能经任务提交走六道门；
- 不信任的客户端先接 `bacmap mcp --read-only`（只暴露查询工具）；
- MCP 只保护经过 MCP 的数据。Harness 自带 Shell 与文件工具，应让 bacmap 以独立系统账户运行、Harness 用户不可读 `BACMAP_HOME`，Harness 经 HTTP + token 接入（ADR-21）；
- 计划确认与审批签名在 bacmap Web 控制台或 CLI 中完成，不在 Harness 对话里完成；
- 连通性排查：`hermes mcp test bacmap`。

### 计划：在 Harness 中提出，在 bacmap 中确认（v1.5.1）

1. 智能体调用 `bacmap_create_plan` 提交类型化任务，例如
   `{"task_type": "analyze", "fasta_dir": "/data/run42", "species": "VPA"}`。可计划类型：
   `analyze`（`samples`/`fasta_dir`/`fastq_dir` 三选一）、`curate`（`scope` = `pathogen`/`strains`）、
   **`mine`**（`objective`、`script`、可选绝对路径 `input_paths`、`sandbox_image`）与
   **`write`**（`objective`、`draft`）。返回 `plan_id`、`version` 与 `plan_hash`。
2. 人在 bacmap 中审阅并确认**该确切版本**：

   ```bash
   bacmap plan ls                                   # 各计划的最新版本
   bacmap plan show <plan_id>                       # 完整参数、哈希、输入指纹
   bacmap plan confirm <plan_id> --version 1 --hash <前 12 位>
   bacmap plan confirm <plan_id>                    # 或：先展示计划再交互确认
   bacmap plan reject <plan_id> --version 1 --reason "样本选错"
   ```

   Web 控制台的 **计划**（`/plans`）页面提供同样操作（cookie 模式下带 CSRF 防护）。
3. 智能体轮询 `bacmap_get_plan` 取得 `task_ids`，再用 `bacmap_task_status` 查询。

保证：修订（`bacmap_revise_plan`）产生新版本，旧版本不能再被确认；输入目录（或 `mine` 的输入文件）
在建计划后发生变化时，确认以冲突失败；重复确认（或 CLI 与 Web 同时确认）只提交一次。

开放路径计划（`mine` / `write`）在确认时**完整展示**——沙箱脚本或成稿全文都进入计划哈希，
所见即所执行。`mine` 在沙箱内无网络执行，产物仍要过挖掘门与签字。

### 运行记录与 GOM：证据链（v1.7.1）

```bash
bacmap run ls                                  # 最近运行记录
bacmap run show <run_id>                       # 参数、工具/数据库版本、输入哈希、种子
bacmap run compare <run_a> <run_b>             # 把差异归因到参数/数据库/工具/输入
bacmap gom ls --type analysis                  # 各对象的最新版本
bacmap gom show <object_id> [--version N]      # 对象全文
```

Web 控制台对应 **运行** 与 **GOM** 页面，运行详情页可直接比较两次运行。每次 analyze 都写一条不可修改的
运行记录（ADR-18）；GOM 对象同样不可变——新结果产生新版本，不覆盖旧版本。

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
版本化部署（树哈希 stamp）→ 进入封闭集合——之后所有 analyze 任务与外部 Harness 的规划自动可用。

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
| 想在表单提交 mine | 表单/CLI/MCP 刻意只收 analyze/curate；向外部 Harness 要 mine 计划（确认后提交），或用 Python API |

**LLM 端点与智能体**（接入教程与完整排查表见安装指南 §5）

| 现象 | 原因与处理 |
|---|---|
| `payload D4 exceeds cloud limit` | 数据分级拦截（ADR-16）；任务内智能体与 `cloud` MCP 实例都会自动裁剪工具带，不应再出现——出现请先升级版本 |
| 401 / 429(1113) / 模型不存在 | 密钥未注入、密钥与端点不匹配（GLM 通用端点 vs coding 端点）、账户无该模型额度——见安装指南 §5.2 |
| 「LLM 不可用 / degraded」 | 统一降级提示；用 `bacmap overview` 看端点状态（确定性功能照常可用，C3） |
| 想让对话有流式输出 | 对话在 Harness 里（ADR-21）；bacmap 只经 `/api/v1/events/stream` 推送领域事件 |
| 智能体说「安全问题无法读取」路径数据 | 设计行为：外部数据走 mine 登记（§2「给 mine 任务一份数据路径」）；若任务报「沙箱不可用」装 podman（安装指南 §6） |
| mine 任务失败、消息只剩「workflow ERROR」 | 旧版环境级异常被吞成笼统消息；现任务消息会指出原因与方向（如「沙箱启动失败：no apptainer/podman on PATH → 安装 podman」）——升级后重提任务即可 |

**样本与数据**

| 现象 | 原因与处理 |
|---|---|
| analyze 找不到 FASTQ | 样本未注册：按 `gs/<ID>/<ID>_R{1,2}.fastq.gz` 布局或登记 samples.tsv（§7、配置指南 §5）；**已组装 FASTA 可登记 `assembly` 列直入封闭路径**（v1.4.33，跳过 QC/组装） |
| 登记过的数据集读不到 | 原文件被移动/删除（零拷贝登记依赖原路径）；`bio_inspect_dataset verify=true` 可检测 |
| 任务停在「待审批」 | 正常：挖掘门/发布门等人工签字，详情页审批卡操作（§4） |
