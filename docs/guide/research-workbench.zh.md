# Research Workbench（P1）

Research Workbench 把一个已有的分析 run 转换成**可复核的研究草案**：统计、图、报告和论文骨架。
P1 刻意保持窄而确定：只做一个 AMR 关联示例，不调用 LLM，不采集新数据。

> 状态：P1 薄链路。`open-test` 下产物标记 **TEST/UNVERIFIED**，
> `research`/`publication` 下标记 **REVIEW REQUIRED**；都不是可发表结论。

## 1. 它做什么

输入：

- `runs.sqlite` 中的 `run_id`；
- `gom.sqlite` 中 `strain_amr_genes` 的基因名；
- `data/bacmap.sqlite` 中 `lab_results` 的检测名。

输出：

- 基因存在/缺失 × 耐药/敏感的 2×2 表；
- OR 与 95% CI；
- Fisher 精确检验 p 值与诊断；
- `figure.svg`、`report.md`、`manuscript.md`；
- `research.sqlite` 中的 session、stat、artifact、ledger 记录。

```text
$BACMAP_HOME/research/<session_id>/
├── figure.svg
├── report.md
└── manuscript.md
```

## 2. 它不做什么

- 不做因果/机制结论；
- 不做 lineage/群体结构校正（P2）；
- 不做外部队列/验证（P2）；
- 不用 LLM 生成文本（P1 是确定性）；
- 不标记 publication-ready；
- 不发起新测序或新数据入库。

## 3. CLI

```bash
bacmap research list

# open-test 草案（TEST/UNVERIFIED）
bacmap research create \
  --run-id 9a31c2... \
  --gene blaKPC-33 \
  --test-name meropenem \
  --profile open-test

bacmap research show rs-0123456789ab
bacmap research artifact rs-0123456789ab report
bacmap research artifact rs-0123456789ab manuscript
```

`--json` 输出机器可读结果。`BACMAP_RESEARCH_PROFILE` 设置默认 Profile；安全默认是
`research`，`open-test` 用于开发。

P2 对象生命周期也可从 CLI 操作（参数接受 JSON 或文件）：

```bash
bacmap research study create --question "blaKPC 是否与 meropenem 耐药相关？" --pathogen KPN
bacmap research cohort create --study <study_id> --members cohort_members.json --name discovery
bacmap research cohort freeze <cohort_id>
bacmap research plan create --study <study_id> --cohort <cohort_id> \
  --spec '{"run_id":"...","gene":"blaKPC","test_name":"meropenem"}'
bacmap research plan freeze <plan_id>
bacmap research experiment record --plan <plan_id> --status success --run-id <run_id>
bacmap research claim create --study <study_id> --type association \
  --wording "blaKPC 与 meropenem 耐药相关" --level E2
bacmap research claim review <claim_id> --decision approve
bacmap research publication <study_id>
```

`cohort create` 接受 OSF fixture 的 `{"members": [...]}` 形式。发表检查会列出每个门的
blockers；`ready=true` 仍需人工评审。

## 4. Web

运行 `bacmap start web` 后打开 **研究 / Research**。Web 是主要的结果查看界面：

1. 从下拉框选择 run（没有 run 时才手填 `run_id`）；
2. 填基因/表型、选择治理 Profile，可选关联 Study/Cohort/Plan，并填写研究说明；
3. session 页显示 2×2 表、诊断、标准图与自定义图、`FigureSpec`、自定义图 provenance
   manifest，以及带 SHA-256 的可下载产物；
4. Study 页显示 G0–G3、带缩略图的关联 session、STROBE 草案（met/partial/missing）和
   投稿包入口；
5. 研究首页还提供 **系统发育规划**（`/research/phylo`：profile → plan → BEAST2 XML /
   IQ-TREE 命令）与 **Logistic 回归**（`/research/stats`：CSV/TSV → OR/CI/p 表）；
6. Study 页还提供 **Cohort builder**：用复选框选择 run/样本，预览重复 isolate/dataset 与
   缺失 run，然后直接创建 cohort，不必手写 members JSON；
