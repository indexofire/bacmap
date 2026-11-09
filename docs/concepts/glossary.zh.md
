# 术语表（PLAN #16）

bacmap 的核心概念定义，消歧常见混淆。

## 数据实体

| 术语 | 定义 | 示例 |
|---|---|---|
| **isolate** | 菌株分离物——一个物理实体（从一份样本分离出的纯培养物）。GOM 中有 `isolate_id`，附 lineage（谱系）和 passage（传代次数）。 | `ISO-2024-001` |
| **sample** | 一次分析的样本 ID——等于 `strain_id`，是 GOM 中菌株的标识符。一个 isolate 可以有多份 sample（不同批次/方法），但通常一一对应。 | `SAM-001` |
| **run** | 一次分析运行的记录——包含输入文件清单、工具版本、参考数据库版本、输出目录。一个 run 覆盖多个 sample。 | `546857e317cd...` |
| **dataset** | 已登记的外部数据（零拷贝，SHA-256 溯源）——可以是 FASTA 目录、CSV 表或任何文件。供 mine 沙箱只读挂载。 | `ds-f01a0256...` |

> **isolate vs sample**：在日常使用中几乎同义。技术上，isolate 强调物理实体
> （分离物），sample 强调分析单元（用于 pipeline 的输入标识）。bacmap 的
> `samples.tsv` 中 `species` 列写的就是 sample/isolate 共用的 `strain_id`。

## 任务与计划

| 术语 | 定义 | 关系 |
|---|---|---|
| **plan** | 一个**提案**——包含 1-10 个任务的版本化清单，等待人工确认（或 auto_confirm 预授权）。确认前不执行任何操作。 | 1 plan → N tasks |
| **task** | 一个**执行单元**——计划确认后自动提交，由 DBOS 引擎执行。有状态机（pending→running→succeeded/failed/awaiting_approval）。 | N tasks ← 1 plan |

> **task vs plan**：plan 是"做什么"的提案（人看），task 是"正在做/已做完"的执行
> 记录（机器管）。人确认 plan → 引擎把 plan 中的每个任务条目转为 task 并执行。

## 任务类型（六类）

| 类型 | 说明 | 执行方式 | 需人工确认 |
|---|---|---|---|
| `analyze` | 标准基因组分析（组装→分型→注释→报告） | Snakemake 管线 | 经 plan 确认 |
| `curate` | 特征库/知识库构建 | 确定性脚本 | 经 plan 确认 |
| `mine` | 智能体自定义脚本（Python/R） | 沙箱（无网络，只读挂载） | plan 确认 + 挖掘门签字 |
| `write` | 报告/论文撰写（LLM 生成 + 引用门） | 引擎内 + pydantic-ai | plan 确认 + 导出门 |
| `record` | 元数据/化验/知识库写入 | 确定性 | 直接提交（入口校验） |
| `research` | 研究分析（session/advstats） | 确定性 / 容器 | 经 plan 确认 |

## 物种命名

| 术语 | 定义 | 示例 |
|---|---|---|
| **species code** | 3 字母物种码 = 属首字母 + 种前两字母 | `VPA` = *Vibrio parahaemolyticus* |
| **gside label** | gside 鉴定工具输出的物种标签 | `V_parahaemolyticus` |
| **display name** | pathogens.yaml 中的中文显示名 | `副溶血性弧菌` |
| **snp_group** | SNP 分析的参考基因组组名 | `vpara` |

> 物种命名流转链：gside 鉴定输出 label → `species_code()` 转为 3 字母码 →
> 码是 `pathogens.yaml` 的键 → 查表获得 MLST scheme、gspec 库、参考基因组等。
> `bacmap species list` 可查看全部注册物种。

## 参考基因组

| 术语 | 定义 |
|---|---|
| **reference group** | 一组用于 SNP/系统发育分析的参考基因组（如 `salmonella` 组包含 LT2 参考株） |
| **reference manifest** | `refs/manifest.json`——记录每条参考序列的名称、版本、SHA-256（ADR-18 溯源） |
| **snp_group** | pathogens.yaml 中的分组名，指定该物种用哪个参考基因组组 |

> bacmap 管理参考基因组：`reference_accessions.yaml`（NCBI accession 清单）→
> `fetch_reference_genomes.py`（部署期下载）→ `refs/manifest.json`（运行时消费）。
> `bacmap reference list` 可查看就绪状态。
