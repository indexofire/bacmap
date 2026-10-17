**English** | [简体中文](configuration.zh-CN.md)

# Configuration guide

All bacmap configuration comes from **environment variables plus one TOML file**. No path is derived from the source tree location (ADR-03).

## 1. Path system and environment variables

The data root is `BACMAP_HOME` (default `~/.local/share/bacmap`), laid out as follows:

```
$BACMAP_HOME/
├── data/            # 本地库（strain metadata / 化验 / 特征索引）与参考库
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

Environment variables (for tests and multi-instance deployments):

| Variable | Default | Overrides |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | Data root directory |
| `BACMAP_DATA_DIR` | `$BACMAP_HOME/data` | Database / reference library directory |
| `BACMAP_GOM_DB` | `$BACMAP_HOME/gom.sqlite` | GOM database: analysis objects + gate/audit events (read by the GOM query tools) |
| `BACMAP_DB_PATH` | `$DATA_DIR/bacmap.sqlite` | Local database: strain metadata, lab results, genotype index |
| `BACMAP_RESULTS_DIR` | `$BACMAP_HOME/results` | Results directory |
| `BACMAP_WORKFLOWS_DIR` | `$BACMAP_HOME/workflows` | Workflow deployment directory |
| `BACMAP_WORKFLOW_STATE_DIR` | `$BACMAP_HOME/workflow_state` | Run-state directory |
| `BACMAP_RUNS_DB` | `$BACMAP_HOME/runs.sqlite` | Run records (ADR-18) |
| `BACMAP_REFS_DIR` | `$BACMAP_HOME/refs` | External tool databases (ADR-20); `refs/manifest.json` registers them into run records |
| `BACMAP_ENV_LOCK` | `$BACMAP_HOME/pixi.lock` | Environment lock hashed into run records (ADR-18) |
| `BACMAP_MCP_TOKEN` / `BACMAP_WEB_TOKEN` | none | Bearer token for MCP HTTP transport / Web API access (ADR-12/14). Sent as an `Authorization: Bearer` header — **browsers cannot set it**, so with a token configured the HTML console returns 401; reach the UI over an SSH tunnel instead (see the usage guide). |
| `CHECKM2_DB` / `GTDBTK_DATA_PATH` | none | Location of large identification databases (optional) |

## 2. LLM endpoints (config.toml)

The configuration file is `$BACMAP_HOME/config.toml`; **when it does not exist, built-in
Strata local defaults apply**. All endpoints speak the OpenAI-compatible protocol, so local
Strata, DeepSeek, Kimi, GLM, vLLM, and the like are all treated alike:

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

Key points:

- **Multiple endpoints coexist**; `[llm.routing]` splits traffic by purpose (`intent_classifier` / `interpretation`);
- Only the environment variable **name** is stored (`api_key_env`); the value is injected in the shell or service environment;
- Set `enabled = false` on an endpoint to disable it temporarily.

## 3. Data classification policy (ADR-16, security red line)

| Level | Content | Cloud endpoints |
|---|---|---|
| D0-D1 | Public information, de-identified summaries | ✅ allowed by default |
| D2 | Strain-level detail | ⚠️ blocked by default; an admin may relax it in config.toml, up to `cloud_max_data_class = "D2"` at most |
| D3-D4 | Raw genomic data, personally identifiable information | ❌ **never sent off the machine**, no configuration can change this (enforced in code) |

Requests over the limit are intercepted by the LlmGateway **before they are sent**, and the event is logged (verification item V9).

## 4. Sandbox and resource arbitration

| Setting | Default | Notes |
|---|---|---|
| `BACMAP_ALLOW_UNSANDBOXED=1` | off | Passthrough execution for mine/`sandbox_run` (controlled development environments only) |
| `BACMAP_SANDBOX_IMAGE` | `docker://python:3.12-slim` | Sandbox image for `sandbox_run`; use an image that bundles the analysis stack (matplotlib/pandas/numpy) so the assistant can render charts |
| Sandbox fallback chain | Apptainer → Podman | If neither exists and passthrough is off, mine tasks fail |
| `llm.resources.co_located` | true | Enables memory arbitration when the model and the pipeline share one machine |
| Arbitration threshold | 24 GB free memory | Below the threshold, Strata is unloaded automatically → heavy steps run → it is restored automatically |

## 5. Sample registration (samples.tsv)

The full analyze task requires samples to be registered. Edit `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`:

```tsv
sample	species	R1	R2
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz
```

- Columns: `sample` (ID), `species` (expected species), `R1`/`R2` (FASTQ paths, relative to the workflows directory)
- Sequencing data should follow the `gs/<sample>/<sample>_R{1,2}.fastq.gz` conventional layout
- When a workflow is redeployed, samples.tsv and the `.snakemake/` checkpoint-resume state are preserved automatically

## 6. Agent client (MCP) side configuration

bacmap itself needs no configuration for MCP; it is the **client** that registers bacmap:

```yaml
# 例：~/.hermes/config.yaml
mcp_servers:
  bacmap:
    command: /path/to/pixi/envs/default/bin/bacmap
    args: ["mcp"]            # 加 --read-only 则只暴露查询工具
```

See the [usage guide](usage.md) for details.

## 7. Run records and external databases (ADR-18/20)

Every analyze run writes an immutable record (`analysis_runs` + `runs/<run_id>/run_manifest.json`).
Two optional keys in `$BACMAP_HOME/workflows/bacmap/config/config.yaml` feed it:

```yaml
iqtree_seed: 42
seeds: {}                     # extra fixed seeds, e.g. {bwa: 11}
nondeterministic_steps: []    # steps whose randomness cannot be fixed, e.g. [assembly_shovill]
```

External tool databases are registered once at deployment time in
`$BACMAP_HOME/refs/manifest.json`; the entries are copied into every run record:

```json
{ "databases": [ { "name": "gapit:card", "version": "3.2.6", "checksum": "<sha256>" } ] }
```

Use `bio_compare_runs` to diff two runs of the same sample: it attributes differences to
parameters / databases / tools / inputs / workflow, and flags `NOT_REPRODUCIBLE` when the
provenance is identical but the results differ.

The `vpara_virulence` gapit database (V. parahaemolyticus virulence markers tdh/trh/tlh)
is built automatically at deploy time from the packaged
`workflow/refs/vpara_virulence.fasta` and registered here; an updated database can replace
it at any time and will be recorded on the next run. The `vpara_virulence` rule fails
explicitly if the database is missing (no silent degradation).
