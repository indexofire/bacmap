# MCP 参考

bacmap 运行一个 MCP 服务器，支持 stdio（默认）或 Streamable HTTP。客户端启动该进程，
并获得工具、提示词与资源。对话与模型选择由客户端负责；bacmap 只暴露领域工具与人工确认边界。

## 1. 传输与鉴权

| 传输 | 命令 | 鉴权 |
|---|---|---|
| stdio | `bacmap mcp` | 操作系统进程边界；actor 为 `mcp-stdio:<profile>:<user>` |
| HTTP | `bacmap mcp --transport http --host 127.0.0.1 --port 8765` | 强制 bearer token |
| unix socket | `bacmap mcp --transport http --uds /run/bacmap-mcp.sock` | 强制 bearer token |

```bash
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
# 客户端：http://127.0.0.1:8765/mcp，Authorization: Bearer <token>
```

HTTP 在没有 token 时拒绝启动。DNS 重绑定防护只允许已配置的主机
（默认回环）。

`--read-only` 移除任务/计划/记录的写工具；只保留读/计算与 capabilities。

## 2. Profile

每个服务实例一个 Profile，启动时固定：

```bash
bacmap mcp                          # cloud（默认）
bacmap mcp --profile local-trusted  # 要求 [mcp] allow_local_trusted = true
```

| Profile | 工具输出上限 | 任务消息 | 任务结果 |
|---|---|---|---|
| `cloud` | `[llm.data_policy].cloud_max_data_class`（默认 D1，最大 D2） | 不下发 | 门计数 |
| `local-trusted` | D4 | 完整 | 逐样本判定 |

客户端无法提权。如有需要，请使用两个实例（不同端口/token）。

## 3. 工具

具体可见性取决于 Profile；`bacmap_capabilities` 会报告实际生效的上限与
可计划的任务类型。

### 3.1 Capabilities

```json
// bacmap_capabilities → （节选）
{
  "server": "bacmap",
  "bacmap_version": "0.1.2",
  "api": "mcp",
  "profile": "cloud",
  "max_data_class": "D1",
  "plannable_task_types": ["analyze", "curate", "mine", "write"],
  "recommended_write_path": "bacmap_create_plan -> user confirms in bacmap CLI/Web -> bacmap_get_plan -> bacmap_task_status",
  "long_running": "explicit task handles (bacmap_task_status polling)",
  "tasks_extension": "unsupported_by_sdk"
}
```

### 3.2 计划

| 工具 | 参数 | 返回 |
|---|---|---|
| `bacmap_create_plan` | `tasks: PlannableTask[]`、`rationale?: string` | 含 `plan_id`、`version`、`state`、`plan_hash`、`confirm_url`、`next_step` 的计划 |
| `bacmap_revise_plan` | `plan_id`、`tasks`、`rationale?` | 新版本；旧版本被取代 |
| `bacmap_get_plan` | `plan_id`、`version?` | 计划状态、任务、哈希、`task_ids` |
| `bacmap_confirm_plan_locally` | `plan_id`、`version` | 打开本地对话框（仅 stdio）；点击即确认 |

任务形状：

```json
{"task_type":"analyze","samples":["SAM-001"]}
{"task_type":"analyze","fasta_dir":"/abs/dir","species":"VPA"}
{"task_type":"analyze","fastq_dir":"/abs/dir","species":"SAL"}
{"task_type":"curate","scope":{"pathogen":"Salmonella"}}
{"task_type":"mine","objective":"...","script":"...","input_paths":["/abs/data"],"input_data_class":"D3","sandbox_image":"docker://python:3.12-slim"}
{"task_type":"write","objective":"...","draft":"...","known_citations":[]}
```

规则：

- `analyze` 需要 `samples`/`fasta_dir`/`fastq_dir` 中恰好一项；
- 目录路径必须为绝对路径；`mine.input_paths` 必须为绝对路径；
- 一个计划最多包含 10 个任务；
- `mine.script` ≤20k 字符；`write.draft` ≤40k；
- 读取/修订仅限创建该计划的客户端；
- 模型无法确认；`confirm_url` 指向 Web 计划页面。