7. session 页还有 **Figure 迭代** gallery：上传草稿、保存反馈、最终 attach 或拒绝；
8. session 页安全渲染 report/manuscript Markdown（原始 HTML 转义）；
9. Study 页与 `/research/studies/{id}/packages` 保存**投稿包历史**：每次构建记录
   package_id、label、created_at、文件数、blockers 与 manifest SHA-256；可查看
   manifest/checklist 或下载 ZIP；
10. 投稿包页显示 manifest、checklist、文件与数据/代码可用性，并提供 ZIP 下载。

自然语言研究指令由外部 agent 经 MCP 处理（Pi/Hermes/DSH）；agent 可读取研究对象并提议
下一步，写入目前仍在 Web/CLI/API。Web 保持为人工审核与结果查看界面。

## 5. JSON API

```bash
TOKEN=...
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/capabilities | jq .

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"run_id":"9a31...","gene":"blaKPC-33","test_name":"meropenem","profile":"open-test"}' \
  http://127.0.0.1:8800/api/v1/research/sessions | jq .

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/sessions/<session_id> | jq .
```

完整端点见 [Research API](../reference/research-api.zh.md)。

## 6. MCP

MCP Profile 允许 D2 时暴露：

- `bacmap_research_capabilities`
- `bacmap_research_sessions`
- `bacmap_research_session`

`cloud`（D1）只拿到 capabilities；session 内容是 D2，不注册。研究写入当前不暴露为 MCP
工具，创建走 CLI/Web/API。

## 7. 治理 Profile

| Profile | 状态 | 标签 | 含义 |
|---|---|---|---|
| `open-test` | `complete_test` | `TEST/UNVERIFIED` | 快速开发；自动通过的测试产物 |
| `research` | `review_required` | `REVIEW REQUIRED` | 使用前应人工复核 |
| `publication` | `review_required` | `REVIEW REQUIRED` | P1 尚未实现发表门 |

`open-test` **不会**放宽 D3/D4 数据边界，只放宽本确定性 P1 管线的产物审批。

## 8. 证据与限制

session ledger 记录创建时的 run、gene、test、profile。统计表与诊断可由命名 run 加本地
GOM/化验库复现。P2 核心对象（Study → Cohort → AnalysisPlan → Claim）已可通过 API 使用：

- `POST /api/v1/research/studies`
- `POST /api/v1/research/cohorts` + `/{id}/freeze`
- `POST /api/v1/research/plans` + `/{id}/freeze`
- `POST /api/v1/research/claims` + `/{id}/review`
- `POST /api/v1/research/cohorts/preview`（重复/缺失 run）
- `POST /api/v1/research/plans/{id}/run`（P1 AMR 配方）
- `POST /api/v1/research/experiments`（成功/失败/阴性/偏离账本）
- `GET /api/v1/research/studies/{id}/publication-readiness`（G0–G3）
- `POST /api/v1/research/claims/from-session`（会话 → association Claim）
- `GET /api/v1/research/benchmarks/amr`（L0 合成基准）
- `GET /api/v1/research/benchmarks/bvbrc-amr`（L1 真实数据基准）
- `GET /api/v1/research/benchmarks/osf-cohort`（L2 队列/表型摘要）
- `GET /api/v1/research/benchmarks/verify?dataset=...`（SHA-256 + 行数校验）

Cohort 必须先冻结才能建计划；计划带确定性哈希；Claim 记录类型、证据等级与审核状态。
Claim 审核有最低等级/措辞门（association E2、transmission E3+时间/流调、causal E3+设计、
mechanism E4+功能证据）。Web `/research/studies/{id}` 页面列出该研究的 cohort/plan/claim。

统计层同时提供：

- Benjamini–Hochberg FDR 多重比较校正（`benjamini_hochberg`）；
- Mantel–Haenszel 分层合并 OR 与 Greenland–Robins CI（`mantel_haenszel`）；
- 稀疏格子诊断，以及 Intermediate/零格子的显式处理。

