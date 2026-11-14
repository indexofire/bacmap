# HTTP API（`/api/v1`）

Web 服务器在与 HTML 控制台相同的鉴权之下暴露一个带版本号的 JSON API。它是
**可信操作员界面**：持有 token 的人可以提交、取消、确认与审批。不要把
Web token 交给外部智能体；智能体使用 MCP。

## 1. 鉴权

### Bearer 模式（默认）

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap start web --host 127.0.0.1 --port 8800
curl -H "Authorization: Bearer $BACMAP_WEB_TOKEN" http://127.0.0.1:8800/api/v1/tasks
```

### Cookie 模式

```bash
export BACMAP_WEB_AUTH=cookie
bacmap start web
# 浏览器：/login → 签名会话 cookie + bacmap_csrf cookie
```

此后，改变状态的请求需要：

```http
X-CSRF-Token: <value of the bacmap_csrf cookie>
Origin: http://127.0.0.1:8800
```

## 2. 端点

| 方法 | 路径 | 用途 |
|---|---|---|
所有列表接口接受 `offset`/`limit`（`/search/identity` 使用 specimen/isolate 各自的 offset），返回 `{items, total, offset, limit}`；`/samples` 保留 cursor 模式兼容，控制台使用 offset。`/tasks` 支持 `task_type`，`/gom/objects` 支持 `type`。

| GET | `/api/v1/capabilities` | API 版本、bacmap 版本、可计划类型、特性 |
| GET | `/api/v1/auth/status` | 鉴权模式、登录状态与操作员指纹（公开） |
| POST | `/api/v1/auth/login` | 用部署令牌换取签名会话 cookie（公开；仅 cookie 模式） |
| POST | `/api/v1/auth/logout` | 清除会话与 CSRF cookie（需 CSRF） |
| GET | `/api/v1/overview` | 系统概览（版本、路径、数据策略、沙箱、任务计数） |
| GET | `/api/v1/stats` | 数据库统计（任务/运行/GOM/菌株/血清型/MLST/AMR/研究/知识库） |
| GET | `/api/v1/samples?cursor=&limit=` | 已完成样本分页（仅解析当前页） |
| GET | `/api/v1/samples/{id}` | 样本 digest + 完整 steps + 报告就绪标记 + gvixb 最新结果入口 |
| GET | `/api/v1/specimens?limit=` | 样本列表（含菌株数） |
| GET | `/api/v1/specimens/{id}` | 样本 + 菌株 + 各菌株的测序数据 |
| GET | `/api/v1/isolates?limit=` | 菌株列表（样本归属、测序数据数） |
| GET | `/api/v1/isolates/{id}` | 菌株 + 所属样本 + 测序数据 |
| POST | `/api/v1/specimens/assign` | 把菌株/测序数据关联到样本（CSRF；样本不存在则创建） |
| POST | `/api/v1/specimens/{id}/delete` | 删除样本（`force: true` 先解除菌株关联；菌株/数据保留） |
| GET | `/api/v1/search?q=&serotype=&mlst_st=&amr_gene=` | 按关键词/血清型/ST/基因检索样本 |
| GET | `/api/v1/search/identity?q=` | 统一检索：样本与菌株 |
| GET | `/api/v1/tasks?limit=` | 最近的任务 |
| POST | `/api/v1/tasks` | 提交 analyze/curate（`task_type`、`samples`、`scope`） |
| GET | `/api/v1/tasks/{id}` | 任务状态与元数据 |
| POST | `/api/v1/tasks/{id}/approve` | 审批签名（`approver`、`decision`、`signature`、`comment?`） |
| POST | `/api/v1/tasks/{id}/cancel` | 取消非终态任务 |
| POST | `/api/v1/tasks/{id}/pause` | 暂停运行中任务（中断的工作流可续跑） |
| POST | `/api/v1/tasks/{id}/resume` | 在同一 run 目录恢复 `paused`/`failed(interrupted)`/`cancelled` 任务 |
| POST | `/api/v1/records/{kind}` | 记录任务（`metadata`/`lab`/`knowledge-import`/`knowledge-approve`） |
| GET | `/api/v1/plans?limit=` | 每个计划的最新版本 |
| GET | `/api/v1/plans/{id}?version=` | 计划详情 |
| POST | `/api/v1/plans/{id}/confirm` | 确认 + 提交 |
| POST | `/api/v1/plans/{id}/reject` | 拒绝 |
| GET | `/api/v1/events?after=&limit=&task_id=&plan_id=` | 事件轮询（`last_seq` 分页游标 + `max_seq` SSE 起点） |
| GET | `/api/v1/events/stream?after=&timeout=` | SSE 流（从 `Last-Event-ID` 续传） |
| GET | `/api/v1/runs?limit=` | 运行记录 |
| GET | `/api/v1/runs/{id}` | 运行详情 + gvixb 视图 |
| GET | `/api/v1/runs/{id}/compare?other=` | 来源比较 |
| GET | `/api/v1/gom/objects?type=&limit=` | 最新的 GOM 对象 |
| GET | `/api/v1/gom/objects/{id}?version=` | GOM 对象 + 关联 gvixb 视图 |
| GET | `/api/v1/gvixb/runs/{run_id}/manifest` | 某运行可用的 gvixb 视图 |
| GET | `/api/v1/gvixb/runs/{run_id}/genome/{dataset}` | 历史运行 draft assembly 数据 |
| GET | `/api/v1/gvixb/samples/{dataset}/genome` | 最新结果 draft assembly 数据 |
| GET | `/api/v1/gvixb/runs/{run_id}/annotated-genome/{dataset}` | 历史运行 Bakta/eggNOG 圈图数据 |
| GET | `/api/v1/gvixb/samples/{dataset}/annotated-genome` | 最新结果圈图数据 |
| GET | `/api/v1/gvixb/runs/{run_id}/tree/{snp\|cgmlst}/{group}` | 进化树数据 |
| GET | `/api/v1/gvixb/runs/{run_id}/mst/{group}` | gmlst 原始 MST 数据 |

## 3. 示例

### Capabilities

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/capabilities | jq .
```

