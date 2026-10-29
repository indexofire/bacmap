# 数据模型与存储

bacmap 用 SQLite 保存结构化状态，用普通目录保存结果文件。所有内容都位于 `BACMAP_HOME` 之下。

## 1. 身份标识：菌株实体 → 数据集 → 运行

```text
isolate: HZCPE-01                  biological strain (stable)
   ├── dataset: HZCPE-01__ilm__20261012   one sequencing library
   │      └── run: 4f2c…                   one analysis execution
   └── dataset: HZCPE-01__ont__20261020
          └── run: 9a31…
```

- **isolate（菌株实体）** —— 你在流行病学上追踪的实体；可以带谱系/传代信息
  （`EVO-001-P037` → 谱系 `EVO-001`，第 37 代）。
- **dataset（数据集）** —— 一个输入文库或组装。其 ID 即 `samples.tsv` 中的 `sample` 列。
- **run（运行）** —— 管线对一个或多个数据集的一次执行。结果从不跨运行共享，即使数据集相同。

这种分离使得同一菌株可以测序两次而不覆盖结果，也使得策展时该菌株只计一次。

## 2. `samples.tsv`（数据集登记表）

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	a1b2…
ASM-STD-001	Salmonella		gs/ASM-STD-001/ASM-STD-001.fasta			ASM-STD-001	ont	c3d4…
```

| 列 | 语义 |
|---|---|
| `sample` | 数据集 ID；`^[A-Za-z0-9._-]+$`，不得为 `.`/`..` |
| `species` | 物种代码或名称；未知时为 `UNK` |
| `R1`、`R2` | 双端读段；相对于 `BACMAP_HOME` 或绝对路径 |
| `assembly` | 预组装 FASTA；跳过 QC/组装 |
| `isolate` | 生物学菌株；默认为数据集 ID |
| `platform` | `ilm`、`ont`、`pacbio`、`unknown` |
| `checksum` | 由登记流程维护的内容哈希 |

登记会写入该行并登记菌株实体。数据集 ID 冲突且内容不同是硬错误，绝不静默覆盖。

## 3. 数据库

| 文件 | 表 / 用途 |
|---|---|
| `tasks.sqlite` | `tasks`、`approvals`、`plans`、`events` —— 运行态事实来源 |
| `dbos.sqlite` | DBOS 系统数据库：工作流/步骤检查点 |
| `runs.sqlite` | `analysis_runs` —— 不可变的溯源记录 |
| `gom.sqlite` | 基因组对象、GOM 事件、数据集、菌株基因型索引、AMR 基因索引 |
| `baseline.sqlite` | 基线候选与已发布版本 |
| `data/bacmap.sqlite` | 菌株元数据、实验室结果、菌株实体 |
| `data/knowledge.sqlite` | 文献/方法条目 + FTS5 索引 |
| `refs/manifest.json` | 外部数据库版本/校验和 |

迁移：

- 每个文件都有一个编号列表与 `PRAGMA user_version`。
- 迁移在备份 `<db>.bak-v<N>` 之后，于单个 `BEGIN IMMEDIATE` 事务中执行。
- 若数据库版本高于当前运行的代码，则拒绝启动（不做静默降级）。
- 迁移列表只追加。

参见 `store/migrations.py` 与 `store/schema.py`。

## 4. 磁盘布局

```text
$BACMAP_HOME/
├── config.toml
├── data/
│   ├── bacmap.sqlite
│   └── knowledge.sqlite
├── results/
│   ├── runs/<task_id>/...
│   ├── <dataset> -> runs/<latest>/<dataset>
│   ├── snp -> runs/<latest>/snp
│   └── cgmlst -> runs/<latest>/cgmlst
├── workflows/bacmap/          # deployed DAG + config/samples.tsv
├── workflow_state/            # Snakemake logs/state
├── gs/<dataset>/...           # conventional raw inputs
├── workspaces/<task_id>/      # mine workspace (analysis.py, context.json, artefacts)
├── runs/<run_id>/run_manifest.json
├── refs/
├── tasks.sqlite
├── dbos.sqlite
├── runs.sqlite
├── gom.sqlite
└── baseline.sqlite
```

`results/runs/<task_id>/` 是一次运行唯一写入的位置。扁平路径是指向最新运行的相对符号链接。
摄取/门/报告读取运行目录，而不是别名（v1.9.3）。

## 5. 分析记录的生命周期

```text
input file(s)
  │  registration → samples.tsv (+ checksum)
  ▼
task submitted (task_id)
  │  DBOS workflow
  ├─ Snakemake writes results/runs/<task_id>/
  ├─ create analysis_runs row + manifest (hashes, versions, seeds)
  ├─ GOM ANALYSIS objects + strain index
  ├─ analysis-claims gate event
  └─ report HTML
  ▼
task state succeeded / awaiting_approval
```

## 6. GOM 对象

`GenomeObject` 不可变且带版本：

```python
GenomeObject(
    object_id="analysis:SAM-001:<run_id>",
    object_type=ObjectType.ANALYSIS,
    version=1,
    schema_version="1.0.0",
    payload={...},
    pipeline_version=...,
    database_versions={...},
    tool_versions={...},
    organism="Salmonella",
    strain_id="SAM-001",
)
```

- 两次创建相同的 `(object_id, version)` 会抛出 `GOMImmutableError`（幂等重试）。
- 内容变化即意味着一个新对象，或调用 `create_new_version`。
- GOM 事件记录门评估结果（`gate.<name>`）与生命周期事件。

## 7. 基线库

一个 `curate` 候选包含：

- 每个菌株实体一个代表性运行（`representative_runs`），
- `superseded` 数据集及原因，
- `excluded` 记录（元数据缺失、物种不支持、QC 失败），
- 仅限白名单的特征表（从构造上就不含个人字段）。

发布时写入新的 `baseline_releases` 行，带签名与父版本。已发布版本只追加。
参见[冻结设计](frozen-design.zh.md) ADR-19。