每次实际执行可记录为 **Experiment**（`success`/`failed`/`negative`/`deviated`），绑定冻结
计划哈希；偏离必须写说明。Experiment 追加式写入，并进入 ledger。`publication-readiness`
评估四个确定性门：

| 门 | 要求 |
|---|---|
| G0 | 已冻结 Cohort + 已冻结 Plan，且哈希有效 |
| G1 | 至少一个 supported/approved Claim；approved Claim 通过等级/措辞门；无未处理的 challenged Claim |
| G2 | Study 与关联 session 均为 D0–D2 |
| G3 | 至少一个 success/negative Experiment，计划哈希匹配且有 run ID |

过门是必要条件，**不是充分条件**：仍需人工发表评审，且 P2 尚不包含投稿包导出器。

### 真实数据科学基准

仓库只带**代码与清单**，不带数据。公开快照放在
`$BACMAP_HOME/benchmarks/<dataset>/`（或设置 `BACMAP_BENCHMARK_DATA`）：

| 层级 | 数据集 | 验证什么 |
|---|---|---|
| L0 | 合成 2×2 | OR/CI/Fisher/BH 正确性 |
| L1 | BV-BRC *K. pneumoniae* / meropenem | 真实基因型–表型关联回归、混杂识别 |
| L2 | OSF n78q3 暴发 + colistin | 表型缺失、队列构成、阴性结果处理 |

用 `bacmap research benchmark amr|bvbrc|osf|verify-bvbrc|verify-osf` 或 API 运行。
L1 刻意保留 CTX-M 作为**负相关/混杂示例**：crude OR 小于 1 不能被改写成保护机制。
L2 报告 37.6% 的 colistin 表型覆盖率，并保留原研究的 GWAS 阴性结果。

这些是观察性 L1/L2 基准，不是金标准因果真值，不能支持因果、机制或传播 Claim。

### 真实队列敏感性分析

BV-BRC L1 基准现在同时报告 crude 与 Mantel–Haenszel 分层调整估计（按现有最精确元数据
`geo_loc_name` → `isolation_source` → `testing_standard` 分层），以及留一层敏感性和 E-value。
当前快照结果：

| 靶点 | Crude OR | MH OR (95% CI) | 留一范围 |
|---|---:|---|---|
| OXA-48 | 4.03 | 2.48 (1.60–3.85) | 1.89–2.96 |
| KPC | 113.7 | 33.9 (21.1–54.5) | 26.2–36.6 |
| NDM | 28.0 | 7.87 (4.97–12.47) | 4.93–8.33 |
| CTX-M | 0.70 | 0.71 (0.56–0.91) | 0.53–0.94 |

KPC/NDM 在分层后明显衰减，说明 crude 估计受混杂影响；CTX-M 仍为负，保留为反例，
不能解释成保护机制。

### 暴发与散在事件挖掘

`research/outbreak.py` 按**已记录**的地点 + 日期精度聚类，并对“聚集 vs 散在”、研究来源、
谱系做分类关联挖掘。它不调用变异、不建树、不推断传播方向。OSF n78q3（176 个有表型事件）：

- 71 个上下文聚类；145 个事件聚集，31 个散在；
- 来源挖掘出现强研究效应（如 Pitt OR 11.4、BH q 0.0016；UHL OR 0.35、q 0.0031），
  这是**采样/来源混杂**，不是生物学结论；
- 传播 Claim 仍需外部分型 + 时间/流调证据。

```bash
bacmap research outbreak --events dev/benchmark-data/osf_n78q3/outbreak_events.json
bacmap research sensitivity --table 70,60,30,20 \
  --strata '[["A",30,20,5,2],["B",25,25,10,8],["C",15,15,15,10]]'
```

### P3 候选探索（第一片）

`research/discovery.py` 在显式预算下对 screening 关联排序。它拒绝确认性数据，不创建 Claim，
每个候选都标注需要独立确认。评分综合 FDR、效应量和样本量，并记录停止原因。

