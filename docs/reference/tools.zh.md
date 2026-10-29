# bacmap 工具参考


`bacmap.tools.registry` 中的工具注册表是 bacmap 能力的唯一目录。每个条目是一个 `ToolSpec`，包含名称、版本、描述、效果与信任层。单一事实来源同时供给 MCP 服务器与调用工具处理器的各接口。本页记录全部 26 个已注册工具；它们当前都处于 0.1.0 版本。

每个工具都带有一种效果标签。`read` 工具查询已存储的结果。`compute` 工具运行分析或包装外部二进制程序，但不写入持久状态。`write` 工具会修改 GOM 或数据库，因此它们从不直接注册进 MCP。MCP 服务器暴露 22 个读/计算工具，以及任务工具 `bacmap_submit_task`、`bacmap_task_status`、`bacmap_task_result` 与 `bacmap_task_cancel`（v1.5.2），计划工具 `bacmap_create_plan`、`bacmap_revise_plan` 与 `bacmap_get_plan`，`bacmap_record_data`（仅 local-trusted，v1.8.4），以及 `bacmap_confirm_plan_locally`（stdio 对话框，v1.9.0）。任务只能通过任务提交，或在 bacmap CLI/Web 中确认的计划进入引擎；不存在由模型确认的工具。在只读模式（`bacmap mcp --read-only`）下，连任务工具也不会注册。从 v1.5 起，每个 MCP 实例还会按其 **Profile** 裁剪（ADR-12/16）：默认的 `cloud` Profile 只暴露输出数据分级不高于 `cloud_max_data_class` 的读/算工具（默认 D1，因此只有 `bio_list_reference_genomes` 与 `bio_diagnose`；计划/任务/能力工具另行注册），而 `local-trusted`（管理员显式选择加入）暴露全部 22 个读/算工具。见[智能体与计划](../guide/agent-plans.zh.md)。

信任层标记调用层拥有多少自主权：L1 是固定流水线，只能调用，不能改写；L2 是在沙箱中受控探索，并有人工复核；L3 是门之后的自由对话。26 个工具分为 9 个读、13 个计算与 4 个写。四个写工具是 `bio_analyze_pathogen`、`bio_generate_report`、`bio_add_lab_result` 与 `bio_add_metadata`。

## 调用工具

MCP 客户端把单个 JSON 对象作为工具参数传入（形状与下文的 `parameters`
小节相同）。示例：

```json
// bio_get_result
{"sample_id": "SAM-001"}

// bio_search_samples
{"serotype": "Typhimurium", "amr_gene": "blaCTX-M-15", "limit": 20}

// bio_compare_runs
{"sample_id": "SAM-001", "run_a": "4f2c...", "run_b": "9a31..."}

// bio_inspect_dataset
{"dataset_id": "ds-0123456789abcdef", "verify": true}
```

内部调用方（CLI、Web、任务步骤）使用相同的处理器契约：
`handler(args: dict) -> str`，返回 JSON 字符串。错误为 `{"error": "..."}`，只含
异常类型；完整细节保留在日志中。

## 摘要

| 工具 | 效果 | 用途 |
| --- | --- | --- |
| bio_add_lab_result | write | 记录样本的湿实验检测结果（AST、血清学、生化、PCR） |
| bio_add_metadata | write | 添加或更新菌株背景与流行病学元数据 |
| bio_align | compute | 将读段比对到参考基因组（BWA-MEM、minimap2、STAR） |
| bio_analyze_pathogen | write | 对样本运行完整的病原菌分析流水线 |
| bio_blast | compute | 针对 NCBI 或本地目标文件运行 BLAST 搜索 |
| bio_cgmlst | compute | 将样本的 cgMLST 谱型对照本地参考库进行追溯 |
| bio_diagnose | read | 从 Snakemake 日志或 stderr 诊断流水线故障 |
| bio_fastq_qc | compute | 对 FASTQ 文件做质量控制，输出紧凑的 JSON 报告 |
| bio_gene_scan | compute | 扫描 contig 中的 AMR、毒力、血清型或质粒基因 |
| bio_generate_report | write | 生成包含结果与证据链的 HTML 报告 |
| bio_get_result | read | 获取已完成样本的分析摘要 |
| bio_inspect_dataset | read | 列出或查看为沙箱访问注册的数据集 |
| bio_list_reference_genomes | read | 列出参考基因组及其就绪状态 |
| bio_list_samples | read | 列出所有样本及其分析状态 |
| bio_query_lab_results | read | 查询样本的湿实验检测结果 |
| bio_query_metadata | read | 使用流行病学过滤条件查询菌株背景元数据 |
| bio_review_flags | read | 列出被标记为需人工复核的 NLI Reflector 审计事件 |
| bio_samtools | compute | 包装常见的 SAM/BAM/FASTA 文件 samtools 操作 |
| bio_search_samples | read | 按血清型、MLST ST、AMR 基因、物种或关键词查找菌株 |
| bio_seq_convert | compute | 在多种格式之间转换序列文件 |
| bio_seq_ops | compute | 执行翻译、ORF 查找、k-mer 计数等序列操作 |
| bio_seq_stats | compute | 计算序列文件的统计信息 |
| bio_snp_tree | compute | 获取队列 SNP 树与两两 SNP 距离 |
| bio_variant | compute | 对变异进行检出、过滤、查询、注释或构建一致性序列 |
| bio_verify_result | compute | 对结果运行确定性验证，可选 NLI 反思 |