### 3.3 任务

| 工具 | 参数 | 说明 |
|---|---|---|
| `bacmap_submit_task` | `task_type`（`analyze`/`curate`）、`samples?`、`scope?` | 兼容性直接提交；无 `submitted_by`（由服务端认定） |
| `bacmap_task_status` | `task_id` | 状态、步骤、消息（cloud 下脱敏）、failure 块 |
| `bacmap_task_result` | `task_id` | `finished`、`run_id`、门/计数 |
| `bacmap_task_cancel` | `task_id` | 仅限本客户端提交的任务或其自己的计划 |

```json
// bacmap_task_status → （cloud，失败）
{
  "task_id": "3f9c...",
  "state": "failed",
  "current_step": "pipeline",
  "message": "",
  "message_withheld": true,
  "failure": {
    "kind": "sandbox_unavailable",
    "suggested_fix": "安装 Apptainer 或 Podman 后重试；直通模式仅用于受控开发",
    "recovery_commands": ["pixi global install podman"]
  }
}
```

### 3.4 记录（仅 `local-trusted`）

`bacmap_record_data` 提交一个 `record` 任务。参数：

```json
{"kind":"metadata","strain_id":"HZCPE-01","sample_id":"HZCPE-01",
 "fields":{"isolation_date":"2026-10-12","province":"Guangdong","sample_source":"food"}}

{"kind":"lab_result","strain_id":"HZCPE-01","category":"mic",
 "test_name":"meropenem","result":"0.25","unit":"mg/L","interpretation":"S"}

{"kind":"knowledge_import","title":"Paper","identifier":"PMID:12345678","entry_kind":"literature"}

{"kind":"knowledge_approve","entry_id":7}
```

调用返回 `{"task_id": "...", "kind": "...", "state": "running"}`。随后用
`bacmap_task_status` 跟踪。

### 3.5 `bio_*` 工具

26 个注册工具记录在[工具注册表](tools.zh.md)中。在 `cloud` 下，只有数据级别在
上限之内的工具会被注册；在 `local-trusted` 下，全部读/计算工具可用。四个
`write` 工具（`bio_analyze_pathogen`、`bio_generate_report`、`bio_add_metadata`、
`bio_add_lab_result`）永不直接暴露；请使用任务/计划/记录。

## 4. 提示词与资源

| 类型 | 名称 | 用途 |
|---|---|---|
| 提示词 | `bacmap_role_<role>` | 全局原则 + 权限边界 + SKILL 指引 |
| 资源 | `skill://bacmap/<role>/SKILL.md` | 原始 SKILL.md，元数据包含 `sha256` |

角色：analyst、curator、miner、literature、writer、epidemiologist。执行领域工作前
先获取角色提示词。

## 5. 错误

在可能的情况下，MCP 工具失败会返回 JSON 信封，而不是传输层错误：

```json
{"code": "validation_error", "error": "directory not found: /data/run42"}
{"code": "not_found", "error": "no such task: ..."}
{"code": "conflict", "error": "plan hash mismatch ..."}
{"code": "forbidden", "error": "only the MCP client that created this plan may revise it"}
```

未知工具会被 SDK 拒绝。数据分级违规在注册时和调用时都会被拒绝。

## 6. 最小客户端对话

```text
1. bacmap_capabilities {}
2. bacmap_create_plan {"tasks":[{"task_type":"analyze","samples":["SAM-001"]}]}
3. （把 confirm_url 展示给用户；用户在 Web/CLI 中确认）
4. bacmap_get_plan {"plan_id":"..."}                  # → state=submitted, task_ids
5. bacmap_task_status {"task_id":"..."}               # 轮询
6. bacmap_task_result {"task_id":"..."}               # 门摘要 + run_id
```

客户端永远不会拿到可以确认计划或签署审批的工具。