### 轮询任务

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/tasks?limit=20" | jq '.items[] | {task_id,state,current_step}'

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/tasks/3f9c2a1b | jq .
```

### 提交与审批任务

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task_type":"analyze","samples":["SAM-TYP-001"]}' \
  http://127.0.0.1:8800/api/v1/tasks | jq '{task_id,state}'

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"approver":"jane","decision":"approve","signature":"jd-2026-11-09"}' \
  http://127.0.0.1:8800/api/v1/tasks/<task_id>/approve | jq '{state,message}'
```

### 检索与概览

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/search?q=Salmonella&mlst_st=11" | jq '.items[] | {sample_id,verdict,st}'
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/overview | jq '{sandbox,versions,cloud_max_data_class}'
```

### 确认计划（bearer 模式）

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version":1,"plan_hash":"c1d2e3f4a5b6","confirmer":"jane"}' \
  http://127.0.0.1:8800/api/v1/plans/9a3f2c1b7d4e4f60/confirm | jq .
```

Cookie 模式还需加上 `-H "X-CSRF-Token: $CSRF"` 与 cookie jar。

### 拒绝计划

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"version":1,"reason":"wrong sample"}' \
  http://127.0.0.1:8800/api/v1/plans/9a3f2c1b7d4e4f60/reject
```

### 事件与 SSE

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/events?after=120" | jq .

curl -N -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/events/stream?after=120"
```

SSE 帧使用 `id: <seq>`、`event: <type>`、`data: <json>`。用 `Last-Event-ID` 或
`after=` 重连。空闲时会发送 keepalive 注释。

### 运行比较

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/runs/<run_a>/compare?other=<run_b>" | jq .
```

### gvixb manifest

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/gvixb/runs/<run_id>/manifest | jq .
```

返回 `circle:<dataset>` 表示该样本存在 Bakta/eggNOG sidecar 布局。完整目录契约、浏览器 URL 和
故障排查见 [gvixb 3D 可视化](../guide/visualization.zh.md)。

## 4. 错误

```json
{"code": "validation_error", "error": "..."}
{"code": "not_found", "error": "..."}
{"code": "conflict", "error": "..."}
```

| 错误码 | HTTP |
|---|---|
| `validation_error` | 400 |
| `not_found` | 404 |
| `conflict` | 409 |

鉴权失败为 401；CSRF 失败为 403。API 返回 JSON，而不是 HTML。

## 5. 说明

- `limit` 会被截断（tasks/plans 200，GOM 500，runs 200）。
- 事件是协作辅助手段，不是真相；断开连接后，请重新读取任务/计划。
- 计划是带版本的；务必确认你审阅过的 `(version, plan_hash)`。
- 在智能体集成中，API 不能替代 MCP。
