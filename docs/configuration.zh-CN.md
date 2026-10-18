[English](configuration.md) | **简体中文**

# 配置指南

bacmap 的全部配置来自**环境变量 + 一个 TOML 文件**。任何路径不由源码位置推导（ADR-03）。

## 1. 路径体系与环境变量

数据根目录 `BACMAP_HOME`（默认 `~/.local/share/bacmap`），布局：

```
$BACMAP_HOME/
├── data/            # 本地库（菌株元数据 / 化验 / 特征索引）与参考库
├── results/         # 分析结果（按样本分目录）
├── workflows/       # 部署的 Snakemake 工作流（含 config/samples.tsv）
├── workflow_state/  # .snakemake 运行状态（断点续跑）
├── gs/              # 测序数据约定布局：<样本>/<样本>_R1.fastq.gz
├── workspaces/      # mine 任务沙箱工作区
├── gom.sqlite       # GOM：分析对象（ANALYSIS）+ 门/审计事件
├── runs.sqlite      # 分析运行记录（ADR-18）
├── tasks.sqlite     # 任务表
├── dbos.sqlite      # DBOS 工作流引擎库
└── config.toml      # 本配置文件（可选）
```

环境变量（测试与多实例部署用）：

| 变量 | 默认 | 覆盖内容 |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | 数据根目录 |
| `BACMAP_DATA_DIR` | `$BACMAP_HOME/data` | 数据库/参考库目录 |
| `BACMAP_GOM_DB` | `$BACMAP_HOME/gom.sqlite` | GOM 数据库：分析对象 + 门/审计事件（GOM 查询工具读取） |
| `BACMAP_DB_PATH` | `$DATA_DIR/bacmap.sqlite` | 本地数据库：菌株元数据、化验结果、特征索引 |
| `BACMAP_RESULTS_DIR` | `$BACMAP_HOME/results` | 结果目录 |
| `BACMAP_WORKFLOWS_DIR` | `$BACMAP_HOME/workflows` | 工作流部署目录 |
| `BACMAP_WORKFLOW_STATE_DIR` | `$BACMAP_HOME/workflow_state` | 运行状态目录 |
| `BACMAP_RUNS_DB` | `$BACMAP_HOME/runs.sqlite` | 运行记录（ADR-18） |
| `BACMAP_REFS_DIR` | `$BACMAP_HOME/refs` | 外部工具数据库（ADR-20）；`refs/manifest.json` 将登记写入运行记录 |
| `BACMAP_ENV_LOCK` | `$BACMAP_HOME/pixi.lock` | 计入运行记录的环境锁（ADR-18） |
| `BACMAP_MCP_TOKEN` / `BACMAP_WEB_TOKEN` | 无 | MCP HTTP 传输 / Web 鉴权的 Bearer token（ADR-12/14）。默认 `bearer` 模式以 `Authorization: Bearer` 头发送——**浏览器无法设置该头**，故 HTML 控制台返回 401（请用 SSH 隧道）；`cookie` 模式下浏览器改为在 `/login` 登录。 |
| `BACMAP_WEB_AUTH` | `bearer` | Web 鉴权模式：`bearer`（仅头，API 客户端）或 `cookie`（浏览器 `/login` → 签名会话 cookie + CSRF） |
| `BACMAP_WEB_SECRET` | 由 token 派生 | 会话 cookie 的 HMAC 签名密钥（cookie 模式）；显式设置可与 token 轮换解耦 |
| `BACMAP_WEB_COOKIE_SECURE` | 关 | 置 `1` 给鉴权 cookie 加 `Secure`（TLS 部署） |
| `CHECKM2_DB` / `GTDBTK_DATA_PATH` | 无 | 大型鉴定库位置（可选） |

## 2. LLM 端点（config.toml）

配置文件 `$BACMAP_HOME/config.toml`；**不存在时内置 Strata 本地默认**。
所有端点走 OpenAI 兼容协议——本地 Strata、DeepSeek、Kimi、GLM、vLLM 等一视同仁：

