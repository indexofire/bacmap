# 界面：Web、CLI、TUI 与 JSON API

四种界面共用同一套任务引擎、门和审计轨迹。按当下场景选择即可；你可以在一个界面里启动任务，
在另一个界面里审批它。

## 1. Web 控制台

默认界面是 **Vue 3 控制台**（`/console/`，Vite 构建，暗色仪器式仪表盘）；`/` 会重定向到
这里。旧 Jinja 任务台已移除：旧路径（`/tasks`、`/plans`、`/samples`、`/gom` 等）会 307
重定向到对应的 `/console/...`。SPA 以预构建静态资源提供：运行期不需要 Node/Bun
（ADR-01）；Node 只在重新构建前端时使用。

控制台提供 **INK / PAPER / CONCRETE 三套主题**：右上角主题菜单即时切换，选择写入
`localStorage`（`bacmap-theme`），刷新后保持。INK 为暗色仪器台，PAPER 为 TailAdmin
风格浅色文档，CONCRETE 为 Swiss/brutalist 灰色模板（网格纸、硬边框、Helvetica 大标题、
等宽数据与分屏海报式首页）。图表与样本 HTML 报告同步主题（`?theme=light|gray`）。

```bash
bacmap start web                            # 默认 127.0.0.1:8800
bacmap start web --host 127.0.0.1 --port 8800

# 前端改动后重新构建（仅开发期）
pixi run -e web web-install
pixi run -e web web-build
```

控制台路由：

| 路由 | 用途 |
|---|---|
| `/console/` | 仪表盘：KPI、7 天趋势、状态分布、待审批 |
| `/console/tasks` | 任务列表、筛选与提交抽屉（analyze/curate） |
| `/console/tasks/{id}` | 任务详情、事件时间线、审批卡、取消 |
| `/console/plans`、`/console/plans/{id}` | 智能体提出的计划、完整参数、确认/拒绝 |
| `/console/samples`、`/console/samples/{id}` | 已完成样本、单样本结果/注释与内嵌“完整报告”页签 |
| `/console/runs`、`/console/runs/{id}` | 不可变运行记录与来源比较 |
| `/console/records` | 元数据、化验结果、知识导入/审核表单 |
| `/console/gom`、`/console/gom/{id}` | GOM 对象、不可变版本与载荷 |
| `/console/research` | 研究会话与 Study/Cohort/Plan/Claim 总览 |
| `/console/research/sessions/{id}` | 研究统计、图、产物与证据链 |
| `/console/research/studies/{id}` | Study、Cohort、Plan、Claim（只读） |
| `/console/overview` | 系统概览（版本、路径、数据策略、沙箱） |
| `/console/search` | 按关键词/血清型/ST/基因检索样本 |
| `/research` | 高级研究工具（系统发育、logistic、对象写操作；Jinja） |
| `/samples/{id}/report` | 报告 HTML 源（`?embed=1` 内嵌）；直接访问 307 到 `/console/samples/{id}?tab=report`，`?download=1` 改为附件，`?theme=light|gray` 浅色/灰色渲染 |
| `/api/v1/*` | JSON API（见 [HTTP API 参考](../reference/api.zh.md)） |

样本详情页提供“概览 / 完整报告”两个页签，报告在页签内的沙箱 iframe 中渲染，不另开页面。
旧模板生成的报告（无 `bacmap-report` 版本标记）会在首次访问时自动重渲染为当前主题。

报告内容包含：KPI 摘要、AMR 类别分布与高置信基因条形图、VFDB 毒力基因、质粒复制子、
Bakta/eggNOG 注释与 COG 功能分类（有注释数据时），完整基因表可折叠展开。
**AI 解读**：外部 Harness/分析师读取 summary 后生成 `interpretation_text`，调用
`bio_verify_result` 并传入该文本；NLI Reflector 会做事实一致性自检并持久化，报告展示
“AI 解读与 NLI 自检”（通过或需人工审核）。没有 LLM 时报告只显示确定性结果，不伪造解读。
仪表盘对 `/api/v1/stats` 失败做降级：任务区照常加载，数据库统计显示不可用提示而不是全 0。