```bash
bacmap research explore --study study-... --cases cases.json \
  --max-tests 200 --max-candidates 20 --min-n 20 --max-q 0.05
```

这是 P3 的起点，不是完整自动探索：Explorer/Verifier/Critic 编排、对抗陷阱和持久化候选账本
仍待建设。

## 9. 设计边界

P1 复用：

- `runs.sqlite`：run 成员；
- `gom.sqlite::strain_amr_genes`：基因型；
- `data/bacmap.sqlite::lab_results`：表型；
- `research.sqlite`：研究对象；
- 现有 Web/API/MCP/CLI/DBOS 边界。

不改变 GOM、Snakemake、DBOS 或五类任务。

## 10. 发表级图片


### R/Python 运行时

Recipe 声明自己在哪里运行；分析过程中不要临时安装 R/Python 包。

| 运行时 | 适用 | 方式 |
|---|---|---|
| `builtin` | SVG/确定性 recipe | 在 bacmap 内运行 |
| `container` | R/ggtree、matplotlib、seaborn | Apptainer/Podman 镜像（`bacmap-figures:r4`、`bacmap-figures:py312`） |
| `pixi` | 离线/无容器机器 | 可选的 `figures` pixi 环境，包版本固定 |
| `host` | 仅开发 | 现有 `Rscript`/Python；不可复现 |

检查可用性：

```bash
bacmap research figure runtimes
```

容器镜像是可复现的默认方案：镜像 digest 随产物记录。主 bacmap 环境保持精简；R 与绘图库
不会变成分析流水线的运行时依赖。如果 recipe 需要镜像中没有的包，把它加入镜像构建并升级
recipe 版本——绝不在运行时 `install.packages()`。

### 用示例图迭代

用户可以指向一篇论文的图或描述版式。Agent 不得复制图片，而是把风格提取为
`FigureSpec.style` 中的 **style brief**：

- `journal`：目标期刊或空；
- `panel_layout`：`single`、`2x2`、`top-bottom` 等；
- `palette_colors`：用户明确要求时的 hex 值；
- `reference_note`：人工描述（“Lancet 风格森林图，无网格线”）；
- `width_mm`、`height_mm`、`dpi`、`font_family`、`font_size_pt`。

循环是：`FigureSpec` + style brief + recipe → 渲染草稿 → 用户反馈 → 更新 brief/recipe 参数
→ 重新渲染。草稿作为中间产物记录；只有确认后的图才按 hash 登记。参考图本身绝不进入仓库，
也不由 bacmap 再分发。


### Recipe 库

创建 session 时关联 study/cohort/plan，figure spec 与投稿包才能带上完整来源链：

```bash
bacmap research create --run-id run-1 --gene blaKPC-33 --test-name meropenem \
  --profile research --study <study_id> --cohort <cohort_id> --plan <plan_id>
```

`bacmap research figure recipes` 列出版本化 recipe。只有状态为 `stable`/`experimental`
且带 entrypoint 的 recipe 才可执行；`planned` 只记录路线图，绝不假装已运行。

| Recipe | 语言 | 状态 | 用途 |
|---|---|---|---|
| `association_bar` | SVG | stable | P1 2×2 关联条形图 |
| `forest` | Python/matplotlib | planned | 效应量 + 95% CI |
| `heatmap` | Python/matplotlib+seaborn | planned | 带注释矩阵 |
| `pca` | Python/matplotlib | planned | 排序图 |
| `volcano` | Python/matplotlib | planned | 效应 vs FDR |
| `tree_rectangular` | R/ggtree | planned | 渲染 Newick 树 |
| `strobe_flow` | SVG | planned | 队列流程图 |
| `custom` | Python | experimental | 沙箱中的 agent 自定义兜底 |

规则：

1. 有稳定 recipe 能表达结果时，优先用 recipe；
2. `tree_rectangular` 只负责渲染；建树（IQ-TREE/Gubbins、模型、bootstrap、生根）是独立的
   工作流步骤，绝不是 AI 临时写脚本；
