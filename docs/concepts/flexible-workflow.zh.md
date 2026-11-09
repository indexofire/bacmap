# 弹性工作流架构（PLAN #5）

> 状态：设计提案（2026-11-09）；平台探测与长读/混合组装规则已在 0.1.5 落地。

## 问题

固定 Snakemake 流程在常规监测中可复现、可审计，但对临时性分析需求（如"这批
样本加一个毒力筛查"或"用不同组装器试一下"）缺乏弹性。智能体和大模型的优势
恰恰在于理解和拆解这类非标准需求。

## 方案：两层弹性模型

```
┌─────────────────────────────────────────────────────────┐
│ 固定层（常规监测）                                        │
│ ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│ │ registry │──→│ smk 规则 │──→│  gates  │──→│  GOM    │ │
│ │(pathogens│   │(确定性)  │   │(门/审计) │   │(证据链)  │ │
│ │ .yaml)   │   │          │   │          │   │          │ │
│ └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│                                                          │
│  ✓ 可复现  ✓ 可审计  ✓ 任何人跑出同一结果                  │
├─────────────────────────────────────────────────────────┤
│ 弹性层（临时分析）                                        │
│ ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│ │ 智能体   │──→│ AI 生成  │──→│ 人工审核 │──→│ mine    │ │
│ │ (理解需求)│   │ smk+参数 │   │ (确认)   │   │ 沙箱执行 │ │
│ └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│                                                          │
│  ✓ 灵活  ✓ 智能体参与  ✓ 人工把关  ✓ 一次性归档            │
└─────────────────────────────────────────────────────────┘
```

### 固定层（不变）

- **registry 驱动**：`pathogens.yaml` 登记物种 → 通用 `species.smk`/`gspec_typing.smk`
  等规则自动路由。新物种 = 登记 yaml 条目，零规则代码。
- **确定性管线**：gside（物种）→ flye/spades（组装）→ gspec（分型）→ gmlst（MLST）
  → verifier → 报告。每步可复现、有 hash。
- **门与审计**：analysis_claims 门、STROBE checklist、G0–G3 发表门。

### 弹性层（AI 参与）

三条路径，按信任级别递增：

| 路径 | 智能体做什么 | 人做什么 | 执行环境 | 生命周期 |
|---|---|---|---|---|
| **A. research 计划** | 提议类型化分析（session/advstats） | 在 bacmap 确认计划 | 容器（bacmap-stats） | 结果持久化 |
| **B. mine 沙箱** | 编写自由脚本（Python/R） | 审核脚本 + 签字 | mine 沙箱（无网络） | 产物入挖掘门 |
| **C. AI 生成 smk**（新增） | 生成自定义 Snakefile + 参数 | 审核 smk 规则 + 确认 | 独立沙箱（无网络） | **一次性，运行后归档** |

#### 路径 C：AI 生成临时 smk（核心新增）

```
用户需求："这批 10 株加一个blaNDM筛查 + 用flye重新组装"
    ↓
智能体：读取 registry（确认物种）→ 生成 Snakefile + config.yaml
    ↓
bacmap：静态校验（语法/规则名/路径白名单）
    ↓
人：审核生成的 smk（完整展示在确认界面）→ 确认
    ↓
沙箱执行（无网络，输入只读挂载，输出 hash 入库）
    ↓
结果归档：smk 文件 + config + 运行日志 + 产物 hash → 一次性记录
```

**关键约束**：
- 生成的 smk 只能引用 registry 中已登记的外部工具（gside/gspec/gmlst/flye 等）
- 输入路径必须来自计划输入指纹（确认时校验）
- 运行在独立沙箱（与 mine 同构但环境含 snakemake）
- 归档后不可重跑（一次性设计——如果需要重跑，应该提升为固定层规则）

## 平台分支规则（PLAN #4）

| 检测结果 | 组装器 | 触发条件 | smk 规则 |
|---|---|---|---|
| illumina | spades/shovill（现有） | 中位读长 ≤400bp，仅有 R1/R2 | `assembly.smk` |
| nanopore | flye `--nano-hq`（R10.4.1 SUP，Q20+；旧 R9.4 可配 `--nano-raw`） | 中位读长 ≥1kb，分布宽，仅有 longread | `assembly_long.smk` |
| pacbio_hifi | flye `--pacbio-hifi` | 中位读长 ≥5kb，分布均匀，仅有 longread | `assembly_long.smk` |
| 混合（短+长） | unicycler | 同一样本同时有 R1/R2 + longread | `assembly_long.smk` |
| 特殊 | trycycler | 用户在 samples.tsv platform 列写 "trycycler"（需 R1/R2 + longread） | `assembly_long.smk` |

trycycler 需单独安装：其 conda 包目前要求 Python <3.11，而 bacmap 运行在 Python 3.12；
flye 与 unicycler 已随默认 pixi 环境安装。

探测由 `bacmap detect` 或 `task submit --fastq-dir` 自动触发（`core/fastq_probe.py`），
结果记入 samples.tsv 的 `platform` 列。用户可在 samples.tsv 的 `platform` 列覆盖
探测结果（`ont` / `pacbio_hifi`）。

### samples.tsv 新增列（0.1.5）

```
sample    species    R1       R2       longread              assembly    platform
SAMP-001  SAL        ...      ...                            (空)        illumina
SAMP-002  VPA        (空)     (空)     /path/ont_reads.fq    (空)        nanopore
SAMP-003  VPA        ...      ...      /path/ont_reads.fq    (空)        ont
SAMP-004  ECO        (空)     (空)                            .../fna     (空)
```

- `longread`：长读 FASTQ 路径（自动检测或手动填写）
- `platform`：测序平台（`ont`/`pacbio_hifi`/`illumina`/`trycycler`，自动探测可覆盖）

## 资源仲裁（PLAN #10）

当 `[llm.resources] co_located = true`：
- Snakemake `--cores` 自动减去 LLM 预留核数（默认预留 4 核，可配置）
- LLM 推理期间（检测到活跃连接），管线降核运行
- LLM 空闲时，管线恢复全核

当 `co_located = false`（推荐）：
- LLM 在 GPU 服务器（`location = "lan"` 或 `"cloud"`）
- 生信在 x86_64 服务器全速运行
- 无冲突

## 下一步实施（按优先级）

1. ✅ FASTQ 平台探测（`core/fastq_probe.py`，已实现）
2. ✅ samples.tsv `platform` 列（可手工覆盖探测结果；无独立 CLI 开关）
3. 路径 C：`research` 计划新增 `analysis=custom_smk`（生成→审核→沙箱→归档）
4. ✅ flye/unicycler/trycycler smk 规则（新 `rules/assembly_long.smk`）
5. 资源仲裁逻辑（`co_located=true` 时自动降核）