任务详情页在非终态时每两秒轮询 `/api/v1/tasks/{id}`。所有资源（CSS、JS、图标、favicon）
均为本地文件；不使用 CDN 或 webfont（可离线使用）。

### 提交任务

表单接受**已登记的数据集 ID**，用半角逗号或换行分隔：

```text
SAM-TYP-001, SAM-TYP-002
```

路径和自然语言请求会被拒绝。对 `curate` 而言，可选的 `scope` 是一个 JSON 对象：

```json
{"pathogen": "Salmonella", "strains": ["HZCPE-01"]}
```

`mine`/`write` 请使用（来自智能体的）计划；表单刻意只暴露 `analyze` 和 `curate`。

### 审批

当任务进入 `awaiting_approval`，详情页会显示一张审批卡。审批人姓名、决定与签名记入
`approvals` 表，并作为事件发出。签字属于仅限人执行的操作；智能体无法执行。

## 2. CLI

```bash
bacmap --version
bacmap overview [--json]
bacmap doctor [--json]
bacmap task list|show|submit|approve|cancel
bacmap plan list|show|confirm|reject
bacmap record metadata|lab|knowledge-import|knowledge-approve
bacmap run list|show|compare
bacmap gom list|show
bacmap isolate list|show
bacmap sample ls|show
bacmap search [--query ...] [--serotype ...] [--st ...] [--gene ...]
bacmap results migrate [--dry-run]
bacmap events prune --days N
bacmap backup --out FILE [--with-results]
bacmap restore --from FILE [--force]
bacmap start mcp     # MCP server
bacmap start web     # Web console
bacmap start tui     # task console
bacmap start console  # numbered menu
```

查询类命令接受 `--json`；任务/计划 ID 支持唯一前缀，因此 `task list` 显示的 12 个字符可直接使用。

### 提交并跟踪一次分析

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
# => task_id

bacmap task list
bacmap task show 3f9c2a1b
bacmap task show 3f9c2a1b --json | jq .state
```

登记一个目录，而不是手工编辑 samples.tsv：

```bash
bacmap task submit --type analyze --fasta-dir /data/genomes
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

### 整理本地基线

```bash
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task show <task_id>          # ends in awaiting_approval
bacmap task approve <task_id> \
  --approver "Jane Doe" --decision approve --signature "jd-2026-10-30"
```

### 确认智能体计划

```bash
bacmap plan list
bacmap plan show <plan_id>                 # full tasks, hash, input fingerprints
bacmap plan confirm <plan_id> --version 1 --hash <first 12+ chars>
bacmap plan reject <plan_id> --version 1 --reason "wrong sample"
```

如果省略 `--hash`，`plan confirm` 会先打印计划再交互询问；脚本应显式传入哈希。

### 记录

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L --interpretation S
bacmap record knowledge-import --title "O3:K6 outbreak" --identifier PMID:12345678
bacmap record knowledge-approve 7
```

每条命令都会提交一个 `record` 任务；用 `bacmap task show` 查看结果。

### 退出码与 JSON

- `0` 成功，`1` 检查未通过 / 操作失败，`2` 参数错误（argparse）。
- `--json` 只打印一个 JSON 文档；诊断信息写到 stderr。
- 仅当某项检查的状态为 `fail` 时，`bacmap doctor` 才以 `1` 退出。

## 3. TUI 任务台

```bash
bacmap start tui
```

TUI 是一个仪表盘加显式操作的界面；**没有对话**。

| 按键 | 操作 |
|---|---|
| `Enter` | 执行当前斜杠命令 |
| `Esc` | 取消待签批的审批 / 聚焦输入框 |
| `Ctrl+B` | 切换侧栏 |
| `Ctrl+R` | 刷新 |
| `Ctrl+L` | 清空日志 |
| `Ctrl+Y` | 确认待执行的签名 |
| `Ctrl+G` 再按 `i/l/s/m/t/a/h/q` | 聚焦输入框 / 任务 / 样本 / 端点 / 主题 / 审批 / 帮助 / 退出 |

斜杠命令：

```text
/help
/clear
/tasks
/samples
/search <keyword>
/model
/result <sample>
/approve <task-id> [signature]
/analyze <sample>
/curate [scope-json]
/quit
```

`/approve` 需要两步确认：提示栏会显示任务与签名；`Ctrl+Y` 提交，`Esc` 取消。

## 4. 交互式控制台

```bash
bacmap start console
```

为偏爱提示式操作而非子命令的用户准备的编号菜单。它使用同一套引擎与门；不是另一套实现。

## 5. JSON API（`/api/v1`）

Web 服务器在同一鉴权之下还提供版本化的 JSON API。它是**可信操作员界面**：持有 Web 令牌的人
即可审批与确认。切勿把该令牌交给外部 Harness —— Harness 使用 MCP。

```bash
TOKEN=...                         # BACMAP_WEB_TOKEN
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/tasks | jq .

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version":1,"plan_hash":"c1d2e3f4a5b6...","confirmer":"jane"}' \
  http://127.0.0.1:8800/api/v1/plans/<plan_id>/confirm