3. `planned` recipe 尚不可用，不得假装已运行；
4. 没有合适 recipe 时才用 `custom` 沙箱脚本，并按 hash 登记；
5. 不要复制论文中的图。已发表图只能作为人工提供的风格参考；把想法翻译成 recipe/spec，
   绝不复现原图。


图片与统计遵循同一条规则：数字来自 bacmap；叙事与自定义版式可以来自 agent。

| 档 | 谁生成 | 用途 | 来源记录 |
|---|---|---|---|
| **A. 确定性标准图** | bacmap（`FigureSpec` + 固定 renderer） | 2×2 条形图、森林图、流程图 | spec/data/output SHA-256 |
| **B. 自定义发表图** | agent 写脚本，在 `mine` 沙箱执行 | 期刊定制面板、特殊标注 | spec/data/code/output SHA-256 + 人工签字 |
| **C. Paper skill** | agent 指导 | 选图、配色、图注、期刊格式 | 仅指导 |

每个 session 都保存 `figure_spec.json`；读取方式：

```bash
bacmap research figure spec rs-0123456789ab
```

或经 MCP 的 `bacmap_research_figure_spec`（D2）。契约包含精确的表格与统计量、来源 ID
（`session_id`、`run_id`、`stat_sha256`、`plan_id`）、样式约束（宽高、dpi、格式、
色盲友好配色）以及图注约束。

自定义图片渲染完成后登记来源：

```bash
bacmap research figure draft rs-0123456789ab --path draft.svg --note "first pass"
bacmap research figure attach rs-0123456789ab \
  --path figure.pdf --code plot.py
```

`attach` 会拒绝来自其他 session 的契约、契约不允许的输出格式，以及缺失的脚本。
`figure_custom` 与 `figure_manifest` 产物记录 `spec_sha256`、`data_sha256`、
`code_sha256` 与 `output_sha256`。

自定义脚本必须走既有开放路径（`mine` 计划：无网络、只读挂载、挖掘门 + 人工签字）；
沙箱镜像需包含绘图栈（例如 matplotlib 或 R）。能用确定性 renderer 表达的标准图，
不要用 AI 重画。

## 11. 系统发育规划（ML 与 BEAST2）

建树仍是工作流步骤。AI 从确定性 profile 规划参数；bacmap 校验计划并渲染 BEAST2 XML。
AI 绝不把自由文本 XML 直接写进运行。

```bash
bacmap research phylo profile --alignment core.fasta [--dates dates.tsv] --json
bacmap research phylo plan --profile profile.json --goal bayesian --json
bacmap research phylo validate --profile profile.json --plan plan.json
bacmap research phylo xml --profile profile.json --plan plan.json \
  --alignment core.fasta -o beast.xml --validate
bacmap research phylo iqtree --plan plan.json --alignment core.fasta
```

- `PhyloProfile`：taxa、位点数、缺失/模糊、可变与信息位点、日期、告警；确定性、只读。
- `PhyloPlan`：替换模型、速率异质性、时钟模型、树先验、链长、burn-in、采样间隔、seed、
  外群、分区以及 AI 的理由。
- AI 可以修改计划；`validate` 强制边界（链长、burn-in、外群、profile hash）。`xml` 用
  版本化模板渲染，记录 plan/XML/alignment hash，并可运行 `beast -validate`。
- BEAST2 模板 v1 支持 HKY/GTR、可选 `+G`、strict clock 与 constant coalescent。
  relaxed clock、birth-death/Yule 先验与分区会被明确拒绝；自定义 XML 走 `mine` 开放路径
  （hash + 人工签字）。
- BEAUti 替代：AI 选参数并解释权衡，bacmap 渲染/校验 XML，人确认后由工作流运行。

MCP（仅 local-trusted，D3）：`bacmap_research_phylo_profile` 与
`bacmap_research_phylo_plan`。

## 12. 回归与投稿包

### 多变量 logistic 回归

```bash
bacmap research stats logistic --data cohort.csv --outcome resistant \
  --predictors gene_present,age,lineage --json
```

