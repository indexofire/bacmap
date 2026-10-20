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
| `BACMAP_MCP_TOKEN` / `BACMAP_WEB_TOKEN` | 无 | MCP HTTP 传输 / Web 鉴权的 Bearer token（ADR-12/14）。默认 `bearer` 模式以 `Authorization: Bearer` 头发送——**浏览器无法设置该头**，故 HTML 控制台返回 401（请用 SSH 隧道）；`cookie` 模式下浏览器改为在 `/login` 登录。非回环 `--host` 且未设 token 时**拒绝启动**（fail-fast）。 |
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
- 端点 `enabled = false` 可临时停用；
- **会话助手在云端端点下自动裁剪工具带（v1.4.30）**：`intent_classifier` 路由到 `cloud`
  端点时，高于 `cloud_max_data_class` 的只读工具（D4 元数据/检验、D3 数据集查看）不进
  会话，沙箱工具整体排除，会话级别由裁剪后工具带派生（≤D2）。要获得完整能力请放宽到
  `"D2"`；只允许 D1 时助手仅剩 D0 工具（参考基因组清单/诊断）。本地/局域网端点不受影响；
- 密钥注入方式、GLM 通用端点与 coding 端点的匹配关系、以及 401/429 等接入报错的
  完整排查表，见[安装指南 §5](installation.zh-CN.md)。

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
- `species` **双接受**：三字母码（`SAL`/`ECO`/`SHI`/`VPA`/`KPN`…，见 `core/pathogens.yaml`）
  或 gside 标签/显示名（`Salmonella`、`V_parahaemolyticus`、`E. coli`）；registry 归一为码。
  新登记**推荐用码**（gside marker 规则覆盖的 40 条物种均已注册）。
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

## 7. 参考基因组、鉴定升级、重组检测（可选）

**参考基因组（SNP/cgMLST cohort）**：每个 cohort 组需要一个参考基因组，accession 写在
`workflow/config/reference_accessions.yaml`（`group → out + accessions`）；联网工作站取回：

```bash
python workflows/bacmap/scripts/fetch_reference_genomes.py \
    --manifest workflows/bacmap/config/reference_accessions.yaml \
    --out-dir "$BACMAP_DATA_DIR/reference/genomes" \
    --refs-dir "$BACMAP_HOME/refs"
```

多复制子（如副溶血性弧菌 I+II 号染色体）按顺序拼接为单条参考；**信任前先核验 accession**
(错配的 accession 会污染 SNP 树)：

```bash
python workflows/bacmap/scripts/verify_reference_accessions.py \
    --manifest workflows/bacmap/config/reference_accessions.yaml [--strict]
```

核验逐条取 NCBI esummary 标题并与条目 organism 比对。包内清单现含 **21 个 cohort**（原 3 个 +
18 个已核验常见病原：VCH/VVU/LMO/SAU/KPN/ABA/PAE/EFA/SPN/SPY/NME/NGO/CDI/LPN/HPY/CJE/BPS/YPE）。
离线失败不中断（逐条记 `error`），`--strict` 时非零退出。每个基因组的 sha256/版本登记进 `refs/manifest.json`，
运行记录（ADR-18）据此溯源；没有参考的组自动跳过 SNP cohort。

**鉴定升级**：`species_mode` 为起始 gside 档位；设 `species_escalation: true`（可选
`species_mode_max`）后，未定种会按 `marker→panel→mash_refseq→sourmash→all` 升档。库未就绪的档
自动落空（不崩溃），`attempts` 记入 `species_id.json`。

**重组检测（Gubbins）**：默认关闭；在 `core/pathogens.yaml` 给病原设 `plan.recombination: true`
即启用。Gubbins 装在独立的 `recomb` pixi 环境（`pixi run -e recomb gubbins`，随 `pixi install`
安装）。`run_gubbins.py` 不在 PATH 时该步骤写 `status="skipped"` 到
`snp/<group>/recombination.json`——绝不静默改判定。

**种以下判定（DEC 致病型）**：gside 止于种（`ECO`）；致泻性大肠埃希菌的致病型由 **gapit 的
`ecoli_dec` 库**判定（`gapit screen --db ecoli_dec` → `gapit typing`），bacmap 不自判。结果落在
`dec/pathotype.json`，归一进 `steps.dec`（`pathotype`、`pathotype_scheme`——首选 `gb4789_6`——
`pathotype_confidence`、`pathotype_genes`、`pathotype_runner_up`、`pathotype_schemes`）。
`gapit` 缺失时该步骤记 `status="skipped"`，`pathotype` 退化为 `N/A`（绝不猜测）。

**gapit 通用分型（registry 驱动）**：除上面的 DEC 致病型外，还有一个通用步骤——对样本物种在
`core/pathogens.yaml` 声明的每个 `gapit_screens` 库执行 `gapit screen` + `gapit typing`，写
`gapit/typing.json`。状态**一律如实**：`ran`（有 scheme 并给出表型，如 `lm_doumith` → 单核细胞
增生李斯特菌 Doumith 血清群，并入 `steps.serotype.serogroup` 与 `serogroup_scheme`）、
`no_scheme`（库存在但未 `--typing` build，如 `ecoh`；gapit 把 `TYPING_NO_SCHEME` 写在 stderr
且退出码非 0，仍如实记为 `no_scheme`）、`unavailable`（库未安装：`DATABASE_NOT_FOUND`）、
`skipped`（gapit 缺失）、`failed`（真正的执行失败）。
`ecoli_dec` 由 DEC 专用步骤处理。

**血清型按物种路由**：gside 定种之后，只有**适用**的种以下步骤进入 DAG——不适用者根本不执行，
结果目录里也不会出现无干的产物（路由依据 `core/pathogens.yaml` 的 `serotype_engine` 与 `gapit_screens`）：

| 引擎 | 物种 | 步骤 |
|---|---|---|
| `sistr` | 沙门菌 | SISTR 血清变型——**SISTR 只做沙门菌** |
| `shigatyper` | 志贺菌 | ShigaTyper（读段级）给出志贺菌血清型；计划迁 gapit |
| `ecoh`（gapit） | 大肠埃希菌 | O/H 血清型（库 `--typing` build 后生效） |
| `ecoli_dec`（gapit） | 大肠埃希菌 | DEC 致病型 |
| `vpara_virulence`（gapit） | 副溶血性弧菌 | tdh/trh/tlh 毒力 + O/K 血清型 |

不适用于该物种的步骤，汇总里如实标 `not_applicable`（`steps.serotype.sistr_status`、
`steps.dec.status`、`steps.dec.pathotype_status`），不臆造数值。

**cgMLST 键：阈值与参考库**：`cgmlst.thresholds` 以**三字母物种码**建键（`SAL`/`ECO`/`SHI`/`VPA`）；
调用方传任意物种写法（`Salmonella`/`E. coli`/`Vibrio parahaemolyticus`…）都会被归一为码，
全系统一套词表。cgMLST 参考库按 **scheme** 命名，如
`data/reference/cgmlst/<scheme>/reference_profiles.tsv`（`senterica_2`/`ecoli_2`/
`vparahaemolyticus_3`）——scheme 是 gmlst 的稳定标识符，与物种写法解耦。原 `cgmlst.schemes`
配置块已删除；各物种的方案来自 `core/pathogens.yaml`（单一事实来源，码键）。
