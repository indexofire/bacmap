# 配置参考

配置由**环境变量 + 一个 TOML 文件**组成（不是 YAML），另有一个可选的 YAML 覆盖层用于
按工具选择参考数据（§13）。数据路径绝不从源码树推导（ADR-03）。当配置文件不存在时，
使用内置默认值。

配置模板：仓库根目录的 [`config.example.toml`](https://github.com/indexofire/bacmap/blob/main/config.example.toml)，
或运行：

```bash
bacmap config init          # 写入 $BACMAP_HOME/config.toml
bacmap config init --user   # 写入 ~/.config/bacmap/config.toml
bacmap config init --project # 写入当前目录 config.toml（源码检出已 gitignore）
bacmap config path          # 显示当前实际读取的文件
```

配置文件解析顺序：

1. `BACMAP_CONFIG` 显式指定的文件；
2. `$BACMAP_HOME/config.toml`（已存在的旧形态继续兼容）；
3. `$XDG_CONFIG_HOME/bacmap/config.toml`，未设置 XDG 时为
   `~/.config/bacmap/config.toml`；
4. 都不存在时使用内置默认值。

项目内 `config.toml` 不会被自动发现；这是有意的（ADR-03）。复制模板到项目根目录后，
运行前设置：

```bash
export BACMAP_CONFIG="$PWD/config.toml"
```

## 1. 环境变量

| 变量 | 默认值 | 含义 |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | 数据根目录 |
| `BACMAP_CONFIG` | 见解析顺序 | 显式配置文件路径；适合项目内临时配置 |
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
| `BACMAP_LANG` | — | CLI 显示语言覆盖（`en`/`zh`）；优先于 `[ui].language` |
| `BACMAP_TOOL_SELECTION` | — | 显式 `tool_selection.yaml` 覆盖层路径（§13） |
| `BACMAP_DB_SELECTION` | — | 旧版 gapit-only 覆盖层路径（加载时翻译为 `tool_selection.yaml`） |
| `BACMAP_RESEARCH_PROFILE` | `research` | Research Workbench 默认治理 Profile（`open-test`/`research`/`publication`） |
| `BACMAP_DEBUG` | 关 | **仅开发**：显式覆盖 `[debug].enabled`；`1` 开启，`0` 关闭。关闭 Web 鉴权/CSRF、计划确认、任务审批、门、Research Claim/发表门与沙箱回退；**MCP 数据级别上限与 HTTP 鉴权不放宽**；D3/D4→cloud 仍被阻止。 |
| `BACMAP_BENCHMARK_DATA` | — | Research 科学基准的本地公共数据快照；可指向单个数据集目录，或包含 `bvbrc_kpn_meropenem`/`osf_n78q3` 的父目录 |
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

[ui]
language = "en"

[mcp]
allow_local_trusted = false

[debug]
enabled = false

[plans.auto_confirm]
enabled = false
task_types = ["analyze"]
max_samples = 20
max_tasks = 10
allow_directory_ingestion = false
allow_scripts = false
allow_drafts = false
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

## 4.1 开发调试模式

调试模式也可以持久写入配置文件，不必每次导出环境变量：

```toml
# $BACMAP_HOME/config.toml
[debug]
enabled = true
```

优先级：`BACMAP_DEBUG` 显式设置 > `[debug].enabled`。因此配置文件开启后，可以用
`BACMAP_DEBUG=0` 临时关闭：

```bash
BACMAP_DEBUG=0 bacmap doctor
```

配置文件开启是**持久状态**；`bacmap doctor` 会输出 `debug=warn`。生产环境不得开启。
该开关不放宽 ADR-16 数据红线：D3/D4 仍不得发往 cloud LLM 端点。它也不提高 MCP 数据级别
上限、不绕过 MCP HTTP 鉴权：`cloud` 仍受 `cloud_max_data_class` 限制，`local-trusted`
仍需 `[mcp] allow_local_trusted = true`，HTTP 始终需要 token。

## 5. 计划

默认关闭自动确认；开启后仍按下方条件 fail-closed。

```toml
[plans.auto_confirm]
enabled = false
task_types = ["analyze"]       # 可选：analyze / curate / mine / write
max_samples = 20               # analyze 且使用 samples 列表时的上限
max_tasks = 10                 # 单个计划任务数上限（硬上限也是 10）
allow_directory_ingestion = false
allow_scripts = false
allow_drafts = false
```

默认策略与 v1.9 兼容：仅自动确认满足以下条件的 `analyze` 计划：

- 引用非空的、已登记的 `samples` 列表；
- 不使用 `fasta_dir`/`fastq_dir`；
- 样本数量不超过 `max_samples`。

管理员可显式放宽用于自动迭代：

| 配置 | 放宽内容 | 仍然保留的安全边界 |
|---|---|---|
| `task_types` | 允许自动确认的任务类型 | 未列出的类型仍需人工确认 |
| `allow_directory_ingestion` | 自动确认目录直入 analyze | 输入指纹仍会在确认前复核 |
| `allow_scripts` | 自动确认 `mine` 计划 | 脚本仍在无网络沙箱执行，产物仍过挖掘门 |
| `allow_drafts` | 自动确认 `write` 计划 | 引用门仍强制，导出仍需人工签 |
| `max_tasks` | 多任务计划 | 超过上限 fail-closed |

`mine` 必须同时配置 `task_types` 包含 `mine` 与 `allow_scripts = true`；
`write` 必须同时包含 `write` 与 `allow_drafts = true`。任何配置值非法都会回退为
“需要人工确认”。自动确认的审计 actor 为 `policy:auto-confirm`。

例：全自动 analyze + mine 迭代（管理员显式选择）：

```toml
[plans.auto_confirm]
enabled = true
task_types = ["analyze", "mine"]
max_samples = 100
allow_directory_ingestion = true
allow_scripts = true
```

注意：任务内的审批门不因此消失。`curate` 发布、`mine` 产物签字、`write` 导出、
分析结论复核仍可能进入 `awaiting_approval`，需要人在 bacmap 的可信界面处理。

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
├── config/               # config.toml、可选的 tool_selection.yaml
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
bacmap start web --host 127.0.0.1 --port 8800
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
- 无效的 `plans.auto_confirm` 策略（`max_samples`/`max_tasks`/`task_types`/开关）会禁用自动确认（故障安全）。
- 比代码更新的数据库会被拒绝；请恢复匹配的备份，而不是降级。
- `config.toml` 只能包含密钥环境变量的名称，绝不能包含密钥本身。

## 12. 显示语言

| 设置 | 默认值 | 说明 |
|---|---|---|
| `[ui].language` | `en` | CLI 帮助与提示文案的语言；`en` 或 `zh`（大小写不敏感） |
| `BACMAP_LANG` | — | 环境变量覆盖；优先于配置文件 |

非法或缺失的取值确定性回落 `en`（与 `[debug]` 的容错口径一致）。该设置只影响
CLI 帮助、提示与消息——数据、报告与 JSON 输出不受影响。

## 13. 工具参考数据选择（`tool_selection.yaml`）

`core/pathogens.yaml` 是包内的物种→参考数据默认映射，**用户不直接编辑**；本地选择写入
YAML 覆盖层，升级时不会丢失：

| 层 | 位置 |
|---|---|
| 包内默认值 | `core/pathogens.yaml`（gapit 库、gmlst scheme） |
| 用户/项目覆盖层 | `$BACMAP_HOME/config/tool_selection.yaml`、`BACMAP_TOOL_SELECTION`、工作流 `tool_selection` 键，或 `bacmap selection --selection PATH` |
| 运行时物种判定 | `species/species_id.json`（gside；仅工作流） |

覆盖层解析顺序：显式路径 → `BACMAP_TOOL_SELECTION` → 旧 `BACMAP_DB_SELECTION` →
`$BACMAP_HOME/config/tool_selection.yaml` → `$BACMAP_HOME/config/db_selection.yaml`。旧文件
（`bacmap.db_selection/1`）按 gapit-only 别名读取并在加载时告警。

Schema `bacmap.tool_selection/1`：

```yaml
schema: bacmap.tool_selection/1
defaults:                        # 可选：条目省略 `mode` 时的合并模式
  gapit: {mode: extend}          # extend（默认）| replace
  gmlst: {mode: extend}
species:
  VPA:
    gapit:
      mode: extend               # registry 默认 + 列出的库
      databases: [vpa_ok, vpa_pai]
    gmlst:
      mode: replace
      modes: [mlst]              # mlst | cgmlst | wgmlst | tgmlst
      schemes: {mlst: vparahaemolyticus_1}
samples:
  S42:
    gapit: {databases: [vpa_ok]} # 样本条目替换物种列表
meta:                            # 可选：`selection select` 写入的来源信息
  generated_by: cli
  generated_at: "2026-11-07T00:00:00+00:00"
  approved_by: operator
```

优先级为 **sample > species > registry**。`gapit.databases` 默认扩展 registry 列表，除非
`mode: replace`；`gmlst.modes` 与 `gmlst.schemes` 默认按 key 合并，除非 `mode: replace`。
未知物种码、库名或 scheme 名都是校验错误——不做任何猜测。scheme 必须在 gmlst catalog 中
存在（配合 `--downloaded-only` 时还要求已缓存）。

用确定性 CLI 查看与写入；流水线本身绝不调用 LLM：

```bash
bacmap selection options --tool all --json   # catalog 行 + 当前选择
bacmap selection show --diff                 # 生效映射与 registry 的差异
bacmap selection validate                    # 未知 / 未下载 / 类型不匹配条目
bacmap selection select --tool gmlst --species VPA --modes mlst --schemes mlst=vparahaemolyticus_1
bacmap db ...                                # gapit-only 别名（--tool gapit）
```

`bacmap selection options --json` 与只读 MCP 工具 `bio_tool_selection_options` 返回同一份
选项文档，因此智能体可以提议选择、由人工确认。运行记录保存 `tool_selection_effective` 与
`tool_selection_sha256`（旧 `db_selection_*` 名称仍可读取）。