## 工具详情

### bio_add_lab_result

版本 `v0.1.0` | 效果：`write` | 信任层：`L3`

记录样本的湿实验检测结果（AST、血清学、生化、PCR）。当用户想要录入表型数据（例如纸片扩散结果、MIC 值或经典血清分型结果）时使用。

**参数**

- `strain_id` *（必填）*：`string`。菌株/样本标识符。
- `category` *（必填）*：`string`。检测类别：`ast`、`serology`、`biochemical`、`pcr`。
- `test_name` *（必填）*：`string`。检测名称（例如 Ampicillin、O antigen、oxidase）。
- `result` *（必填）*：`string`。原始结果值（例如 16、O4、positive）。
- `interpretation`：`string`。S、I、R、positive、negative。
- `method`：`string`。所用方法（broth_microdilution、disk_diffusion、antiserum）。
- `unit`：`string`。单位（ug/mL、mm）。

### bio_add_metadata

版本 `v0.1.0` | 效果：`write` | 信任层：`L3`

添加或更新菌株背景元数据（患者姓名、年龄、分离日期、省份、暴发 ID 等）。创建新记录或更新现有记录。当用户想要记录或修改样本的流行病学信息时使用。

**参数**

- `strain_id` *（必填）*：`string`。菌株/样本标识符。
- `data` *（必填）*：`object`。要设置的元数据字段。核心字段：`patient_name`、`patient_age`、`patient_gender`、`isolation_date`、`province`、`city`、`sample_source`、`outbreak_id`。自定义字段存放在 extra JSON 中。

### bio_align

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

将测序读段比对到参考基因组。包装 BWA-MEM（短读长 DNA）、minimap2（长读长、RNA-seq）或 STAR（RNA-seq 剪接感知）。需要安装相应工具。首次使用时为参考基因组建立索引。默认产出排序并建索引的 BAM。下游 SAM/BAM 操作请使用 bio_samtools。

**参数**

- `aligner` *（必填）*：`string`，枚举 `bwa-mem|minimap2|star`。使用哪种比对器。
- `reference` *（必填）*：`string`。参考基因组 FASTA 的路径（如需要会建立索引）。
- `reads` *（必填）*：`array`。读段文件：单端为 1 个，双端为 2 个。
- `output_bam` *（必填）*：`string`。输出 BAM 路径（默认排序并建索引）。
- `preset`：`string`。minimap2 预设：map-pb、map-ont、splice 等（仅 minimap2）。
- `read_type`：`string`，枚举 `short|long`。用于自动选择比对器的读段类型：'long' 把 FASTQ 路由到 minimap2，'short' 路由到 BWA-MEM。省略时从 FASTQ 自动探测读长。
- `extra_args`：`string`。原样传给比对器的额外 CLI 参数。

### bio_analyze_pathogen

版本 `v0.1.0` | 效果：`write` | 信任层：`L1`

运行完整的病原菌分析流水线（QC、组装、经 gside 做物种鉴定、经 gmlst 做 MLST/cgMLST、经 gapit 做筛查/血清分型、AMR/毒力/质粒、报告）。物种路由是自动的，并遵循病原体注册表。返回结果摘要。流水线指引与故障排查请阅读 MCP 提示词 bacmap_role_analyst。

