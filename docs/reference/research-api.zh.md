# Research API（P1）

所有路由在 `/api/v1/research` 下，鉴权与 Web 控制台相同。研究内容是 **D2**（单株 AMR/表型），
只对允许 D2 的 Profile 开放。

## 能力

```http
GET /api/v1/research/capabilities?profile=open-test
```

```json
{
  "profile": "open-test",
  "statuses": ["complete_test", "review_required", "reviewed"],
  "artifacts": ["figure", "report", "manuscript"],
  "description": "P1 Research Workbench: ..."
}
```

## 会话

```http
GET  /api/v1/research/sessions?limit=50
POST /api/v1/research/sessions
GET  /api/v1/research/sessions/{session_id}
GET  /api/v1/research/sessions/{session_id}/ledger
```

创建请求：

```json
{
  "run_id": "9a31c2...",
  "gene": "blaKPC-33",
  "test_name": "meropenem",
  "profile": "open-test"
}
```

响应（节选）：

```json
{
  "session": {
    "session_id": "rs-0123456789ab",
    "run_id": "9a31c2...",
    "gene": "blaKPC-33",
    "test_name": "meropenem",
    "profile": "open-test",
    "status": "complete_test",
    "label": "TEST/UNVERIFIED",
    "data_class": 2
  },
  "stat": {
    "table": {
      "gene_pos_resistant": 6,
      "gene_pos_susceptible": 1,
      "gene_neg_resistant": 2,
      "gene_neg_susceptible": 7
    },
    "odds_ratio": 21.0,
    "ci_low": 1.8,
    "ci_high": 244.0,
    "p_value": 0.04,
    "n": 16,
    "diagnostics": []
  },
  "artifacts": [
    {"kind": "figure", "path": ".../figure.svg", "sha256": "..."},
    {"kind": "report", "path": ".../report.md", "sha256": "..."},
    {"kind": "manuscript", "path": ".../manuscript.md", "sha256": "..."}
  ]
}
```

## 产物

```http
GET /api/v1/research/sessions/{session_id}/figure.svg
GET /api/v1/research/sessions/{session_id}/report.md
GET /api/v1/research/sessions/{session_id}/manuscript.md
```

`figure.svg` 为 `image/svg+xml`；报告为 `text/markdown`。同一 session 的产物不可变；新分析创建新
session。

## 错误

```json
{"code": "not_found", "error": "no such run: ..."}
{"code": "validation_error", "error": "run_id, gene and test_name are required"}
```

| Code | HTTP |
|---|---|
| `validation_error` | 400 |
| `not_found` | 404 |
| `conflict` | 409 |

## CSRF

Cookie 模式下，`POST /research/sessions` 需要 `X-CSRF-Token`，值等于 `bacmap_csrf` cookie。
Web 表单会自动带上。

## P2 研究语义对象

```http
GET  /api/v1/research/studies
POST /api/v1/research/studies
GET  /api/v1/research/studies/{study_id}

POST /api/v1/research/cohorts/preview
POST /api/v1/research/cohorts
POST /api/v1/research/cohorts/{cohort_id}/freeze

POST /api/v1/research/plans
POST /api/v1/research/plans/{plan_id}/freeze
POST /api/v1/research/plans/{plan_id}/run
POST /api/v1/research/experiments
GET  /api/v1/research/experiments?study_id=&plan_id=
GET  /api/v1/research/studies/{study_id}/publication-readiness

POST /api/v1/research/claims
POST /api/v1/research/claims/from-session
POST /api/v1/research/claims/{claim_id}/review

GET  /api/v1/research/cohorts?study_id=
GET  /api/v1/research/cohorts/{cohort_id}
GET  /api/v1/research/plans?study_id=
GET  /api/v1/research/plans/{plan_id}
GET  /api/v1/research/claims?study_id=
GET  /api/v1/research/claims/{claim_id}
GET  /api/v1/research/ledger?object_type=&object_id=
GET  /api/v1/research/benchmarks/amr
GET  /api/v1/research/benchmarks/bvbrc-amr
GET  /api/v1/research/benchmarks/osf-cohort
GET  /api/v1/research/benchmarks/verify?dataset=bvbrc_kpn_meropenem|osf_n78q3

POST /api/v1/research/outbreak/analyze
POST /api/v1/research/explore
```

创建 Study：

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"blaKPC-33 是否与耐药相关？","pathogen_scope":"KPN","data_class":2}' \
  http://127.0.0.1:8800/api/v1/research/studies
```

创建并冻结 Cohort：

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","name":"discovery","rules":{"qc":true},
       "members":[{"isolate_id":"I1","dataset_id":"D1","run_id":"R1"}]}' \
  http://127.0.0.1:8800/api/v1/research/cohorts

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/cohorts/<cohort_id>/freeze
```

