# 配置参考

配置由**环境变量 + 一个 TOML 文件**组成。路径绝不从源码树推导（ADR-03）。
当 `config.toml` 不存在时，使用内置默认值。

## 1. 环境变量

| 变量 | 默认值 | 含义 |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | 数据根目录 |
| `BACMAP_DATA_DIR` | `$BACMAP_HOME/data` | 元数据/参考数据库 |
| `BACMAP_DB_PATH` | `$DATA_DIR/bacmap.sqlite` | 菌株元数据 + 化验结果 |
| `BACMAP_GOM_DB` | `$BACMAP_HOME/gom.sqlite` | GOM、数据集、菌株索引 |
| `BACMAP_RUNS_DB` | `$BACMAP_HOME/runs.sqlite` | 运行记录 |
| `BACMAP_RESULTS_DIR` | `$BACMAP_HOME/results` | 结果 |
| `BACMAP_WORKFLOWS_DIR` | `$BACMAP_HOME/workflows` | 已部署的工作流 |
| `BACMAP_WORKFLOW_STATE_DIR` | `$BACMAP_HOME/workflow_state` | Snakemake 状态/日志 |
| `BACMAP_REFS_DIR` | `$BACMAP_HOME/refs` | 外部数据库 + manifest |
| `BACMAP_ENV_LOCK` | `$BACMAP_HOME/pixi.lock` | 计入运行记录的环境锁 |
| `BACMAP_WEB_URL` | `http://127.0.0.1:8800` | 计划 `confirm_url` 的基地址 |
| `BACMAP_MCP_TOKEN` | — | MCP HTTP 的 bearer token |
| `BACMAP_WEB_TOKEN` | — | Web/API 的 bearer token |
| `BACMAP_WEB_AUTH` | `bearer` | `bearer` 或 `cookie` |
| `BACMAP_WEB_SECRET` | 由 token 派生 | 会话 cookie 的 HMAC 密钥 |
| `BACMAP_WEB_COOKIE_SECURE` | 关 | `1` 给 cookie 加上 `Secure` |
| `BACMAP_ALLOW_UNSANDBOXED` | 关 | `1` 允许直接执行（仅开发） |
| `CHECKM2_DB` | — | CheckM2 数据库路径 |
| `GTDBTK_DATA_PATH` | — | GTDB-Tk 数据库路径 |

`--home` 按命令覆盖 `BACMAP_HOME`。`--token-env` 更改 Web/MCP
token 所在的环境变量名。

## 2. `config.toml` 概览

```toml
[llm.data_policy]
cloud_max_data_class = "D1"

[llm.endpoints.strata]
location = "local"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.routing]
interpretation = "strata"

[llm.resources]
co_located = true
min_free_ram_gb_for_heavy_steps = 24.0

[mcp]
allow_local_trusted = false

[plans.auto_confirm]
enabled = false
max_samples = 20
```

## 3. LLM 端点

端点兼容 OpenAI 协议。多个端点可以并存；`[llm.routing]` 按名称把用途映射到
端点。

### 3.1 端点键

| 键 | 默认值 | 说明 |
|---|---|---|
| `location` | `local` | `local` / `lan` / `cloud`；cloud 受数据分级约束 |
| `base_url` | 必填 | OpenAI 兼容的 base URL |
| `model` | 必填 | 模型名称 |
| `kind` | `openai_compatible` | 保留 |
| `tier` | `T2` | 能力档位；角色声明最低要求 |
| `max_concurrency` | `1` | 每端点信号量（本地模型通常需要 1） |
| `api_key_env` | — | 存放密钥的环境变量**名** |
| `enabled` | `true` | 不删除即可停用 |
| `supports_tools_with_schema` | `false` | 端点能力元数据 |
| `constrained_decoding` | `false` | 能力元数据 |
| `request_timeout_s` | `300` | 每请求超时 |
| `admin_url` | — | Strata `/load` `/unload` 管理端点 |

### 3.2 路由

```toml
[llm.routing]
interpretation = "deepseek"          # 由 agent/interpret.py 使用
```

如果某个用途没有路由，则使用第一个已启用的端点，并记录一条警告。请显式固定路由，
以避免意外的云端外发。

### 3.3 数据策略

```toml
[llm.data_policy]
cloud_max_data_class = "D1"   # D1 或 D2；D3/D4 在解析时即被拒绝
```

