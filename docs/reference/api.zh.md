# HTTP API（`/api/v1`）

Web 服务器在与 HTML 控制台相同的鉴权之下暴露一个带版本号的 JSON API。它是
**可信操作员界面**：持有 token 的人可以提交、取消、确认与审批。不要把
Web token 交给外部智能体；智能体使用 MCP。

## 1. 鉴权

### Bearer 模式（默认）

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap web --host 127.0.0.1 --port 8800
curl -H "Authorization: Bearer $BACMAP_WEB_TOKEN" http://127.0.0.1:8800/api/v1/tasks
```

### Cookie 模式

```bash
export BACMAP_WEB_AUTH=cookie
bacmap web
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
| GET | `/api/v1/capabilities` | API 版本、bacmap 版本、可计划类型、特性 |
| GET | `/api/v1/samples?cursor=&limit=` | 已完成样本分页（仅解析当前页） |
| GET | `/api/v1/tasks?limit=` | 最近的任务 |
| GET | `/api/v1/tasks/{id}` | 任务状态 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消非终态任务 |
| GET | `/api/v1/plans?limit=` | 每个计划的最新版本 |
| GET | `/api/v1/plans/{id}?version=` | 计划详情 |
| POST | `/api/v1/plans/{id}/confirm` | 确认 + 提交 |
| POST | `/api/v1/plans/{id}/reject` | 拒绝 |
| GET | `/api/v1/events?after=&limit=&task_id=&plan_id=` | 事件轮询 |
| GET | `/api/v1/events/stream?after=&timeout=` | SSE 流（从 `Last-Event-ID` 续传） |
| GET | `/api/v1/runs?limit=` | 运行记录 |
| GET | `/api/v1/runs/{id}` | 运行详情 |
| GET | `/api/v1/runs/{id}/compare?other=` | 来源比较 |
| GET | `/api/v1/gom/objects?type=&limit=` | 最新的 GOM 对象 |
| GET | `/api/v1/gom/objects/{id}?version=` | GOM 对象 |

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
