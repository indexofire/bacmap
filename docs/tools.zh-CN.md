# bacmap 工具参考

[English](tools.md) | **简体中文**

`bacmap.tools.registry` 中的工具注册表是 bacmap 能力的唯一清单。每个条目是一个 `ToolSpec`，带名称、版本、描述、effect 与信任层。同一个事实来源同时供给 MCP 服务器与内置智能体。本页记录全部 26 个注册工具，当前版本统一为 0.1.0。

每个工具都标注 effect。`read` 工具只做只读查询；`compute` 工具执行计算或封装外部程序，不写持久状态；`write` 工具会写 GOM 或数据库，绝不直接注册进 MCP。MCP 服务器暴露 23 个 read/compute 工具，外加两个任务工具 `bacmap_submit_task` 与 `bacmap_task_status`。经这一对工具提交任务，就是写操作唯一入口。只读模式（`bacmap mcp --read-only`）下连任务工具也不会注册。

信任层标记调用方的自主程度：L1 是固定管线，只调用、不改写；L2 是受控探索，经沙箱执行并接受人审；L3 是自由对话，受门约束。26 个工具按 effect 分为 9 个 read、14 个 compute、3 个 write。三个 write 工具是 `bio_analyze_pathogen`、`bio_add_lab_result` 与 `bio_add_metadata`。

## 概览

| 工具 | 效果 | 用途 |
| --- | --- | --- |
| bio_add_lab_result | write | 记录样本的湿实验结果（AST、血清学、生化、PCR） |
| bio_add_metadata | write | 新增或更新菌株背景与流行病学元数据 |
| bio_align | compute | 将 reads 比对到参考基因组（BWA-MEM、minimap2、STAR） |
| bio_analyze_pathogen | write | 对样本运行完整病原分析流水线 |
| bio_blast | compute | 对 NCBI 或本地 subject 文件运行 BLAST 搜索 |
| bio_cgmlst | compute | 将样本 cgMLST 谱与本地参考库比对溯源 |
| bio_diagnose | read | 从 Snakemake 日志或 stderr 诊断流水线失败 |
| bio_fastq_qc | compute | FASTQ 质量控制，输出精简 JSON 报告 |
| bio_gene_scan | compute | 扫描 contigs，检测耐药、毒力、血清型或质粒基因 |
| bio_generate_report | write | 生成含结果与证据链的 HTML 报告 |
| bio_get_result | read | 获取已完成样本的分析摘要 |
| bio_inspect_dataset | read | 列出或查看已登记的可沙箱访问数据集 |
| bio_list_reference_genomes | read | 列出参考基因组及其供给状态 |
| bio_list_samples | read | 列出全部样本及其分析状态 |
| bio_query_lab_results | read | 查询样本的湿实验结果 |
| bio_query_metadata | read | 按流行病学条件查询菌株背景元数据 |
| bio_review_flags | read | 列出标记待人工复核的 NLI Reflector 审计事件 |
| bio_samtools | compute | 封装常用 samtools 操作（SAM/BAM/FASTA） |
| bio_search_samples | read | 按血清型、MLST ST、耐药基因、物种或关键词检索菌株 |
| bio_seq_convert | compute | 在多种格式间转换序列文件 |
| bio_seq_ops | compute | 执行序列操作：翻译、ORF 查找、k-mer 计数等 |
| bio_seq_stats | compute | 计算序列文件的统计信息 |
| bio_snp_tree | compute | 获取队列 SNP 树与成对 SNP 距离 |
| bio_variant | compute | 变异检测与操作（call、filter、query、annotate、consensus） |
| bio_verify_result | compute | 对结果运行确定性校验，可选 NLI 反思 |

## 工具详情

### bio_add_lab_result

版本 `v0.1.0` | effect: `write` | 信任层: `L3`

记录样本的湿实验结果（AST 药敏、血清学、生化、PCR）。用户要录入表型数据（如纸片扩散结果、MIC 值或经典血清分型结果）时使用。