**参数**

- `sample_id` *（必填）*：`string`。来自 samples.tsv 的样本 ID。
- `cores`：`integer`。CPU 核数（默认 8）。

### bio_blast

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

运行 BLAST 搜索。两种模式：(1) 'remote' 查询 NCBI BLAST API（需要互联网，无需本地数据库）；(2) 'local' 针对用户提供的目标文件运行本地的 makeblastdb+blastn/blastp 流水线（需要安装 blast+ CLI）。用于序列鉴定与同源发现。

**参数**

- `mode` *（必填）*：`string`，枚举 `remote|local`。'remote'（NCBI）或 'local'（blast+ CLI）。
- `query` *（必填）*：`string`。查询序列：原始序列，或当 query_is_file=true 时的 FASTA 文件路径。
- `query_is_file`：`boolean`。若为 true，'query' 是文件路径。
- `program`：`string`，枚举 `blastn|blastp|blastx|tblastn|tblastx`。BLAST 程序（默认 blastn）。
- `database`：`string`。远程：NCBI 数据库名（nt、nr、refseq_rna、swissprot 等）。本地：目标 FASTA 文件路径。
- `expect`：`number`。E-value 阈值（默认 10）。
- `max_hits`：`integer`。报告的最大命中数（默认 10）。
- `output_file`：`string`。可选：把表格形式的 BLAST 输出写入此处。

### bio_cgmlst

版本 `v0.1.0` | 效果：`compute` | 信任层：`L1`

将单个样本的 cgMLST 等位基因谱型对照本地参考库进行追溯（EnteroBase HierCC 约定、Hamming 等位基因距离、任一侧缺失则排除）。返回最近的 top-N 参考株、每个物种的判定（outbreak/related/unrelated/undetermined）、所应用的阈值，以及任何注意事项（例如 S. sonnei 的 HC5/HC10 不可靠、V. parahaemolyticus 为 UNVERIFIED）。当用户询问两个菌株实体是否属于同一暴发簇，或需要为样本找到最近的参考株时，用于高分辨率溯源。要求已运行并入库 cgMLST 分型（bio_analyze_pathogen 覆盖此项）；若尚无谱型，请先调用 bio_analyze_pathogen。cgMLST 阈值解读请阅读 MCP 提示词 bacmap_role_analyst。

**参数**

- `sample_id` *（必填）*：`string`。需要追溯其 cgMLST 谱型的样本 ID。

### bio_compare_runs

版本 `v0.1.0` | 效果：`compute` | 信任层：`L1`

把同一样本的两次分析运行相互比较（ADR-18）。它逐字段比较运行记录——已解析参数、参考数据库、工具版本、环境锁、输入文件哈希与工作流提交——并比较每次运行的结果摘要，然后把差异归因到某一类（parameters / databases / tools / inputs / workflow）。返回判定：`IDENTICAL`（来源与结果均一致）、`DIFF_ATTRIBUTED`（来源不同，差异已归因）或 `NOT_REPRODUCIBLE`（来源相同但结果不同——提示存在不可复现的运行）。用于回答“为什么同一样本得到不同结果”，或确认可复现性。

**参数**

- `sample_id` *（必填）*：`string`。要比较其两次运行的样本/菌株 ID。
- `run_a` *（必填）*：`string`。第一个 `run_id`（来自 `analysis_runs` 表）。
- `run_b` *（必填）*：`string`。第二个 `run_id`。

### bio_diagnose

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

通过解析 Snakemake 日志诊断流水线故障。返回错误类型、根因、受影响的规则与建议的恢复命令。当分析失败或用户报告流水线错误时使用。处理 OOM、锁冲突、工具缺失、数据库缺失、输入文件缺失、磁盘已满与 Snakemake 版本问题。

**参数**

- `log_path`：`string`。Snakemake 日志文件的路径。省略时自动读取最新日志。
- `stderr_text`：`string`。要诊断的原始 stderr 文本（作为 log_path 的替代）。

### bio_fastq_qc

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

对 FASTQ 文件做质量控制：逐碱基质量统计、接头污染检查、重复率估计与长度分布。输出紧凑的 JSON 报告。需要完整图形化报告时可通过 shell 使用 FastQC，但本工具无需外部工具即可快速分诊。

