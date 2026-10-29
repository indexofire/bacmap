# 任务与门

**任务**是 bacmap 改变状态的唯一途径。任务引擎执行五种任务类型，记录每一步，施加门（gate），
并保留不可变的证据轨迹。各界面只负责提交任务；它们从不直接写存储。

## 1. 五种任务类型

| 类型 | 用途 | 输入形态 | 典型终态 |
|---|---|---|---|
| `analyze` | 对数据集运行固定的 Snakemake 管线 | `samples`、`fasta_dir`、`fastq_dir` 之一 | `succeeded`；若分析结论门标记了某段文本，则为 `awaiting_approval` |
| `curate` | 构建本地流行病学基线候选 | 可选的 `scope` | `awaiting_approval`（发布门 + 签名） |
| `mine` | 在无网络的沙箱中运行用户/智能体的 Python 脚本 | `objective`、`script`，可选 `input_paths` | `awaiting_approval`（挖掘门 + 签名） |
| `write` | 用本地知识库对稿件/报告草稿做门控校验 | `objective`、`draft`、`known_citations` | `awaiting_approval`；遇到未知引用则为 `failed` |
| `record` | 元数据、化验结果、知识库导入/审批 | `kind` + 各字段 | `succeeded` / `failed` |

**封闭路径**：`analyze` 与 `curate` 运行固定的 DAG/算法。**开放路径**：`mine` 与 `write`
携带必须由人审阅的代码/文本；它们只能以经人确认的计划形式被接受。

## 2. 任务状态

```text
pending ──► running ──► succeeded
                │
                ├──► failed
                ├──► cancelled
                └──► awaiting_approval ──► succeeded | failed
```

`pending` 存在于模型中，但提交后通常直接进入 `running`。`awaiting_approval` 表示某个门给出了
`needs approval` 的结论；必须由人签批或拒绝该任务。`tasks.sqlite` 中的任务表是真相来源；
查询时会先把 DBOS 状态对齐进来。

```bash
bacmap task list
bacmap task show <task_id> --json
bacmap task cancel <task_id>        # only non-terminal tasks
```

## 3. `analyze`

### 参数

| 字段 | 必填 | 说明 |
|---|---|---|
| `samples` | 三者之一 | 已登记的数据集 ID |
| `fasta_dir` | 三者之一 | `.fna/.fasta/.fa` 的绝对目录；逐个基因组登记 |
| `fastq_dir` | 三者之一 | 成对 `*_R1/_R2`（或 `*_1/_2`）reads 的绝对目录 |
| `species` | 仅与目录同用 | 代码或名称；FASTA 省略时用 gside 自动识别；FASTQ 默认 `UNK` |
| `cores` | 否 | Snakemake 核数，默认 8 |
| `interpretation_text` | 否 | 仅内部/引擎层使用：由分析结论门校验的可选文本；不是 CLI/计划字段，也不会自动生成 |

只允许一种输入形态。`samples` 与目录互斥；`species` 不能与 `samples` 组合使用。

### 示例

```bash
# Registered datasets
bacmap task submit --type analyze --samples SAM-TYP-001,SAM-TYP-002

# Assembled genomes: scan, register and analyse; species detected per genome
bacmap task submit --type analyze --fasta-dir /data/genomes

# Reads: paired files, known species
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

作为 MCP 计划：

```json
{
  "tasks": [
    {"task_type": "analyze", "fasta_dir": "/data/genomes", "species": "VPA"}
  ],
  "rationale": "batch 42, assembled genomes"
}
```

管线写入 `results/runs/<task_id>/<sample>/`。成功后，`results/<sample>` 之类的扁平路径会重新
指向该次运行。摄取、门与报告生成读取运行目录，绝不读取可变的扁平别名（v1.9.3）。

结束时，bacmap 会创建：

- 一条不可变的 `analysis_runs` 记录 + `runs/<run_id>/run_manifest.json`；
- GOM `ANALYSIS` 对象（`analysis:<sample>:<run_id>`、按样本的 cgMLST 谱、队列汇总）；
- 一行菌株索引，用于快速检索；
- 每个样本一份模板化 HTML 报告。

## 4. `curate`

`curate` 为每个 **isolate（菌株实体）** 选择一个代表性运行，检查纳入标准，从构造上移除 D4
字段，然后保存一个候选基线。发布需要发布门和人的签名。

```bash
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task show <task_id>          # awaiting_approval when the gate passes
bacmap task approve <task_id> --approver "Jane" --decision approve --signature "jd-2026-10-30"
```

范围字段：

| 字段 | 含义 |
|---|---|
| `pathogen` | 物种子串过滤（例如 `Salmonella`） |
| `strains` | 显式的数据集或菌株实体 ID |
| `representative_dataset` | `{"<isolate>": "<dataset>"}`，用于覆盖默认的最新运行 |

选择细节：

- 分组键取自 samples.tsv 的 `isolate`（缺省时回落到数据集 ID）；
- 默认代表为摘要 mtime 最新者，并以稳定的规则打破平局；
- 候选记录 `representative_runs` 与 `superseded`；被排除的菌株实体带有原因；
- 纳入要求物种受支持，且有 QC 数据、分离日期、地区与来源；
- `representative_dataset` 中的拼写错误会报为 `representative_dataset_missing` /
  `representative_isolate_missing`，而不是被静默忽略。

计划示例：

```json
{"tasks": [{"task_type": "curate", "scope": {"pathogen": "Vibrio parahaemolyticus"}}]}
```

## 5. `mine`

`mine` 让智能体用自定义 Python 分析**已经产出**的数据。脚本在无网络的容器内运行；宿主输入路径
以零拷贝方式登记并以只读挂载。

参数（计划中可用的那些）：

| 字段 | 必填 | 说明 |
|---|---|---|
| `objective` | 是 | 1–500 个字符；脚本应当产出什么 |
| `script` | 是 | 完整 Python 源码，≤20,000 个字符；计入计划哈希 |
| `input_paths` | 否 | 要登记并以只读挂载的绝对文件/目录 |
| `sandbox_image` | 否 | 默认 `docker://python:3.12-slim` |
| `input_data_class` | 否 | `D2`、`D3`（默认）或 `D4` |