**参数**

- `strain_id` *(必填)*: `string`。菌株/样本标识符。
- `category` *(必填)*: `string`。检测类别：`ast`、`serology`、`biochemical`、`pcr`。
- `test_name` *(必填)*: `string`。检测名称（如 Ampicillin、O antigen、oxidase）。
- `result` *(必填)*: `string`。原始结果值（如 16、O4、positive）。
- `interpretation`: `string`。判读：S、I、R、positive、negative。
- `method`: `string`。所用方法（broth_microdilution、disk_diffusion、antiserum）。
- `unit`: `string`。单位（ug/mL、mm）。

### bio_add_metadata

版本 `v0.1.0` | effect: `write` | 信任层: `L3`

新增或更新菌株背景元数据（患者姓名、年龄、分离日期、省份、暴发 ID 等）。记录已存在则更新，不存在则新建。用户要记录或修改样本的流行病学信息时使用。

**参数**

- `strain_id` *(必填)*: `string`。菌株/样本标识符。
- `data` *(必填)*: `object`。要设置的元数据字段。核心字段：`patient_name`、`patient_age`、`patient_gender`、`isolation_date`、`province`、`city`、`sample_source`、`outbreak_id`。自定义字段存入 extra JSON。

### bio_align

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

将测序 reads 比对到参考基因组。封装 BWA-MEM（短读长 DNA）、minimap2（长读长、RNA-seq）或 STAR（RNA-seq 剪接感知）。需要安装对应工具。首次使用时为参考基因组建索引。默认产出排序并建好索引的 BAM。下游 SAM/BAM 操作请用 bio_samtools。

**参数**

- `aligner` *(必填)*: `string`，enum `bwa-mem|minimap2|star`。选择哪个比对器。
- `reference` *(必填)*: `string`。参考基因组 FASTA 路径（需要时会自动建索引）。
- `reads` *(必填)*: `array`。reads 文件：单端 1 个，双端 2 个。
- `output_bam` *(必填)*: `string`。输出 BAM 路径（默认排序并建索引）。
- `preset`: `string`。minimap2 preset：map-pb、map-ont、splice 等（仅 minimap2）。
- `read_type`: `string`，enum `short|long`。用于自动选择比对器的读类型：'long' 将 FASTQ 路由到 minimap2，'short' 路由到 BWA-MEM。省略时自动从 FASTQ 探测读长。
- `extra_args`: `string`。原样传给比对器的额外 CLI 参数。

### bio_analyze_pathogen

版本 `v0.1.0` | effect: `write` | 信任层: `L1`

运行完整病原分析流水线（QC、组装、经 invA/uidA/ipaH 三基因路由的物种鉴定、MLST、血清分型、耐药 AMR、毒力、质粒、DEC 致病型、报告）。适用于 Salmonella、DEC（E. coli）、Shigella、EIEC；物种路由自动完成。返回结果摘要。流水线使用与排障指引请读取 MCP prompt bacmap_role_analyst。

**参数**

- `sample_id` *(必填)*: `string`。samples.tsv 中的样本 ID。
- `cores`: `integer`。CPU 核数（默认 8）。

### bio_blast

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

运行 BLAST 搜索。两种模式：(1) 'remote' 查询 NCBI BLAST API（需要联网，无需本地数据库）；(2) 'local' 对用户提供的 subject 文件运行本地 makeblastdb+blastn/blastp 流程（需要安装 blast+ CLI）。用于序列鉴定与同源发现。

**参数**

- `mode` *(必填)*: `string`，enum `remote|local`。'remote'（NCBI）或 'local'（blast+ CLI）。
- `query` *(必填)*: `string`。查询：原始序列，或 query_is_file=true 时的 FASTA 文件路径。
- `query_is_file`: `boolean`。为 true 时 'query' 是文件路径。
- `program`: `string`，enum `blastn|blastp|blastx|tblastn|tblastx`。BLAST 程序（默认 blastn）。
- `database`: `string`。远程模式为 NCBI 数据库名（nt、nr、refseq_rna、swissprot 等）；本地模式为 subject FASTA 文件路径。
- `expect`: `number`。E 值阈值（默认 10）。
- `max_hits`: `integer`。最多报告的命中数（默认 10）。
- `output_file`: `string`。可选：将表格化 BLAST 输出写到此处。

