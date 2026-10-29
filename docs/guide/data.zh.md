# 数据与身份

bacmap 区分三个层级的身份：

```text
isolate (biological strain, stable)
   └── dataset (one sequencing library / assembly)
          └── run (one analysis execution)
```

一个菌株可能被测序多次；一个数据集可能被分析多次。结果绝不会在运行之间混淆，整理基线时也绝不
会把同一个菌株实体重复计数。

## 1. samples.tsv 表

位置：`$BACMAP_HOME/workflows/bacmap/config/samples.tsv`。

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	<sha256>
ASM-STD-001	Salmonella		gs/ASM-STD-001/ASM-STD-001.fasta			ASM-STD-001	ont	<sha256>
HZCPE-01__ilm__20261012	VPA	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R1.fastq.gz	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R2.fastq.gz			HZCPE-01	ilm	<sha256>
HZCPE-01__ont__20261020	VPA	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R1.fastq.gz	gs/HZCPE-01__ont__20261020/HZCPE-01__ont__20261020_R2.fastq.gz			HZCPE-01	ont	<sha256>
```

| 列 | 含义 |
|---|---|
| `sample` | **数据集 ID**。允许字符：`A-Z a-z 0-9 . _ -`；永远不能是 `.` 或 `..` |
| `species` | 三字母代码或 gside 标签/名称；尚未鉴定的 reads 用 `UNK` |
| `R1`/`R2` | 成对 FASTQ 路径，相对于 `BACMAP_HOME` 或绝对路径 |
| `assembly` | 组装后的 FASTA 路径；跳过 QC/组装；两者都设置时 reads 优先 |
| `isolate` | 生物学菌株 ID；旧表默认等于数据集 ID |
| `platform` | 测序平台（`ilm`、`ont`、`pacbio` 等）；未提供时为 `unknown` |
| `checksum` | 输入文件的 SHA-256；由登记流程维护 |

同一菌株实体有多个文库时的命名建议：

```text
<isolate>__<platform>[__<date>]
HZCPE-01__ilm__20261012
HZCPE-01__ont__20261020
```

## 2. 登记路径

### 2.1 目录登记（推荐）

```bash
# Assembled FASTA; species auto-detected with gside unless --species is given
bacmap task submit --type analyze --fasta-dir /data/genomes --species VPA

# Reads; pairs are detected from *_R1/_R2 or *_1/_2
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

登记是一个任务步骤，而不是直接编辑文件：它会写 `samples.tsv`、登记菌株实体，然后提交分析。
登记函数会把 `added`、`reused`、`skipped` 和 `detected` 返回给工作流（实际分析的是返回的样本
列表）；CLI 返回提交后的 `task_id`，登记结果可在 `samples.tsv` 中查看。

```json
{
  "samples": ["HZCPE-01__ilm__20261012"],
  "added": 1,
  "reused": 0,
  "skipped": [],
  "detected": {"HZCPE-01__ilm__20261012": "VPA"},
  "samples_tsv": "/home/me/.local/share/bacmap/workflows/bacmap/config/samples.tsv"
}
```