脚本从其工作区读取 `context.json`：

```json
{
  "backend": "apptainer",
  "results_dir": "/data/results",
  "gom_db": "/data/gom.sqlite",
  "datasets": {
    "ds-0123456789abcdef": "/input/ds-0123456789abcdef"
  }
}
```

`datasets` 是一个**对象**，把数据集 ID 映射到路径。一个最小脚本：

```python
import json, pathlib, statistics

ctx = json.loads(pathlib.Path("context.json").read_text())
rows = []
for ds_id, root in ctx["datasets"].items():
    for path in pathlib.Path(root).rglob("*.tsv"):
        rows.append({"dataset": ds_id, "file": path.name, "bytes": path.stat().st_size})

out = {"n_files": len(rows), "median_bytes": statistics.median(r["bytes"] for r in rows) if rows else 0}
pathlib.Path("summary.json").write_text(json.dumps(out, indent=2))
```

工作区中创建的文件（`analysis.py` 与 `context.json` 除外）成为产物。只有在人签字之后，它们才能
通过挖掘门；未签字的产物永远不会进入报告。

## 6. `write`

`write` 对完整草稿施加**引用门**。引用只有与一条已审核的本地知识库条目（PMID 或 DOI）匹配时
才被接受。

| 字段 | 必填 | 说明 |
|---|---|---|
| `objective` | 是 | 1–500 个字符 |
| `draft` | 是 | 全文，≤40,000 个字符；计入计划哈希 |
| `known_citations` | 否 | 要接受的标识符；**空列表**表示“使用已审核知识库”。非空列表会**替换**知识库集合，因此随计划一并审阅 |

```json
{
  "tasks": [{
    "task_type": "write",
    "objective": "weekly V. parahaemolyticus brief",
    "draft": "In week 43 ... (PMID:12345678)",
    "known_citations": []
  }]
}
```

未知引用会让任务在进入审批之前就失败。如果条目只是暂存而尚未审核，请先审核它：

```bash
bacmap record knowledge-approve 12
```

## 7. `record`

记录类任务是元数据、化验结果和知识库的唯一路径。它们可审计，且从不直接修改存储。
`bacmap_record_data` **仅**在 `local-trusted` Profile 下经 MCP 暴露它们。

| 类型 | 必填 | 可选 |
|---|---|---|
| `metadata` | `strain_id`、`fields` | `sample_id` |
| `lab_result` | `strain_id`、`category`、`test_name`、`result` | unit、method、interpretation、standard、tested_date、tested_by、lab、notes |
| `knowledge_import` | `title` | authors、year、source、identifier、content、entry_kind（`literature`/`method`/`report`） |
| `knowledge_approve` | `entry_id` | — |

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L --interpretation S
bacmap record knowledge-import --title "Outbreak paper" --identifier PMID:12345678
bacmap record knowledge-approve 7
```

元数据字段受白名单限制；未知键会被拒绝。知识库审核是**一次性**的：后来的审阅者无法覆盖最初的
审核人。

## 8. 门一览

| 门 | 触发时机 | 通过条件 | 失败方式 |
|---|---|---|---|
| `analysis_claims` | analyze 结束 / `bio_verify_result` | 物种受支持，且可选的解读文本不与管线事实矛盾 | `reject` 或 `needs_human_review` |
| `baseline_release` | curate 结束 | 非空、无重复、物种/日期/地区/来源完整、无 D4 泄漏 | `reject`；不予发布 |
| `mining` | mine 结束 + 审批 | 产物非空、每个都可复现、经人签字 | `reject`；任务失败 |
| `citation` | write 结束 | 每个 PMID/DOI 都出现在已审核知识库中 | `reject`；任务失败 |

计划确认与任务审批在本表中**不是门**：它们是可信界面上的人工操作。实现细节见
[任务引擎与门](../concepts/task-engine.zh.md)。

## 9. 可复现性

每次 `analyze` 运行都会记录解析后的配置、哈希、工具版本、参考数据库版本、随机种子、工作流
commit 以及输入哈希。比较两次运行：

```bash
bacmap run list
bacmap run show <run_id>
bacmap run compare <run_a> <run_b>
```

`NOT_REPRODUCIBLE` 表示来源一致但结果不同；`DIFF_ATTRIBUTED` 表示差异可由参数/数据库/工具/输入/
工作流解释。

## 10. 取消与恢复

```bash
bacmap task cancel <task_id>
```

只有非终态任务可以取消。引擎基于 DBOS：进程挂掉后，重启会从最后一个已完成的步骤续跑工作流；
Snakemake 从 `.snakemake` 续跑。计划确认使用确定性的任务 ID，因此崩溃后重新确认不会产生第二个任务。