### bio_cgmlst

版本 `v0.1.0` | effect: `compute` | 信任层: `L1`

将单株的 cgMLST 等位基因谱与本地参考库比对溯源（EnteroBase HierCC 约定，Hamming 等位基因距离，任一方缺失即剔除）。返回 top-N 最近参考株、分物种判定（outbreak/related/unrelated/undetermined）、所用阈值及注意事项（如 S. sonnei 的 HC5/HC10 不可靠，V. parahaemolyticus 未经验证）。当用户问两株是否属于同一暴发簇，或要为样本寻找最近的参考菌株时，用它做高分辨率溯源。需要先跑过 cgMLST 分型并入库（bio_analyze_pathogen 已覆盖）；尚无谱时先调用 bio_analyze_pathogen。cgMLST 阈值解读请读取 MCP prompt bacmap_role_analyst。

**参数**

- `sample_id` *(必填)*: `string`。要溯源 cgMLST 谱的样本 ID。

### bio_compare_runs

版本 `v0.1.0` | effect: `compute` | 信任层: `L1`

比较同一样本的两次分析运行（ADR-18）。逐字段比对运行记录——解析后参数、参考数据库、工具版本、环境锁、输入文件哈希、工作流提交——并比对两次运行的结果汇总，把差异归因到类别（parameters / databases / tools / inputs / workflow）。返回判定：`IDENTICAL`（来源与结果均一致）、`DIFF_ATTRIBUTED`（来源不同，差异已归因）、`NOT_REPRODUCIBLE`（来源完全相同但结果不同——告警不可复现）。用于回答"同一样本为何结果不同"，或确认可复现性。

**参数**

- `sample_id` *(必填)*: `string`。要比较两次运行的样本/菌株 ID。
- `run_a` *(必填)*: `string`。第一个 `run_id`（来自 `analysis_runs` 表）。
- `run_b` *(必填)*: `string`。第二个 `run_id`。

### bio_diagnose

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

解析 Snakemake 日志，诊断流水线失败原因。返回错误类型、根因、受影响的规则与建议的恢复命令。分析失败或用户报告流水线错误时使用。覆盖 OOM、锁冲突、缺工具、缺数据库、缺输入文件、磁盘满及 Snakemake 版本问题。

**参数**

- `log_path`: `string`。Snakemake 日志文件路径。省略时自动读取最新日志。
- `stderr_text`: `string`。要诊断的原始 stderr 文本（log_path 的替代）。

### bio_fastq_qc

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

FASTQ 文件质量控制：逐碱基质量统计、接头污染检查、重复率估计与长度分布。输出精简 JSON 报告。完整图形报告请经 shell 使用 FastQC；本工具无需外部软件即可快速分诊。

**参数**

- `files` *(必填)*: `array`。一个或多个 FASTQ 文件路径。
- `sample_reads`: `integer`。为提速抽样至最多 N 条 reads（0 = 全部，默认 100000）。
- `adapter_file`: `string`。可选，接头序列 FASTA，用于污染检查。
- `report_file`: `string`。可选：除 JSON 外，在此处另写一份 markdown 报告。

### bio_gene_scan

版本 `v0.1.0` | effect: `compute` | 信任层: `L1`

将组装后的 contigs 对基因数据库（card/vfdb/ecoh/plasmidfinder/resfinder）扫描，检测耐药 AMR、毒力、血清型或质粒基因。返回含基因列表、一致性、覆盖度的 JSON。支持一次调用扫描多个数据库。耐药基因临床意义（ESBL/碳青霉烯酶/AmpC）解读请读取 MCP prompt bacmap_role_analyst。