### 2.2 手工添加行

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
NEW-001	Salmonella	gs/NEW-001/NEW-001_R1.fastq.gz	gs/NEW-001/NEW-001_R2.fastq.gz			NEW-001	ilm
```

手工添加行时可以留空 `checksum`；下一次登记会重新计算它。管线使用相对于 `BACMAP_HOME` 的路径，
与 Snakefile 完全一致。

## 3. 冲突规则

登记已存在的数据集 ID 时，**只有内容哈希一致**才视为幂等：

```text
dataset_id collision: 'HZCPE-01__ilm__20261012' already registered with different content
(existing path: ...; new path: ...). Rename the file or use a distinct dataset id,
e.g. HZCPE-01__ilm__20261012__<platform>__<yyyymmdd>.
```

具体行为：

- 相同 ID + 相同内容 → 复用，不产生重复行；
- 相同 ID + 不同路径或内容 → 直接报错；绝不会静默分析旧文件；
- 没有 `checksum` 的历史行 → 比较之前会重新计算已记录文件的哈希。

不是合法标识符的数据集 ID 在目录登记时会被跳过并给出原因，因此它无法创建不可读的结果目录。

## 4. 菌株实体、谱系与传代

```bash
bacmap isolate list
bacmap isolate show HZCPE-01
```

菌株实体由 `samples.tsv` 自动创建。命名约定：

```text
EVO-001-P000
EVO-001-P001
EVO-001-P037
```

`EVO-001-P037` 会被解析为谱系 `EVO-001`、传代 `37`。为每一代传代各建一个菌株实体，并在其下关联
一个或多个数据集。`lineage_id` 预留给传代之间的关联；当前版本会解析它，但尚未提供跨谱系的 API。

`curate` 按菌株实体分组，每个菌株实体只纳入一个代表性运行。默认取最新一次分析；也可以显式覆盖：

```json
{"pathogen": "VPA", "representative_dataset": {"EVO-001-P037": "EVO-001-P037__ont__20261020"}}
```

候选基线会记录 `representative_runs` 与 `superseded`，因此多数据集菌株在基线发布中不会被重复计数。

## 5. 记录：元数据、化验结果与知识库

记录是**任务**，不是直接写入。它们可审计，可从 CLI/Web/MCP（local-trusted）提交，且绝不绕过引擎。

### 元数据

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 \
  --field province=Guangdong \
  --field city=Shenzhen \
  --field sample_source=food
```

允许的字段包括 `isolation_date`、`collection_date`、`province`、`city`、`district`、
`sample_source`、`sample_type`、`food_category`、`food_name`、`outbreak_id`，以及实验室/患者
字段（D4）。未知键会被拒绝。`sample_id` 默认等于 `strain_id`。

### 化验结果

```bash
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L \
  --interpretation S --method broth_microdilution --lab "Provincial CDC"
```

用 `bio_query_lab_results`（local-trusted）或 Records 页面查询它们。

### 知识库

```bash
bacmap record knowledge-import --title "V. parahaemolyticus O3:K6 outbreak" \
  --authors "Zhang et al." --year 2024 --identifier PMID:12345678 \
  --content "cgMLST cluster ..." --entry-kind literature

bacmap record knowledge-approve 7
```

导入的条目先暂存（`approved_by IS NULL`）。只有已审核条目才可被引用；审核只记录一次，无法被覆盖。
write 任务的引用门会消费已审核的 PMID 与 DOI。

## 6. 外部数据集（mine 输入）

`mine` 任务可以读取本地文件/目录而不复制它们。引擎会：

1. 解析路径、遍历目录、计算每个文件的 SHA-256 与清单哈希；
2. 按清单哈希对相同内容去重；
3. 在 `gom.sqlite`（`datasets` 表）中登记该数据集，连同数据分级、来源路径以及
   dev/inode/mtime；
4. 将其只读挂载进沙箱（`/input/<dataset_id>`）。

`mine` 只有作为经人确认的计划的一部分才会被接受；没有 CLI 快捷方式：

```json
{"tasks": [{
  "task_type": "mine",
  "objective": "summarise the supplied TSV files",
  "script": "import json,pathlib; ...",
  "input_paths": ["/data/run42/analysis"],
  "input_data_class": "D3"
}]}
```

工作区的 `context.json` 把数据集 ID 映射到沙箱内路径：

```json
{"datasets": {"ds-0123456789abcdef": "/input/ds-0123456789abcdef"}}
```

校验完整性：

```bash
# MCP / tool call (local-trusted)
bio_inspect_dataset {"dataset_id": "ds-0123456789abcdef", "verify": true}
```

原始文件必须留在原处；零拷贝登记记录的是它的身份，而不是副本。源文件被移动/删除后，校验时会变成
`missing`。

## 7. 身份出现在哪里

| 产物 | 身份 |
|---|---|
| `samples.tsv` | 数据集 ID 与菌株实体 |
| `results/runs/<task_id>/<dataset>/` | 某个数据集的一次执行 |
| `analysis_runs.strain_ids` | 该次运行中分析的数据集 ID |
| GOM `ANALYSIS` 对象 | `analysis:<dataset>:<run_id>` |
| 菌株索引 | 每个数据集一行（最新分析胜出） |
| 基线发布 | 每个菌株实体代表一行 |
| `approvals` / 事件 | 任务/计划 + 人工操作者 |

正是这种分离，使得“同一个菌株被测序两次”不会覆盖结果，也使得基线能把该菌株只计一次。
