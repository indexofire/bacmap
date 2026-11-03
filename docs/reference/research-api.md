# Research API (P1)

All routes are under `/api/v1/research` and use the same authentication as the Web console.
Research content is **D2** (single-strain AMR/phenotype) and is only available to profiles that
allow D2.

## Capabilities

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

## Sessions

```http
GET  /api/v1/research/sessions?limit=50
POST /api/v1/research/sessions
GET  /api/v1/research/sessions/{session_id}
GET  /api/v1/research/sessions/{session_id}/ledger
```

Create body:

```json
{
  "run_id": "9a31c2...",
  "gene": "blaKPC-33",
  "test_name": "meropenem",
  "profile": "open-test"
}
```

Response (abridged):

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

## Artifacts

```http
GET /api/v1/research/sessions/{session_id}/figure.svg
GET /api/v1/research/sessions/{session_id}/report.md
GET /api/v1/research/sessions/{session_id}/manuscript.md
```

`figure.svg` is `image/svg+xml`; reports are `text/markdown`. The three artifacts are immutable for a
given session; a new analysis creates a new session.

## Errors

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

In cookie mode, `POST /research/sessions` needs `X-CSRF-Token` equal to the `bacmap_csrf` cookie.
The Web form includes the token automatically.

## P2 research objects

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

Create a study:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Is blaKPC-33 associated with resistance?","pathogen_scope":"KPN","data_class":2}' \
  http://127.0.0.1:8800/api/v1/research/studies
```

Create and freeze a cohort:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","name":"discovery","rules":{"qc":true},
       "members":[{"isolate_id":"I1","dataset_id":"D1","run_id":"R1"}]}' \
  http://127.0.0.1:8800/api/v1/research/cohorts

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/cohorts/<cohort_id>/freeze
```

Create and freeze a plan:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","cohort_id":"cohort-...","spec":{"endpoint":"mic"}}' \
  http://127.0.0.1:8800/api/v1/research/plans

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/research/plans/<plan_id>/freeze
```

Create and review a claim:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"study_id":"study-...","claim_type":"association",
       "wording":"blaKPC-33 is associated with resistance","evidence_level":"E2",
       "evidence":{"stat":"s1"}}' \
  http://127.0.0.1:8800/api/v1/research/claims

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"decision":"support","message":"reviewed"}' \
  http://127.0.0.1:8800/api/v1/research/claims/<claim_id>/review
```

Cohort freezing computes a canonical snapshot hash; a plan requires a frozen cohort and carries a
deterministic hash; `POST /research/plans/{id}/run` executes the P1 AMR recipe when the plan spec
contains `run_id`, `gene`, `test_name`, linking the session to the study/cohort/plan.

Claim review supports `support`, `challenge`, `reject`, `approve`. Before support/approve, a
minimum gate checks:

- association → E2+;
- transmission → E3+ plus temporal/epidemiological evidence;
- causal → E3+ plus experimental/interventional design;
- mechanism → E4 plus functional evidence;
- association/observation wording must not use causal/mechanism/transmission language.

`POST /research/cohorts/preview` reports duplicate isolates/datasets and missing runs without
writing. `POST /research/claims/from-session` turns a study-linked P1 session into an association
claim draft, carrying the stat table/run into its evidence.

## Experiments and publication gates

Record every execution against a frozen plan (append-only; deviations require a note):

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

`status` is `success`, `failed`, `negative` or `deviated`. The record stores the plan's hash, so a
later plan revision cannot be confused with the executed version.

```http
GET /api/v1/research/studies/{study_id}/publication-readiness
```

Returns `ready` plus four gates:

- **G0** frozen cohort and frozen plan with a valid hash;
- **G1** supported/approved claim passing level/wording, with no open challenged claim;
- **G2** study and linked sessions within D0–D2;
- **G3** success/negative experiment matching the plan hash and carrying run IDs.

`ready=true` is necessary but not sufficient; a human publication review is still required.

`GET /research/benchmarks/amr` runs the L0 AMR 2×2 benchmark suite (positive/null/negative).

## Scientific benchmarks (real data)

Real-data snapshots are never committed. Point `BACMAP_BENCHMARK_DATA` at a dataset directory
(or a parent containing `bvbrc_kpn_meropenem`/`osf_n78q3`), or place them under
`$BACMAP_HOME/benchmarks/`.

```http
GET /api/v1/research/benchmarks/bvbrc-amr
GET /api/v1/research/benchmarks/osf-cohort
GET /api/v1/research/benchmarks/verify?dataset=bvbrc_kpn_meropenem
```

- `bvbrc-amr` returns per-target 2×2, OR, 95% CI, Fisher p, BH q, direction and a
  `passed` flag against the pre-registered direction (carbapenemases positive; CTX-M
  expected non-positive as a confounding example).
- `osf-cohort` returns phenotype coverage, study composition, breakpoint counts and
  explicit limitations; it does not recompute variants or lineages.
- `verify` checks every file's SHA-256 and minimum row count from the dataset
  `manifest.json`, so a silently replaced snapshot is reported as `ok=false`.

Both return `available=false` when the data directory is absent; this is not an error.

## Outbreak mining and candidate exploration

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

Returns location+period clusters, sporadic/clustered counts, and BH-adjusted categorical
associations. It does **not** infer transmission; that requires external typing and
temporal/epidemiological evidence.

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

Ranks screening candidates only. `role` other than `screening` is rejected; candidates are
proposals and never create Claims or change evidence levels.