**参数**

- `contigs_path` *(必填)*: `string`。组装 contigs FASTA 路径。
- `database` *(必填)*: `string`。数据库名：card、vfdb、ecoh、plasmidfinder、resfinder、ncbi、megares、victors、ecoli_vf。多库可用逗号分隔。
- `min_identity`: `number`。最低一致性百分比（默认 80）。
- `min_coverage`: `number`。最低覆盖度百分比（默认 80）。

### bio_generate_report

版本 `v0.1.0` | effect: `write` | 信任层: `L1`

生成包含全部结果、校验器输出与证据链的 HTML 报告。返回文件路径。报告已随 analyze 任务自动生成，本工具用于按需重新生成。注意：effect 为 `write`（工具会向 `results/` 写入 HTML/PDF 文件），故**不经 MCP 暴露**——按需重新生成请走 CLI/TUI/Web 任务页（冻结规则 5：MCP 只暴露 read/compute 工具）。

**参数**

- `sample_id` *(必填)*: `string`。样本 ID。

### bio_get_result

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

获取已完成样本的分析摘要。返回物种（Salmonella/E.coli/Shigella）、MLST ST、血清型、ipaH 状态、DEC 致病型、耐药/毒力/质粒基因计数。结果解读请读取 MCP prompt bacmap_role_analyst。

**参数**

- `sample_id` *(必填)*: `string`。样本 ID。

### bio_inspect_dataset

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

列出或查看登记给沙箱访问的数据集——用户给定的本地路径，由 `mine` 任务的 `input_paths` 零拷贝登记（含 SHA256）。省略 `dataset_id` 时列出全部已登记数据集；给出 `dataset_id` 时返回文件清单、清单 SHA256 与沙箱挂载点。把 `dataset_id` 传给 `sandbox_run` 即可在沙箱内读取该数据。

**参数**

- `dataset_id`: `string`。已登记数据集 id（省略则列出全部）。
- `verify`: `boolean`。重算 SHA256 检测内容变化（默认 false）。

### bio_list_reference_genomes

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

列出 accession 清单（`workflow/config/reference_accessions.yaml`）中的参考基因组及其**供给状态**：各 cohort 组的 NCBI accession、预期输出文件、是否已取回、是否登记进 `refs/manifest.json`，以及联网工作站上的**取回命令**。SNP/cgMLST cohort 运行前，或用户询问如何补/换参考基因组时使用。

**参数**

- `group`: `string`。可选，按 cohort 组名过滤（如 `salmonella`）。

### bio_list_samples

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

列出全部样本及其分析状态。

**参数**：无

### bio_query_lab_results

版本 `v0.1.0` | effect: `read` | 信任层: `L3`

查询样本的湿实验结果（AST 药敏、经典血清学、生化试验、PCR）。支持按样本、category、test_name、result、interpretation 过滤。用户问表型结果、药敏检测或血清学发现时使用。

**参数**

- `sample_id`: `string`。要查询的菌株 ID（可选）。省略时返回全部结果。
- `category`: `string`。按类别过滤：`ast`、`serology`、`biochemical`、`pcr`、`pfge`。
- `test_name`: `string`。按检测名称过滤（如 Cefotaxime、Ciprofloxacin、O-antigen）。
- `result`: `string`。按结果值过滤（如 >=8、Positive、Negative）。
- `interpretation`: `string`。按判读过滤：R（耐药）、S（敏感）、I（中介）、positive、negative。

### bio_query_metadata

版本 `v0.1.0` | effect: `read` | 信任层: `L3`

从 strain_metadata 表查询菌株背景元数据（患者信息、分离详情、暴发关联）。支持按省份、outbreak_id、sample_source、日期范围过滤。用户问样本背景、流行病学信息或暴发调查时使用。

**参数**