网关在发送到 `cloud` 端点前比较载荷分级，超过上限时抛出
`DataClassViolationError`。该上限无法通过配置提高到 D2 以上。

### 3.4 资源（ADR-17）

```toml
[llm.resources]
co_located = true
min_free_ram_gb_for_heavy_steps = 24.0
```

当模型与流水线共享同一主机时，重型步骤可以请求卸载模型。若模型运行在
别处，请设置 `co_located = false`。

## 4. MCP

```toml
[mcp]
allow_local_trusted = false   # 必须是布尔 true 才能启动 --profile local-trusted
```

MCP 服务器默认使用 `cloud` Profile。Profile 的上限同样是
`cloud_max_data_class`。见 [MCP 参考](mcp.zh.md)。

## 5. 计划

```toml
[plans.auto_confirm]
enabled = false
max_samples = 20
```

自动确认仅适用于满足以下条件的 `analyze` 计划：

- 引用非空的、已登记的 `samples` 列表；
- 不使用 `fasta_dir`/`fastq_dir`（目录摄取）或脚本；
- 样本数量不超过 `max_samples`。

`mine`、`write`、`curate` 与记录任务永不自动确认。`max_samples` 格式错误时会
安全地回退为“需要人工确认”。审计 actor 为 `policy:auto-confirm`。

## 6. 样本注册

`samples.tsv` 是数据文件，不是 `config.toml`：

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-001	Salmonella	gs/SAM-001/SAM-001_R1.fastq.gz	gs/SAM-001/SAM-001_R2.fastq.gz			SAM-001	ilm	<sha256>
```

列语义、命名、冲突与注册见[数据与身份](../guide/data.zh.md)。

## 7. 目录与数据库布局

```text
$BACMAP_HOME/
├── data/                 # bacmap.sqlite, knowledge.sqlite
├── results/runs/<task_id>/...
├── workflows/bacmap/     # 已部署的 DAG + samples.tsv
├── workflow_state/       # logs/state
├── gs/                   # 原始输入（约定）
├── workspaces/<task_id>/ # mine 工作区
├── runs/<run_id>/run_manifest.json
├── refs/manifest.json
├── tasks.sqlite
├── dbos.sqlite
├── runs.sqlite
├── gom.sqlite
└── baseline.sqlite
```

## 8. 外部数据库

每次运行的记录都会读取 `refs/manifest.json`：

```json
{"databases": [
  {"name": "gapit:card", "version": "3.2.6", "checksum": "sha256:..."},
  {"name": "gmlst:senterica_2", "version": "2026-09", "checksum": "sha256:..."}
]}
```

文件缺失或格式错误时得到空列表；bacmap 不会猜测版本。

## 9. Web 与 API 鉴权

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
export BACMAP_WEB_AUTH=cookie          # 可选的浏览器登录
export BACMAP_WEB_SECRET="..."         # 可选的显式 HMAC 密钥
export BACMAP_WEB_COOKIE_SECURE=1      # 位于 TLS 之后
bacmap web --host 127.0.0.1 --port 8800
```

- 非回环主机且无 token 时拒绝启动。
- Bearer 模式用于 API 客户端；浏览器无法设置该请求头。
- Cookie 模式增加 `/login`、签名的 `HttpOnly` 会话，以及 POST 的 CSRF。
- `BACMAP_WEB_URL` 控制计划的 `confirm_url`（默认回环）。

## 10. 沙箱

| 设置 | 默认值 | 说明 |
|---|---|---|
| backend | Apptainer → Podman | 运行时自动检测 |
| 镜像 | `mine.sandbox_image`，默认 `docker://python:3.12-slim` | 每个计划单独指定；没有环境变量 |
| `BACMAP_ALLOW_UNSANDBOXED` | 关 | 直接在宿主机执行；仅开发 |
| 网络 | 无 | 由容器后端强制 |
| 挂载 | results/GOM/datasets 只读 | 仅声明的输入路径 |

不支持 Docker。没有可用后端时，`mine` 会以 `sandbox_unavailable` 失败。

## 11. 校验与失败行为

- 类型化段中的未知 TOML 键会被拒绝（pydantic `extra="forbid"`）。
- `cloud_max_data_class` 高于 D2 是解析错误。
- 无效的 `plans.auto_confirm.max_samples` 会禁用自动确认（故障安全）。
- 比代码更新的数据库会被拒绝；请恢复匹配的备份，而不是降级。
- `config.toml` 只能包含密钥环境变量的名称，绝不能包含密钥本身。