实现为确定性 IRLS（不依赖 scipy）：系数、OR、Wald 95% CI、双侧 p 值与诊断（事件数、
收敛、分离告警）。缺失/非法行会被丢弃并计数。混合效应、IPTW、匹配与生存分析**尚未实现**；
不允许 agent 伪造这些方法。

MCP（仅 local-trusted，D3）：`bacmap_research_logistic`。

### 投稿包

```bash
bacmap research package <study_id> --out ./submission --json
```

包含：

- `submission_manifest.json`——研究、发表门、blocker、文件 hash、数据/代码可用性声明；
- `strobe_checklist.json` / `strobe_checklist.md`——确定性 STROBE 草案，含 met/partial/
  missing 与 evidence ID；
- `artifacts/<session_id>/...`——会话图片、报告、论文草案，带 SHA-256 复制。

清单只是草案，不是发表批准。叙述性条目（摘要、讨论、局限性、外推性、资助/利益冲突）在
人工完成前保持 `missing`。门通过是必要条件，不是充分条件。

MCP（D2，只读）：`bacmap_research_reporting_checklist`。


## 13. 研究请求（Agent → 人）

自然语言指令可以先落成**草案请求**，而不是直接执行：

1. Agent 调用 MCP `bacmap_research_request`，提交问题、run ID、基因/表型、分析类型、
   可选 members/plan spec 与说明。它只写 `research.sqlite` 的草案，不创建
   Study/Cohort/Plan，也不执行任何分析；
2. Web **研究请求收件箱** 列出 proposed 请求；人工检查/修改 members 与 plan spec，
   点击 **确认并创建**；
3. bacmap 创建 Study → 冻结 Cohort → 冻结 Plan → 可选 session，并把 ID 回写到请求；
4. **拒绝** 把请求标记为 rejected 并记录原因。

CLI 兜底：

```bash
bacmap research request create --question "..." --run-id run-1 \
  --gene blaKPC-33 --test-name meropenem --analysis association
bacmap research request list
bacmap research request approve <request_id> --note "approved"
bacmap research request reject <request_id> --note "not needed"
```

MCP（D2+，local-trusted）：`bacmap_research_request`、`bacmap_research_requests`。


## 14. 图片迭代

草稿是一等对象，带反馈与最终确认门：

1. 在 session 页上传 SVG/PNG/PDF 草稿（≤10 MiB），填写说明；
2. **Figure 迭代** gallery 显示草稿、SHA-256、作者与状态；
3. 每个草稿可保存反馈；草稿保持 `draft`；
4. **最终 attach** 把草稿转为自定义图（`figure_custom` + provenance manifest）；
   **拒绝** 标记为 rejected。

只有 final 的草稿进入投稿包。草稿上传仅 Web；Agent 可经 MCP
（`bacmap_research_figure_drafts`）列出草稿与反馈，但不能最终确认。

CLI 兜底：

```bash
bacmap research figure drafts <session_id>
bacmap research figure feedback <draft_id> --text "use colorblind palette"
bacmap research figure finalize <draft_id> --recipe custom [--code plot.py]
bacmap research figure reject <draft_id> --note "wrong layout"
```


## 15. Markdown 渲染与投稿包历史

Session 页用安全 Markdown 子集渲染 `report.md` 与 `manuscript.md`（标题、列表、表格、
代码、粗体/斜体、链接）。原始 HTML 一律转义；链接仅允许 http(s)、mailto 与相对路径。

投稿包按 `research/packages/<study_id>/<package_id>/` 版本化，并写入 `research.sqlite`：

- `GET /research/studies/{study_id}/packages`——历史；
- `POST /research/studies/{study_id}/packages`——生成新投稿包（可选 label）；
- `GET /research/packages/{package_id}`——manifest、checklist、文件、blockers；
- `GET /research/packages/{package_id}/download.zip`——ZIP 下载。

旧的 `/research/studies/{study_id}/package` 保留为快速重建视图。