- `strain_id`: `string`。要查询的具体菌株 ID（可选）。
- `province`: `string`。按省份过滤。
- `outbreak_id`: `string`。按暴发 ID 过滤。
- `sample_source`: `string`。按样本来源过滤（clinical/food/environment）。
- `isolation_date_from`: `string`。日期范围起点（YYYY-MM-DD）。
- `isolation_date_to`: `string`。日期范围终点（YYYY-MM-DD）。

### bio_review_flags

版本 `v0.1.0` | effect: `read` | 信任层: `L1`

从 GOM 列出 Layer 3 NLI Reflector 审计事件（nli_reflected）：哪些样本被 AI 解读自检标记，含矛盾率、阈值与被反驳的论断。这是人审回读入口。用户问哪些样本需要复核、AI 错在哪里，或要追查被标记样本的审计轨迹时使用。

**参数**

- `limit`: `integer`。最多返回的事件数（默认 50，最新在前）。

### bio_samtools

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

封装常用 samtools 操作：sort、index、view（过滤/区域）、depth、flagstat、mpileup、faidx、idxstats。需要安装 samtools。任何 SAM/BAM 文件操作都可用本工具。

**参数**

- `operation` *(必填)*: `string`，enum `sort|index|view|depth|flagstat|mpileup|faidx|idxstats|fasta_index`。要运行的 samtools 子命令。
- `input` *(必填)*: `string`。主输入文件（BAM/SAM/FASTA）。
- `output`: `string`。输出文件路径（适用时）。
- `region`: `string`。'view' 的基因组区域（如 'chr1:1000-5000'）。
- `flags`: `string`。samtools view 过滤参数（如排除未比对的 '-F 4'、'-q 30'）。
- `extra_args`: `string`。原样传给 samtools 的额外参数。

### bio_search_samples

版本 `v0.1.0` | effect: `read` | 信任层: `L3`

跨全部已入库样本结果搜索，按血清型、MLST ST、耐药基因、物种或自由文本关键词检索菌株。支持多字段 AND 查询（如 serotype=Typhimurium AND amr_gene=blaCTX-M-15）。用于溯源："找出血清型相同的全部菌株"、"哪些菌株携带基因 X"。

**参数**

- `query`: `string`。自由文本搜索（兜底）。经 FTS5 检索物种、strain_id、血清型、MLST、耐药基因。
- `serotype`: `string`。血清型精确匹配（如 Typhimurium、Enteritidis）。
- `mlst_st`: `string`。MLST ST 号（如 ST19、19）。归一化为 ST 前缀。
- `amr_gene`: `string`。耐药基因名，精确匹配（如 blaCTX-M-15、tet(A)）。
- `organism`: `string`。物种名，子串匹配（如 Salmonella、E.coli）。
- `limit`: `integer`。最大结果数（默认 50）。

### bio_seq_convert

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

在多种格式间转换序列文件：FASTA、FASTQ、GenBank、EMBL、NEXUS、PhylIP、Stockholm、Clustal、GFF。在运行要求特定输入格式的工具前使用。

**参数**

- `input_file` *(必填)*: `string`。输入序列文件。
- `output_file` *(必填)*: `string`。输出文件路径。
- `output_format` *(必填)*: `string`，enum `fasta|fastq|genbank|embl|nexus|phylip|stockholm|clustal|gff`。目标格式。

### bio_seq_ops

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

执行序列操作：反向互补、翻译、GC-skew、motif 搜索、ORF 查找、酶切位点检测、k-mer 计数。作用于序列字符串或已加载文件中的某条记录。用于临时序列分析，不必动用比对工具。

**参数**

