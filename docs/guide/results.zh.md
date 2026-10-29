# 结果与证据

bacmap 把两类东西分开放：**结果文件**（按运行存放）与**证据记录**（哈希、版本、门、审批）。
要回答“我们发现了什么，而且能否证明它？”，两者缺一不可。

## 1. 按运行划分的结果布局

物理结果存放在运行目录之下：

```text
$BACMAP_HOME/results/
├── runs/
│   └── <task_id>/
│       ├── <dataset>/               # per-sample files
│       │   ├── qc/
│       │   ├── assembly/
│       │   ├── species/
│       │   ├── typing/
│       │   ├── amr/
│       │   ├── plasmid/
│       │   └── report/
│       │       ├── <dataset>_summary.json
│       │       └── <dataset>_report.html
│       ├── snp/<group>/...
│       └── cgmlst/<group>/...
├── <dataset> -> runs/<latest_task>/<dataset>
├── snp       -> runs/<latest_task>/snp
└── cgmlst    -> runs/<latest_task>/cgmlst
```

性质：

- 每次执行只写自己的 `runs/<task_id>/`；旧运行永远不会被覆盖。
- 扁平路径是指向**最新**运行的相对符号链接，用于兼容脚本与工具。
- 管线成功后，摄取、门与报告生成读取**本次运行**的目录；对同一数据集的并发分析不会污染它们
  （v1.9.3）。
- 历史扁平目录会迁移到 `runs/legacy-<name>/` 并由链接替代。新的运行也会自动迁移遗留目录。
  需要显式升级步骤时可用 `bacmap results migrate [--dry-run]`。

```bash
bacmap results migrate --dry-run
bacmap results migrate
ls -l "$BACMAP_HOME/results/SAM-TYP-001"
```

## 2. 报告

每个成功的 `analyze` 任务都会生成一份模板化 HTML 报告：

```bash
ls "$BACMAP_HOME/results/runs/<task_id>/SAM-TYP-001/report/"
# SAM-TYP-001_summary.json
# SAM-TYP-001_report.html
```

从 Web 打开它：

```text
/samples/SAM-TYP-001/report            # inline under a sandbox CSP
/samples/SAM-TYP-001/report?download=1 # attachment
```

报告是自包含的（内联样式，无外部请求），因此可以归档并离线查看。PDF 生成是可选项，需要本地转换器。

报告会在每次分析结束时自动生成。重新运行一次分析就会重新生成它们；不存在用于报告的 MCP 直接写入工具。

## 3. 运行记录（`runs.sqlite` + 清单）

每次 analyze 运行都会创建一条不可变记录：

```bash
bacmap run list
bacmap run show <run_id>
bacmap run show <run_id> --json | jq .
```

一条记录包含：

| 分组 | 字段 |
|---|---|
| 身份 | `run_id`、`task_id`、`strain_ids`、workflow/commit/dirty |
| 时间 | `started_at`、`finished_at`、`ingested_at` |
| 参数 | `resolved_config`、`config_sha256`、`seeds`、`nondeterministic_steps` |
| 输入 | `input_files`（路径 → SHA-256） |
| 环境 | `tool_versions`、`env_lock_sha256`、`host` |
| 数据库 | `ref_databases`（名称/版本/校验和） |

同样的内容会连同自哈希封存到 `$BACMAP_HOME/runs/<run_id>/run_manifest.json`。
`bacmap run compare` 比较两条记录；而清单正是审计人员可以独立重算哈希的对象。

### 比较两次运行

```bash
bacmap run compare <run_a> <run_b>
```

结论：

- `IDENTICAL`：来源与结果都一致；
- `DIFF_ATTRIBUTED`：来源不同；差异可归因于参数/数据库/工具/输入/工作流；
- `NOT_REPRODUCIBLE`：来源一致但结果不同。

## 4. GOM 对象

Genome Object Model（GOM）对象不可变；新的结果会创建新版本或新对象。

```bash
bacmap gom list --type analysis
bacmap gom show analysis:SAM-001:<run_id>
bacmap gom show <object_id> --version 2
```

对象类型包括 sample、analysis、report、workflow、plugin、knowledge 和 task。analysis 载荷包含
一个扁平摘要视图以及原始摘要：

```json
{
  "analysis_type": "sample_analysis",
  "sample_id": "SAM-001",
  "run_id": "...",
  "species_verdict": "Salmonella",
  "serotype": {"sistr": "Typhimurium"},
  "mlst": "ST19",
  "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
  "summary": {"steps": {"...": "..."}}
}
```

门的评估结果会以 `gate.<name>` 事件追加到相关对象上；任务级门（mine/write/curate）使用 `TASK`
对象。

```text
GET /api/v1/gom/objects?type=analysis&limit=20
GET /api/v1/gom/objects/<object_id>?version=2
```

## 5. 检索样本

```bash
bacmap search --query Salmonella
bacmap search --serotype Typhimurium --st 19 --gene blaCTX-M-15
bacmap sample ls
bacmap sample show SAM-001
```

Web 的 `/search` 支持自由文本以及血清型、ST 和基因过滤。`bio_search_samples` 把同一索引暴露给
MCP 客户端（D2）。本地基因型索引（`gom.sqlite` 中的 `strain_genotype_index`）为每个数据集保存
一行，由最新一次分析更新。

## 6. 证据链：简版

```text
input file ──SHA256──► run record ──run_id──► GOM ANALYSIS
                             │                     │
                             │                     ├── gate events
                             └── manifest.json     └── approvals / releases
```

- **输入**在登记/运行时被哈希。
- **参数/工具/数据库**按运行捕获。
- **结果**指向 `run_id`。
- **门**是代码检查；**审批**是人的签名。
- **基线发布**保存清单 + 签名，且只追加。

像“该菌株属于本地暴发簇”这样的结论，必须指明基线版本及其背后的运行 ID。这正是让结论可审计的原因。

## 7. 保留与备份

- `results/` 不会被自动删除；请在核对保留策略后有意清理旧运行。
- `bacmap backup` 包含数据库与运行清单；加上 `--with-results` 可包含结果文件。
- `bacmap events prune --days N` 删除旧的协调事件，不删除门审批或运行记录。
- 恢复较旧的备份也会恢复 `dbos.sqlite`，因此正在执行的任务可以继续。

备份/恢复与升级流程见[运维](../operations/index.zh.md)。