**参数**

- `files` *（必填）*：`array`。一个或多个 FASTQ 文件路径。
- `sample_reads`：`integer`。为提速最多抽样 N 条读段（0 = 全部，默认 100000）。
- `adapter_file`：`string`。可选的接头序列 FASTA，用于检查污染。
- `report_file`：`string`。可选：除 JSON 外，还在此写入 markdown 报告。

### bio_gene_scan

版本 `v0.1.0` | 效果：`compute` | 信任层：`L1`

将组装好的 contig 对照基因数据库（card/vfdb/ecoh/plasmidfinder/resfinder）扫描，以检测 AMR、毒力、血清型或质粒基因。返回包含基因列表、一致度、覆盖度的 JSON。支持一次调用扫描多个数据库。AMR 基因的临床意义（ESBL/碳青霉烯酶/AmpC）请阅读 MCP 提示词 bacmap_role_analyst。

**参数**

- `contigs_path` *（必填）*：`string`。组装 contig FASTA 的路径。
- `database` *（必填）*：`string`。数据库名称：card、vfdb、ecoh、plasmidfinder、resfinder、ncbi、megares、victors、ecoli_vf。或用逗号分隔以扫描多个数据库。
- `min_identity`：`number`。最低一致度百分比（默认 80）。
- `min_coverage`：`number`。最低覆盖度百分比（默认 80）。

### bio_generate_report

版本 `v0.1.0` | 效果：`write` | 信任层：`L1`

生成包含全部结果、验证器输出与证据链的 HTML 报告。返回文件路径。每个 analyze 任务结束时本就会自动生成报告；使用本工具可按需重新生成。注意：效果为 `write`（工具会在 `results/` 下写入 HTML/PDF 文件），因此它**不通过 MCP 暴露**——请改为通过 CLI/TUI/Web 的任务页面重新生成（冻结规则 5：MCP 只暴露读/计算工具）。

**参数**

- `sample_id` *（必填）*：`string`。样本 ID。

### bio_get_result

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

获取已完成样本的分析摘要。返回物种类型（Salmonella/E.coli/Shigella）、MLST ST、血清型、ipaH 状态、DEC 致病型、AMR/毒力/质粒基因计数。结果解读请阅读 MCP 提示词 bacmap_role_analyst。

**参数**

- `sample_id` *（必填）*：`string`。样本 ID。

### bio_inspect_dataset

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

列出或查看为沙箱访问注册的数据集——用户提供的本地路径，由 `mine` 任务的 `input_paths` 以零拷贝方式携带 SHA256 注册。不带 `dataset_id` 时列出所有已注册数据集；带 `dataset_id` 时返回文件清单、清单 SHA256 与沙箱挂载点。`mine` 任务会把这些数据集以只读方式挂载；工作区 `context.json` 把每个 `dataset_id` 映射到沙箱内路径。

**参数**

- `dataset_id`：`string`。已注册的数据集 id（省略以列出全部）。
- `verify`：`boolean`。重新计算 SHA256 以检测变化（默认 false）。

### bio_list_reference_genomes

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

列出 accession 清单（`workflow/config/reference_accessions.yaml`）中的参考基因组及其就绪状态：每个 cohort 组的 NCBI accession、预期输出文件、是否已取回、是否已登记到 `refs/manifest.json`，以及在联网工作站上应执行的确切取回命令。用于 SNP/cgMLST 队列运行之前，或当用户询问如何添加或刷新参考基因组时。

**参数**

- `group`：`string`。可选的 cohort 组名过滤（例如 `salmonella`）。

### bio_list_samples

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

列出所有样本及其分析状态。

**参数**：无
### bio_query_lab_results

版本 `v0.1.0` | 效果：`read` | 信任层：`L3`

查询样本的湿实验检测结果（AST 药敏、经典血清学、生化试验、PCR）。支持按样本、类别、test_name、result 与 interpretation 过滤。当用户询问表型结果、抗生素耐药检测或血清学发现时使用。

**参数**

- `sample_id`：`string`。要查找的菌株 ID（可选）。省略时返回所有结果。
- `category`：`string`。按类别过滤：`ast`、`serology`、`biochemical`、`pcr`、`pfge`。
- `test_name`：`string`。按检测名称过滤（例如 Cefotaxime、Ciprofloxacin、O-antigen）。
- `result`：`string`。按结果值过滤（例如 >=8、Positive、Negative）。
- `interpretation`：`string`。按判读过滤：R（耐药）、S（敏感）、I（中介）、positive、negative。

