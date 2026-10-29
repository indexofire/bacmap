# 界面：Web、CLI、TUI 与 JSON API

四种界面共用同一套任务引擎、门和审计轨迹。按当下场景选择即可；你可以在一个界面里启动任务，
在另一个界面里审批它。

## 1. Web 控制台

```bash
bacmap web                                  # 127.0.0.1:8800 by default
bacmap web --host 127.0.0.1 --port 8800
```

页面：

| 路由 | 用途 |
|---|---|
| `/` | 任务列表与提交表单（analyze/curate） |
| `/tasks/{id}` | 任务详情、实时状态片段、审批卡 |
| `/plans`、`/plans/{id}` | 智能体提出的计划、完整参数、确认/拒绝 |
| `/samples`、`/samples/{id}` | 已完成的样本、单样本检出结果 |
| `/samples/{id}/report` | 内联 HTML 报告（加 `?download=1` 改为附件下载） |
| `/search` | 按关键词/血清型/ST/基因检索 |
| `/records` | 元数据、化验结果和知识库条目的录入表单 |
| `/runs`、`/gom` | 不可变的运行记录与 GOM 对象 |
| `/overview` | 系统概览（版本、路径、数据策略、沙箱） |
| `/api/v1/*` | JSON API（见 [HTTP API 参考](../reference/api.zh.md)） |

任务详情页每两秒轮询一次 `/tasks/{id}/fragment`；不使用外部 JavaScript 或 CDN（可离线使用）。

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
bacmap mcp   # MCP server
bacmap web   # Web console
bacmap tui   # task console
bacmap console  # numbered menu
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
bacmap tui
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
bacmap console
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

`bacmap web` 默认绑定 `127.0.0.1`。需要远程访问时，请使用 SSH 隧道：

```bash
ssh -L 8800:127.0.0.1:8800 user@workstation
# then open http://127.0.0.1:8800 locally
```

如果绑定非回环地址，bacmap 在缺少令牌时会拒绝启动：

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap web --host 0.0.0.0 --port 8800
```

两种鉴权模式：

- `bearer`（默认）：API 客户端发送 `Authorization: Bearer <token>`；浏览器无法设置该请求头，
  因此 HTML 控制台会返回一段简短的 401 说明（请改用 SSH 隧道）。
- `cookie`：设置 `BACMAP_WEB_AUTH=cookie`；在 `/login` 登录；会话 cookie 经过签名且为
  `HttpOnly`，每个改变状态的 POST 都需要 CSRF 令牌。在 TLS 之后请再加上
  `BACMAP_WEB_COOKIE_SECURE=1`。

MCP 的 HTTP 传输是独立的：它始终要求 `BACMAP_MCP_TOKEN`（或 `--token-env`），相关内容见
[智能体与计划](agent-plans.zh.md)。
