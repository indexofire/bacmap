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

### Cookie 模式（单令牌）

```bash
export BACMAP_WEB_AUTH=cookie
bacmap start web
# 浏览器：/login → 签名会话 cookie + bacmap_csrf cookie
```

### 个人模式（访问密钥）

```bash
bacmap personal init                    # 只显示一次 bk_…
export BACMAP_WEB_AUTH=personal
bacmap start web
# 浏览器 /console/login → 访问密钥
# 脚本/API：仍可用部署令牌 Authorization: Bearer <BACMAP_WEB_TOKEN>
```

访问密钥以 scrypt 哈希保存在 `$BACMAP_HOME/personal.json`（0600）；登录后是内置
`owner`（admin，全功能）的服务端会话。

### 本地账号模式

```bash
bacmap user create admin --role admin   # 本机 shell，首个管理员
export BACMAP_WEB_AUTH=accounts
bacmap start web
# 浏览器 /console/login → 用户名 + 密码
# 脚本/API 客户端：bacmap user token create alice → Authorization: Bearer bm_...
```

admin/analyst/user 的权限与数据可见范围见
[多用户与角色](../concepts/accounts.zh.md)。普通用户只能读取自己提交/归属的
任务、计划、样本与结果。

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
| POST | `/api/v1/auth/login` | 单令牌：部署令牌换 cookie；accounts：用户名/密码；personal：访问密钥换服务端会话（公开） |
| POST | `/api/v1/auth/logout` | 撤销服务端会话并清除 cookie（需 CSRF） |
| GET/POST | `/api/v1/users` | 用户列表/创建（`user.manage`，admin；写操作需 CSRF） |
| PATCH | `/api/v1/users/{id}/role`、`/disabled` | 改角色/停用（admin；需 CSRF） |
| POST | `/api/v1/users/{id}/password` | 重置密码并撤销旧会话（admin；需 CSRF） |
| GET/POST/DELETE | `/api/v1/users/{id}/tokens` | 个人 API 令牌管理（admin；明文只返回一次） |
| POST | `/api/v1/imports` | 上传湿实验 XLSX/CSV/TSV，生成 `pending_review` 提案（`import.submit`；multipart） |
| GET | `/api/v1/imports?status=&kind=&offset=&limit=` | 提案列表（`kind=import|edit`）；普通用户只看自己的 |
| GET | `/api/v1/imports/{id}` | 提案摘要/错误/审核状态（不返回文件路径与数据行） |
| GET | `/api/v1/imports/{id}/preview?limit=20` | 前 N 行预览（仅授权用户/审核者；D4 本地） |
| POST | `/api/v1/imports/{id}/advise` | AI 映射建议（只读；需 CSRF；仅 pending_review） |
| POST | `/api/v1/imports/{id}/approve` | analyst/admin 审核文件导入或修改提案并提交 record 任务（`import.review`；需 CSRF） |
| POST | `/api/v1/imports/{id}/reject?note=` | 拒绝提案（`import.review`；需 CSRF） |
| POST | `/api/v1/imports/{id}/withdraw` | 提交人撤回 pending 提案（需 CSRF） |
| POST | `/api/v1/wetlab/proposals` | 普通用户提交修改/删除/新建/关联提案（`import.submit`；同一目标同操作只允许一个 pending） |
| POST | `/api/v1/wetlab/specimens` | 新建样本（analyst/admin；`record` 任务；需 CSRF） |
| POST | `/api/v1/wetlab/isolates` | 新建菌株（analyst/admin；`record` 任务；需 CSRF） |
| POST | `/api/v1/wetlab/specimens/{id}/metadata` | 保存样本湿实验字段（`record.write`；默认全量替换；需 CSRF） |
| POST | `/api/v1/wetlab/specimens/{id}/metadata/delete` | 删除样本湿实验字段（不删样本实体；需 CSRF） |
| POST | `/api/v1/wetlab/specimens/{id}/assign` | 关联菌株/测序数据到样本（`specimen_assign` record 任务；需 CSRF） |
| POST | `/api/v1/wetlab/isolates/{id}/metadata` | 保存菌株湿实验字段（已知列 + `extra`；需 CSRF） |
| POST | `/api/v1/wetlab/isolates/{id}/metadata/delete` | 删除菌株湿实验字段（不删菌株；需 CSRF） |
| POST | `/api/v1/wetlab/libraries/{id}/metadata` | 保存测序数据附加元数据（需 CSRF） |
| POST | `/api/v1/wetlab/libraries/{id}/metadata/delete` | 删除测序数据附加元数据（不影响测序文件；需 CSRF） |
| POST | `/api/v1/wetlab/lab` | 新增化验结果（isolate/specimen 主体；需 CSRF） |
| POST | `/api/v1/wetlab/lab/{id}` | 部分更新化验结果（需 CSRF） |
| POST | `/api/v1/wetlab/lab/{id}/delete` | 删除化验结果（需 CSRF） |
| GET | `/api/v1/overview` | 系统概览（版本、路径、数据策略、沙箱、任务计数） |
| GET | `/api/v1/stats` | 数据库统计（任务/运行/GOM/菌株/血清型/MLST/AMR/研究/知识库） |
| GET | `/api/v1/samples?offset=&limit=&q=&species=&st=&serotype=&amr_gene=` | 结果索引分页/检索（`sort=sample_id|species|st|serovar|genome_size|contigs|gc_pct|n_card|n_vfdb|n_plasmid|analysis_date`） |
| GET | `/api/v1/species` | 物种聚合（基因组/样本/菌株数、最近分析） |
| GET | `/api/v1/samples/{id}` | 样本 digest + 完整 steps + 报告就绪标记 + gvixb 最新结果入口 |
| GET | `/api/v1/specimens?offset=&limit=&q=` | 样本列表（含物种、菌株数、结果数） |
| GET | `/api/v1/specimens/{id}` | 样本 + 菌株 + 各菌株的测序数据 + 样本级湿实验元数据/化验 |
| GET | `/api/v1/isolates?offset=&limit=&q=` | 菌株列表（物种/ST/血清型/结果数） |
| GET | `/api/v1/isolates/{id}` | 菌株 + 所属样本 + 测序数据（含 library 元数据） |
| POST | `/api/v1/specimens/assign` | 把菌株/测序数据关联到样本（CSRF；样本不存在则创建） |
| POST | `/api/v1/specimens/{id}/delete` | 删除样本（`force: true` 先解除菌株关联；菌株/数据保留） |
| POST | `/api/v1/isolates/{id}/delete` | 删除空菌株（有测序数据/元数据/化验/GOM/运行记录时 409 拒绝） |
| GET | `/api/v1/search?q=&serotype=&mlst_st=&amr_gene=` | 按关键词/血清型/ST/基因检索样本 |
| GET | `/api/v1/search/identity?q=` | 统一检索：样本与菌株 |
| GET | `/api/v1/tasks?limit=` | 最近的任务 |
| POST | `/api/v1/tasks` | 提交 analyze/curate（`task_type`、`samples`、`scope`） |
| GET | `/api/v1/tasks/{id}` | 任务状态与元数据 |
| POST | `/api/v1/tasks/{id}/approve` | 审批签名（accounts 模式由登录主体认定 approver） |
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
| POST | `/api/v1/runs/{id}/purge` | 清理运行的物理产物（保留记录/GOM；运行中或最新 run 返回 409） |
| GET | `/api/v1/gom/objects?type=&limit=` | 最新的 GOM 对象 |
| GET | `/api/v1/gom/objects/{id}?version=` | GOM 对象 + 关联 gvixb 视图 |
| GET | `/api/v1/gvixb/runs/{run_id}/manifest` | 某运行可用的 gvixb 视图 |
| GET | `/api/v1/gvixb/runs/{run_id}/genome/{dataset}` | 历史运行 draft assembly 数据 |
| GET | `/api/v1/gvixb/samples/{dataset}/genome` | 最新结果 draft assembly 数据 |
| GET | `/api/v1/gvixb/runs/{run_id}/annotated-genome/{dataset}` | 历史运行 Bakta/eggNOG 圈图数据 |
| GET | `/api/v1/gvixb/samples/{dataset}/annotated-genome` | 最新结果圈图数据 |
| GET | `/api/v1/gvixb/runs/{run_id}/tree/{snp}/{group}` | SNP 进化树载荷（`gvixb.phylogeny/v2`）；`cgmlst` 返回 410（请改用 MST 端点——cgMLST 的 Newick 是 MST 序列化结果，并非系统发育树） |
| GET | `/api/v1/gvixb/runs/{run_id}/mst/{group}` | gmlst MST 数据（由 `cgmlst_profiles.tsv` 补充位点名与样本 ST/scheme 元数据） |

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