- `operation` *(必填)*: `string`，enum `reverse_complement|translate|gc_content|gc_skew|motif_search|find_orfs|restriction_sites|kmer_count`。要执行的操作。
- `sequence`: `string`。原始序列（DNA 或 RNA）。'translate' 用 DNA；除非给定 'frame'，密码子从位置 0 开始读。
- `file`: `string`。可选：从此文件读取序列，代替 'sequence'。
- `record_id`: `string`。给定 'file' 时，指定操作该文件中的哪条记录。
- `motif`: `string`。'motif_search' 用：IUPAC motif 模式（如 'GANTC'）。
- `frame`: `integer`，enum `0|1|2`。'translate' 的读码框（默认 0）。
- `min_orf_len`: `integer`。'find_orfs' 的最小 ORF 长度，单位密码子（默认 30）。
- `k`: `integer`。'kmer_count' 的 k（默认 3）。
- `top`: `integer`。'kmer_count' 返回前 N 个结果（默认 20）。
- `output_file`: `string`。可选：将完整结果（如全部 ORF/k-mer）写到此处。

### bio_seq_stats

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

计算序列文件（FASTA、FASTQ 或 GenBank）的统计信息。返回计数（记录数、总碱基数）、长度分布（min/max/mean/N50）与 GC 含量。FASTQ 额外给出逐碱基质量与 Q 值分布。任何测序分析的第一步，先摸清输入数据。

**参数**

- `file` *(必填)*: `string`。序列文件的绝对或相对路径。
- `format`: `string`，enum `fasta|fastq|genbank|auto`。文件格式。'auto' 按扩展名探测（默认）。
- `histogram_bins`: `integer`。长度/质量直方图的分箱数（默认 20）。

### bio_snp_tree

版本 `v0.1.0` | effect: `compute` | 信任层: `L1`

获取队列级 SNP 系统发育树与成对距离矩阵。返回 Newick 树字符串、样本列表、SNP 位点数、缺失率与全部成对 SNP 距离。用户问遗传相关性、暴发簇、系统发育关系或样本间 SNP 距离时使用。SNP 距离解读阈值（0-5=暴发，6-15=可能相关）请读取 MCP prompt bacmap_role_analyst。

**参数**：无

### bio_variant

版本 `v0.1.0` | effect: `compute` | 信任层: `L2`

变异检测与操作。操作：'mpileup_call'（从 BAM 经 bcftools mpileup+call 检测变异）、'filter'（bcftools 按质量/深度过滤）、'query'（bcftools query 提取字段）、'annotate'（添加 VCF 注释）、'consensus'（bcftools consensus 将变异应用到参考序列）。需要安装 bcftools 和/或 samtools。

**参数**

- `operation` *(必填)*: `string`，enum `mpileup_call|filter|query|annotate|consensus`。要执行的变异操作。
- `input` *(必填)*: `string`。输入文件（检测用 BAM，过滤/query/注释用 VCF）。
- `output`: `string`。输出文件路径。
- `reference`: `string`。参考 FASTA（mpileup_call、consensus 必需）。
- `query`: `string`。bcftools query 格式串（如 '%CHROM\t%POS\t%REF\t%ALT\n'）。
- `filter_expr`: `string`。bcftools 过滤表达式（如 'QUAL>30 && DP>10'）。
- `extra_args`: `string`。原样传给 bcftools 的额外参数。

### bio_verify_result

版本 `v0.1.0` | effect: `compute` | 信任层: `L1`

对结果运行确定性校验。检查物种、MLST、血清型、耐药 AMR。将关键耐药（CTX-M/NDM/KPC/mcr-1）标记给人工复核。可选传入 interpretation_text（你对该样本的解读草稿），同时运行 Layer 3 NLI Reflector：文本中的论断会与样本事实核对，矛盾率高时标记 NEEDS_HUMAN_REVIEW。理解校验规则请读取 MCP prompt bacmap_role_analyst。

**参数**

- `sample_id` *(必填)*: `string`。样本 ID。
- `interpretation_text`: `string`。可选，用于与样本事实比对的 LLM 解读文本（Layer 3 NLI Reflector）。

---

规范来源：`bacmap.tools.registry` 的运行时注册表。它是工具名称、版本、effect、信任层与参数 schema 的权威记录。注册表变更时，请重新生成本文档。