```toml
[llm.endpoints.strata]
location = "local"                     # local | lan | cloud
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.endpoints.deepseek]
location = "cloud"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"       # 密钥从环境变量读，不落盘

[llm.routing]                          # 按用途路由（可混搭本地/云端）
intent_classifier = "strata"
interpretation = "deepseek"

[llm.data_policy]
cloud_max_data_class = "D1"            # 见 §3，不可通过配置放宽超过 D2
```

要点：

- **多端点并存**，`[llm.routing]` 按 purpose（`intent_classifier` / `interpretation`）分流；
- 密钥只存环境变量**名**（`api_key_env`），值在 shell/服务环境里注入；
- 端点 `enabled = false` 可临时停用。

## 3. 数据分级政策（ADR-16，安全红线）

| 级别 | 内容 | cloud 端点 |
|---|---|---|
| D0–D1 | 公开信息、脱敏摘要 | ✅ 默认允许 |
| D2 | 菌株级明细 | ⚠️ 默认拦截；管理员在 config.toml 放宽至 `cloud_max_data_class = "D2"` 为止 |
| D3–D4 | 原始基因组数据、可识别个人信息 | ❌ **永不外发**，任何配置都改不了（代码级强制） |

超限请求在**发送前**被 LlmGateway 拦截并记录事件（V9 验证项）。

## 4. 沙箱与资源仲裁

| 配置 | 默认 | 说明 |
|---|---|---|
| `BACMAP_ALLOW_UNSANDBOXED=1` | 关 | mine / `sandbox_run` 的直通执行（仅受控开发环境） |
| `BACMAP_SANDBOX_IMAGE` | `docker://python:3.12-slim` | `sandbox_run` 的沙箱镜像；绘图需镜像自带分析栈（matplotlib/pandas/numpy） |
| 沙箱回退链 | Apptainer → Podman | 都不存在且未开启直通时 mine 任务失败 |
| `llm.resources.co_located` | true | 模型与管线同机时启用内存仲裁 |
| 仲裁阈值 | 24 GB 可用内存 | 低于阈值自动卸载 Strata → 跑重型步骤 → 自动恢复 |

## 5. 样本注册（samples.tsv）

analyze 全流程任务要求样本已注册。编辑 `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`：

```tsv
sample	species	R1	R2
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz
```

- 列：`sample`（ID）、`species`（预期物种）、`R1`/`R2`（FASTQ 路径，相对 workflows 目录）
- 测序数据建议按 `gs/<样本>/<样本>_R{1,2}.fastq.gz` 约定布局
- 工作流重部署时 samples.tsv 与 `.snakemake/` 续跑状态自动保留

## 6. 智能体客户端（MCP）侧配置

bacmap 本身无需为 MCP 做配置；是**客户端**登记 bacmap：

```yaml
# 例：~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/pixi/envs/default/bin/bacmap
    args: ["mcp"]            # 加 --read-only 则只暴露查询工具
```

详见[使用指南](usage.zh-CN.md)。

## 7. 运行记录与外部数据库（ADR-18/20）

每次 analyze 运行写入一条不可修改的记录（`analysis_runs` 表 + `runs/<run_id>/run_manifest.json`）。
`$BACMAP_HOME/workflows/bacmap/config/config.yaml` 中的两个可选键喂给它：

```yaml
iqtree_seed: 42
seeds: {}                     # 额外固定种子，如 {bwa: 11}
nondeterministic_steps: []    # 无法固定随机性的步骤名，如 [assembly_shovill]
```

外部工具数据库在部署期一次性登记于 `$BACMAP_HOME/refs/manifest.json`，条目会写入每次运行记录：

```json
{ "databases": [ { "name": "gapit:card", "version": "3.2.6", "checksum": "<sha256>" } ] }
```

用 `bio_compare_runs` 比较同一样本的两次运行：把差异归因到 参数/数据库/工具/输入/工作流，
并在来源完全相同而结果不同时判为 `NOT_REPRODUCIBLE`。

`vpara_virulence` 的 gapit 库（副溶血性弧菌毒力标记 tdh/trh/tlh）在部署期由打包的
`workflow/refs/vpara_virulence.fasta` 自动构建并登记于此；更新后的数据库可随时替换，
下次运行即记录新版本。数据库缺失时 `vpara_virulence` 规则显式失败（不静默降级）。
