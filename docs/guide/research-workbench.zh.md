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

运行 `bacmap start web` 后打开 **研究 / Research**：

1. 填 `run_id`、基因、检测名；
2. 选择治理 Profile；
3. 查看 2×2 表、诊断、图、报告和论文草案；
4. 产物显示 SHA-256 与路径，便于追溯。

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
bacmap research figure attach rs-0123456789ab \
  --path figure.pdf --code plot.py
```

`attach` 会拒绝来自其他 session 的契约、契约不允许的输出格式，以及缺失的脚本。
`figure_custom` 与 `figure_manifest` 产物记录 `spec_sha256`、`data_sha256`、
`code_sha256` 与 `output_sha256`。

自定义脚本必须走既有开放路径（`mine` 计划：无网络、只读挂载、挖掘门 + 人工签字）；
沙箱镜像需包含绘图栈（例如 matplotlib 或 R）。能用确定性 renderer 表达的标准图，
不要用 AI 重画。