### bio_query_metadata

版本 `v0.1.0` | 效果：`read` | 信任层：`L3`

从 strain_metadata 表查询菌株背景元数据（患者信息、分离详情、暴发关联）。支持按 province、outbreak_id、sample_source 与日期范围过滤。当用户询问样本背景、流行病学信息或暴发调查时使用。

**参数**

- `strain_id`：`string`。要查找的特定菌株 ID（可选）。
- `province`：`string`。按省份过滤。
- `outbreak_id`：`string`。按暴发 ID 过滤。
- `sample_source`：`string`。按样本来源过滤（clinical/food/environment）。
- `isolation_date_from`：`string`。日期范围起点（YYYY-MM-DD）。
- `isolation_date_to`：`string`。日期范围终点（YYYY-MM-DD）。

### bio_review_flags

版本 `v0.1.0` | 效果：`read` | 信任层：`L1`

列出 GOM 中 Layer 3 NLI Reflector 的审计事件（nli_reflected）：哪些样本被 AI 解读自检标记，以及矛盾率、阈值与被反驳的主张。这是供人工复核的回读界面。当用户询问哪些样本需要复核、AI 判断错在哪里，或需要追溯某个被标记样本的审计轨迹时使用。

**参数**

- `limit`：`integer`。返回的最大事件数（默认 50，最新优先）。

### bio_samtools

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

包装常见的 samtools 操作：sort、index、view（过滤/区域）、depth、flagstat、mpileup、faidx、idxstats。需要安装 samtools。用于任何 SAM/BAM 文件操作。

**参数**

- `operation` *（必填）*：`string`，枚举 `sort|index|view|depth|flagstat|mpileup|faidx|idxstats|fasta_index`。要运行的 samtools 子命令。
- `input` *（必填）*：`string`。主输入文件（BAM/SAM/FASTA）。
- `output`：`string`。输出文件路径（适用时）。
- `region`：`string`。'view' 的基因组区域（例如 'chr1:1000-5000'）。
- `flags`：`string`。samtools view 参数（例如 '-F 4' 排除未比对读段、'-q 30'）。
- `extra_args`：`string`。原样传给 samtools 的额外参数。

### bio_search_samples

版本 `v0.1.0` | 效果：`read` | 信任层：`L3`

在所有已入库的样本结果中搜索，按血清型、MLST ST、AMR 基因、物种或自由文本关键词查找菌株。支持多字段 AND 查询（例如 serotype=Typhimurium AND amr_gene=blaCTX-M-15）。用于溯源：'find all strains with same serotype' 或 'which strains carry gene X'。

**参数**

- `query`：`string`。自由文本搜索（回退）。通过 FTS5 搜索物种、strain_id、血清型、MLST、AMR 基因。
- `serotype`：`string`。精确匹配血清型（例如 Typhimurium、Enteritidis）。
- `mlst_st`：`string`。MLST ST 编号（例如 ST19、19）。会归一为 ST 前缀。
- `amr_gene`：`string`。AMR 基因名，精确匹配（例如 blaCTX-M-15、tet(A)）。
- `organism`：`string`。物种名，子串匹配（例如 Salmonella、E.coli）。
- `limit`：`integer`。最大结果数（默认 50）。

### bio_seq_convert

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

在格式之间转换序列文件：FASTA、FASTQ、GenBank、EMBL、NEXUS、PhylIP、Stockholm、Clustal、GFF。在运行需要特定输入格式的工具之前很有用。

**参数**

- `input_file` *（必填）*：`string`。输入序列文件。
- `output_file` *（必填）*：`string`。输出文件路径。
- `output_format` *（必填）*：`string`，枚举 `fasta|fastq|genbank|embl|nexus|phylip|stockholm|clustal|gff`。目标格式。

### bio_seq_ops

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

执行序列操作：反向互补、翻译、GC-skew、基序搜索、ORF 查找、限制性位点检测、k-mer 计数。可作用于序列字符串，或已加载文件中的记录 ID。用于不调用比对工具的临时序列分析。

**参数**

