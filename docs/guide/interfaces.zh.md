# 界面：Web、CLI、TUI 与 JSON API

四种界面共用同一套任务引擎、门和审计轨迹。按当下场景选择即可；你可以在一个界面里启动任务，
在另一个界面里审批它。

## 1. Web 控制台

默认界面是 **Vue 3 控制台**（`/console/`，Vite 构建，暗色仪器式仪表盘）；`/` 会重定向到
这里。旧 Jinja 任务台已移除：旧路径（`/tasks`、`/plans`、`/samples`、`/gom` 等）会 307
重定向到对应的 `/console/...`。SPA 以预构建静态资源提供：运行期不需要 Node/Bun
（ADR-01）；Node 只在重新构建前端时使用。

控制台提供 **dark / light 两套主题**：右上角月亮/太阳按钮即时切换，选择写入
`localStorage`（`bacmap-theme`），刷新后保持；浅色模板采用 TailAdmin 风格的浅灰画布、
白色卡片、细边框与柔和阴影，图表配色同步切换。样本 HTML 报告也支持浅色渲染
（`?theme=light`），控制台切到浅色后报告页签会同步。

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
| `/samples/{id}/report` | 报告 HTML 源（`?embed=1` 内嵌）；直接访问 307 到 `/console/samples/{id}?tab=report`，`?download=1` 改为附件，`?theme=light` 浅色渲染 |
| `/api/v1/*` | JSON API（见 [HTTP API 参考](../reference/api.zh.md)） |

样本详情页提供“概览 / 完整报告”两个页签，报告在页签内的沙箱 iframe 中渲染，不另开页面。
旧模板生成的报告（无 `bacmap-report` 版本标记）会在首次访问时自动重渲染为暗色主题。
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

如果绑定非回环地址，bacmap 在缺少令牌时会拒绝启动：

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap start web --host 0.0.0.0 --port 8800
```

两种鉴权模式：

- `bearer`（默认）：API 客户端发送 `Authorization: Bearer <token>`；浏览器无法设置该请求头，
  因此 HTML 控制台会返回一段简短的 401 说明（请改用 SSH 隧道）。
- `cookie`：设置 `BACMAP_WEB_AUTH=cookie`；在 `/login` 登录；会话 cookie 经过签名且为
  `HttpOnly`，每个改变状态的 POST 都需要 CSRF 令牌。在 TLS 之后请再加上
  `BACMAP_WEB_COOKIE_SECURE=1`。

MCP 的 HTTP 传输是独立的：它始终要求 `BACMAP_MCP_TOKEN`（或 `--token-env`），相关内容见
[智能体与计划](agent-plans.zh.md)。
