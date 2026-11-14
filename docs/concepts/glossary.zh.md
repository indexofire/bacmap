# 术语表（PLAN #16）

bacmap 的核心概念定义，消歧常见混淆。

## 数据实体

| 术语 | 定义 | 示例 |
|---|---|---|
| **specimen** | 样本——唯一送检编号。一份样本可产出 0..N 个菌株，也可直接测序（mNGS/tNGS，下一大版本）。编号可为空，后续用 `bacmap specimen import` 补录。 | `A03-SN-001` |
| **isolate** | 菌株——从样本分离出的纯培养物，只属于一份样本。GOM 中有 `isolate_id`，附 lineage（谱系）和 passage（传代次数）。 | `A03-ISO-01` |
| **library** | 测序数据——一次测序文库或组装。其 ID 是 `samples.tsv` 的 `sample` 列（历史列名保留）；挂在菌株上（样本直接测序时挂在样本上）。 | `A03-ISO-01__ilm__20261012` |
| **run** | 一次分析运行的记录——包含输入文件清单、工具版本、参考数据库版本、输出目录。一个 run 覆盖多个测序数据。 | `546857e317cd...` |
| **dataset** | 已登记的外部数据（零拷贝，SHA-256 溯源）——可以是 FASTA 目录、CSV 表或任何文件。供 mine 沙箱只读挂载。 | `ds-f01a0256...` |

> **specimen vs isolate vs library**：样本是送检材料；菌株是从样本分离出的培养物
> （一份样本多株是常态）；测序数据是某个菌株的一次测序文库/组装。`samples.tsv` 的
> `sample` 列是**测序数据 ID**，`isolate`/`specimen` 列把它挂到上层实体。

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