创建并冻结 Plan：

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","cohort_id":"cohort-...","spec":{"endpoint":"mic"}}' \
  http://127.0.0.1:8800/api/v1/research/plans

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/plans/<plan_id>/freeze
```

创建并审核 Claim：

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","claim_type":"association",
       "wording":"blaKPC-33 与耐药相关","evidence_level":"E2",
       "evidence":{"stat":"s1"}}' \
  http://127.0.0.1:8800/api/v1/research/claims

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"decision":"support","message":"reviewed"}' \
  http://127.0.0.1:8800/api/v1/research/claims/<claim_id>/review
```

Cohort 冻结计算规范快照哈希；Plan 需要已冻结 Cohort 并带确定性哈希。
`POST /research/plans/{id}/run` 在计划 spec 含 `run_id`/`gene`/`test_name` 时执行 P1 AMR
配方，并把 session 关联到 study/cohort/plan。

Claim 审核支持 `support`、`challenge`、`reject`、`approve`。support/approve 前有最低门：

- association → E2+；
- transmission → E3+，且有时间/流行病学证据；
- causal → E3+，且有实验/干预设计；
- mechanism → E4，且有功能证据；
- association/observation 的措辞不得使用因果/机制/传播语言。

`POST /research/cohorts/preview` 不写库地报告重复 isolate/dataset 与缺失 run。
`POST /research/claims/from-session` 把已关联 Study 的 P1 会话转成 association Claim 草案，
证据中携带 stat 表与 run。

## Experiment 与发表门

每次实际执行都应绑定冻结计划记录（追加式；偏离必须写说明）：

```http
POST /api/v1/research/experiments
GET  /api/v1/research/experiments?study_id=&plan_id=
```

```json
{
  "plan_id": "plan-...",
  "status": "success",
  "run_ids": ["run-..."],
  "outcome": {"n": 965},
  "deviation": ""
}
```

`status` 取 `success`/`failed`/`negative`/`deviated`。记录保存计划的哈希，后续计划修订不会与
已执行版本混淆。

```http
GET /api/v1/research/studies/{study_id}/publication-readiness
```

返回 `ready` 与四个门：

- **G0** 已冻结 Cohort 与已冻结 Plan，哈希有效；
- **G1** 至少一个 supported/approved Claim 通过等级/措辞门，且无未处理的 challenged Claim；
- **G2** Study 与关联 session 在 D0–D2；
- **G3** success/negative Experiment 与计划哈希匹配并带 run ID。

`ready=true` 是必要条件而非充分条件；仍需人工发表评审。

`GET /research/benchmarks/amr` 运行 L0 AMR 2×2 基准（positive/null/negative）。

## 科学基准（真实数据）

真实数据快照不入库。把 `BACMAP_BENCHMARK_DATA` 指向数据集目录（或包含
`bvbrc_kpn_meropenem`/`osf_n78q3` 的父目录），或放到 `$BACMAP_HOME/benchmarks/`。

```http
GET /api/v1/research/benchmarks/bvbrc-amr
GET /api/v1/research/benchmarks/osf-cohort
GET /api/v1/research/benchmarks/verify?dataset=bvbrc_kpn_meropenem
```

- `bvbrc-amr` 返回每个靶点的 2×2、OR、95% CI、Fisher p、BH q、方向，并按预设方向给出
  `passed`（碳青霉烯酶为正；CTX-M 作为混杂示例预期非正）。
- `osf-cohort` 返回表型覆盖率、研究来源构成、折点计数与明确限制；不重算变异或谱系。
- `verify` 按数据集 `manifest.json` 校验每个文件的 SHA-256 与最小行数；快照被替换会返回
  `ok=false`。

数据目录不存在时两者都返回 `available=false`，这不是错误。

## 暴发事件挖掘与候选探索

```http
POST /api/v1/research/outbreak/analyze
```

```json
{
  "events": [
    {"case_id": "A", "event_date": "2020-01-02", "location": "Ward1",
     "source": "outbreak-A", "phenotype": "Resistant", "lineage": "L1"}
  ],
  "min_count": 5
}
```

返回地点+日期精度聚类、聚集/散在计数，以及 BH 校正后的分类关联。它**不推断传播**；
传播需要外部分型 + 时间/流调证据。

```http
POST /api/v1/research/explore
```

```json
{
  "study_id": "study-...",
  "role": "screening",
  "cases": [{"exposure": "KPC", "outcome": "meropenem", "table": [20, 2, 2, 20]}],
  "budget": {"max_tests": 200, "max_candidates": 20, "min_n": 20, "max_q": 0.05}
}
```

只对 screening 数据排序候选。`role` 非 `screening` 会被拒绝；候选只是提议，不会创建
Claim 或改变证据等级。