- `operation` *（必填）*：`string`，枚举 `reverse_complement|translate|gc_content|gc_skew|motif_search|find_orfs|restriction_sites|kmer_count`。要执行的操作。
- `sequence`：`string`。原始序列（DNA 或 RNA）。'translate' 请使用 DNA；除非给出 'frame'，否则从位置 0 开始读取密码子。
- `file`：`string`。可选：从此文件读取序列，而不是使用 'sequence'。
- `record_id`：`string`。若给出 'file'，则操作该特定记录。
- `motif`：`string`。用于 'motif_search'：IUPAC 基序模式（例如 'GANTC'）。
- `frame`：`integer`，枚举 `0|1|2`。'translate' 的阅读框（默认 0）。
- `min_orf_len`：`integer`。'find_orfs' 的最小 ORF 长度（以密码子计，默认 30）。
- `k`：`integer`。'kmer_count' 的 k（默认 3）。
- `top`：`integer`。'kmer_count' 返回前 N 个结果（默认 20）。
- `output_file`：`string`。可选：把完整结果（例如全部 ORF/k-mer）写入此处。

### bio_seq_stats

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

计算序列文件（FASTA、FASTQ 或 GenBank）的统计信息。返回计数（记录数、总碱基数）、长度分布（min/max/mean/N50）与 GC 含量。对 FASTQ 还会给出逐碱基质量分数与 Q-score 分布。任何测序分析的第一步都可用它来了解输入数据。

**参数**

- `file` *（必填）*：`string`。序列文件的绝对或相对路径。
- `format`：`string`，枚举 `fasta|fastq|genbank|auto`。文件格式。'auto' 从扩展名推断（默认）。
- `histogram_bins`：`integer`。长度/质量直方图的分箱数（默认 20）。

### bio_snp_tree

版本 `v0.1.0` | 效果：`compute` | 信任层：`L1`

获取队列级 SNP 系统发育树与两两距离矩阵。返回 Newick 树字符串、样本列表、SNP 位点数、缺失率与所有两两 SNP 距离。当用户询问遗传相关性、暴发簇、系统发育关系或样本间 SNP 距离时使用。SNP 距离解读阈值（0-5=暴发，6-15=可能相关）请阅读 MCP 提示词 bacmap_role_analyst。

**参数**：无

### bio_variant

版本 `v0.1.0` | 效果：`compute` | 信任层：`L2`

检出或操作变异。操作：'mpileup_call'（从 BAM 执行 bcftools mpileup+call）、'filter'（按质量/深度执行 bcftools filter）、'query'（用 bcftools query 提取字段）、'annotate'（添加 VCF 注释）、'consensus'（用 bcftools consensus 把变异应用到参考序列）。需要 bcftools 和/或 samtools。

**参数**

- `operation` *（必填）*：`string`，枚举 `mpileup_call|filter|query|annotate|consensus`。要执行的变异操作。
- `input` *（必填）*：`string`。输入文件（检出用 BAM，过滤/查询/注释用 VCF）。
- `output`：`string`。输出文件路径。
- `reference`：`string`。参考 FASTA（mpileup_call、consensus 必填）。
- `query`：`string`。bcftools query 格式字符串（例如 '%CHROM\t%POS\t%REF\t%ALT\n'）。
- `filter_expr`：`string`。bcftools filter 表达式（例如 'QUAL>30 && DP>10'）。
- `extra_args`：`string`。原样传给 bcftools 的额外参数。

### bio_verify_result

版本 `v0.1.0` | 效果：`compute` | 信任层：`L1`

对结果运行确定性验证。检查物种、MLST、血清型、AMR。标记关键耐药（CTX-M/NDM/KPC/mcr-1）以供人工复核。可选传入 interpretation_text（你对样本的解读草稿），以同时运行 Layer 3 NLI Reflector：文本中的主张会对照样本事实检查，矛盾率高时会标记 NEEDS_HUMAN_REVIEW。了解验证规则请阅读 MCP 提示词 bacmap_role_analyst。

**参数**

- `sample_id` *（必填）*：`string`。样本 ID。
- `interpretation_text`：`string`。可选的 LLM 解读文本，用于对照样本事实进行反思（Layer 3 NLI Reflector）。

---

规格来源：`bacmap.tools.registry` 中的运行时注册表。它是工具名称、版本、效果、信任层与参数 schema 的权威记录。注册表变更时，请重新生成本文档。
