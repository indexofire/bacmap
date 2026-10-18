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
| `BACMAP_MCP_TOKEN` / `BACMAP_WEB_TOKEN` | none | Bearer token for MCP HTTP transport / Web auth (ADR-12/14). In the default `bearer` mode it is sent as an `Authorization: Bearer` header — **browsers cannot set it**, so the HTML console returns 401 (use an SSH tunnel); in `cookie` mode the browser logs in at `/login` instead. |
| `BACMAP_WEB_AUTH` | `bearer` | Web auth mode: `bearer` (header only, API clients) or `cookie` (browser `/login` → signed session cookie + CSRF) |
| `BACMAP_WEB_SECRET` | derived from token | HMAC secret signing the session cookie (cookie mode); set explicitly to decouple from token rotation |
| `BACMAP_WEB_COOKIE_SECURE` | off | `1` adds `Secure` to auth cookies (TLS deployments) |
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
- `species` is **dual-accept**: a 3-letter code (`SAL`, `ECO`, `SHI`, `VPA`, `KPN`, …; see
  `core/pathogens.yaml`) or a gside label / display name (`Salmonella`, `V_parahaemolyticus`,
  `E. coli`). The registry resolves either form to the code — codes are preferred for new
  registrations (the 40 pathogens gside's marker rules cover are all registered).
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

## 7. Reference genomes, species escalation, recombination (optional)

**Reference genomes (SNP/cgMLST cohorts).** Each cohort group needs a reference genome.
Accessions live in `workflow/config/reference_accessions.yaml` (`group → out + accessions`);
fetch them on a networked workstation:

```bash
python workflows/bacmap/scripts/fetch_reference_genomes.py \
    --manifest workflows/bacmap/config/reference_accessions.yaml \
    --out-dir "$BACMAP_DATA_DIR/reference/genomes" \
    --refs-dir "$BACMAP_HOME/refs"
```

Multi-replicon entries (e.g. V. parahaemolyticus chromosomes I+II) are concatenated into one
reference. **Verify accessions before trusting them** (a wrong accession poisons the SNP tree):

```bash
python workflows/bacmap/scripts/verify_reference_accessions.py \
    --manifest workflows/bacmap/config/reference_accessions.yaml [--strict]
```

This checks each accession's NCBI esummary title against the entry's organism. The packaged
manifest ships **21 cohorts** (the 3 original + 18 verified common pathogens: VCH/VVU/LMO/SAU/
KPN/ABA/PAE/EFA/SPN/SPY/NME/NGO/CDI/LPN/HPY/CJE/BPS/YPE). Offline failures are non-fatal
(per-entry `error`); `--strict` exits non-zero.
Each genome's sha256/version is registered into `refs/manifest.json`, so run records (ADR-18)
trace exactly which reference was used. Groups without a reference simply skip the SNP cohort.

**Species escalation.** `species_mode` picks the starting gside tier; set
`species_escalation: true` (and optionally `species_mode_max`) so an unresolved verdict
escalates `marker → panel → mash_refseq → sourmash → all`. Tiers whose databases are not
provisioned simply fall through (no crash); `attempts` is recorded in `species_id.json`. The
final custom code is recorded per sample.

**Recombination (Gubbins).** Optional and off by default: set
`plan.recombination: true` on a pathogen (in `core/pathogens.yaml`). Gubbins lives in the
separate `recomb` pixi environment (`pixi run -e recomb gubbins`, installed by `pixi install`).
If `run_gubbins.py` is not on PATH the step writes `status="skipped"` into
`snp/<group>/recombination.json` — it never changes a verdict silently.

**Below-species typing (DEC pathotype).** gside stops at species (`ECO`); the diarrheagenic
E. coli pathotype is determined by **gapit's `ecoli_dec` database**
(`gapit screen --db ecoli_dec` → `gapit typing`), not by bacmap. The result lands in
`dec/pathotype.json` and is summarized into `steps.dec` (`pathotype`, `pathotype_scheme`
— `gb4789_6` preferred — `pathotype_confidence`, `pathotype_genes`, `pathotype_runner_up`,
`pathotype_schemes`). If `gapit` is missing the step records `status="skipped"` and the
pathotype degrades to `N/A` (it never guesses).

**Below-species typing via gapit (registry-driven).** Besides DEC pathotype (above), a generic
step runs `gapit screen` + `gapit typing` for every database a sample's species declares in
`core/pathogens.yaml` (`gapit_screens`) and writes `gapit/typing.json`. Status is always
factual: `ran` (a scheme designated a phenotype — e.g. `lm_doumith` → L. monocytogenes
Doumith serogroup, surfaced as `steps.serotype.serogroup` + `serogroup_scheme`),
`no_scheme` (the DB exists but was not built with `--typing`, e.g. `ecoh`), `skipped` (gapit
absent), `failed`. `ecoli_dec` is handled by the dedicated DEC step. Legacy serotype
placeholders are now factual rather than `pending_gapit`: E. coli O/H awaits a `--typing`
gapit DB, Shigella serovar comes from **SISTR**, and V. parahaemolyticus serotyping has no
upstream database yet.

**cgMLST keys: thresholds and the reference library.** `cgmlst.thresholds` is keyed by the**3-letter species code** (`SAL`/`ECO`/`SHI`/`VPA`); lookups pass an arbitrary species spelling
(`Salmonella`, `E. coli`, `Vibrio parahaemolyticus`, …) and it is normalized to the code, so
there is one vocabulary everywhere. The cgMLST reference library is keyed by **scheme**, e.g.
`data/reference/cgmlst/<scheme>/reference_profiles.tsv` (`senterica_2`, `ecoli_2`,
`vparahaemolyticus_3`) — scheme names are gmlst's stable identifiers, decoupled from species
spelling. The former `cgmlst.schemes` config block was removed; per-species schemes come from
`core/pathogens.yaml` (the single source of truth, keyed by code).