```

完整的端点与错误参考：[HTTP API](../reference/api.zh.md)。

## 6. 远程访问与鉴权

`bacmap start web` 默认绑定 `127.0.0.1`。需要远程访问时，请使用 SSH 隧道：

```bash
ssh -L 8800:127.0.0.1:8800 user@workstation
# then open http://127.0.0.1:8800 locally
```

后台运行控制台（不随终端退出），使用守护进程模式：

### 内嵌本机智能体对话（DSH / Hermes / opencode）

不必同时开 bacmap 与智能体两个窗口——把智能体自己的 web UI 嵌成控制台
侧边栏页面（仅限回环地址，ADR-16；云托管前端不可嵌入）：

```toml
# config.toml
[[web.agent_embed]]
name = "DSH"
url = "http://127.0.0.1:3080/?token=<dsh-browser-trust-token>"

[[web.agent_embed]]
name = "Hermes"
url = "http://127.0.0.1:56791"      # hermes dashboard

[[web.agent_embed]]
name = "opencode"
url = "http://127.0.0.1:49374"      # opencode serve
```

重启 `bacmap start web` 后侧边栏出现"智能体对话"分组，每条配置一个页面
（`/agent/<n>`）。配置的 origin 会自动加入 Web CSP 的 `frame-src` 白名单；
非回环条目直接跳过。已实测：DSH（需把 browser-trust token 写进 URL）、
Hermes Dashboard、`opencode serve` 三端可嵌；Pi 为纯 TUI（无 web 面可嵌）。

```bash
bacmap start web -D            # 或 --daemon
# PID 文件：$BACMAP_HOME/web.pid · 日志：$BACMAP_HOME/web.log
bacmap stop                    # 优雅停止（SIGTERM，超时后 SIGKILL）
bacmap restart                 # 停止后按上次启动参数重新拉起
```

守护进程已在运行时再次启动会被拒绝（陈旧 PID 文件自动放行）。
`bacmap restart` 复用上次守护启动记录的 host/port/token-env；可用 `--host`/`--port`/`--token-env` 覆盖。

如果绑定非回环地址，bacmap 在缺少令牌时会拒绝启动：

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap start web --host 0.0.0.0 --port 8800
```

控制台只响应 `Host` 为回环名、绑定地址（`0.0.0.0`/`::` 时为本机主机名）或列在
`BACMAP_WEB_ALLOWED_HOSTS`（逗号分隔）中的请求，其余返回 `400`。请把浏览器访问用的局域网
IP/域名或反向代理转发的主机名加进去：

```bash
export BACMAP_WEB_ALLOWED_HOSTS=192.168.1.20,bacmap.lab.example
```

两种鉴权模式：

- `bearer`（默认）：API 客户端发送 `Authorization: Bearer <token>`；浏览器无法设置该请求头，
  因此 HTML 控制台会返回一段简短的 401 说明（请改用 SSH 隧道）。
- `cookie`：设置 `BACMAP_WEB_AUTH=cookie`；在 `/login` 登录；会话 cookie 经过签名且为
  `HttpOnly`，每个改变状态的 POST 都需要 CSRF 令牌。在 TLS 之后请再加上
  `BACMAP_WEB_COOKIE_SECURE=1`。

MCP 的 HTTP 传输是独立的：它始终要求 `BACMAP_MCP_TOKEN`（或 `--token-env`），相关内容见
[智能体与计划](agent-plans.zh.md)。
