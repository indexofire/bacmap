# Research Workbench (P1)

The Research Workbench turns an existing analysis run into a **reviewable research draft**:
statistics, a figure, a report and a manuscript skeleton. P1 is deliberately narrow and
deterministic: one AMR association, no LLM, no new data collection.

> Status: P1 thin slice. Outputs are marked **TEST/UNVERIFIED** in `open-test` and
> **REVIEW REQUIRED** in `research`/`publication`. They are not publication-ready.

## 1. What it does

Given:

- a `run_id` in `runs.sqlite`;
- an AMR gene name from `strain_amr_genes` (`gom.sqlite`);
- a lab test name from `lab_results` (`data/bacmap.sqlite`);

it builds a 2×2 table (gene present/absent × resistant/susceptible), computes an odds ratio with a
95% confidence interval, a two-sided Fisher exact p-value and diagnostics, then writes:

```text
$BACMAP_HOME/research/<session_id>/
├── figure.svg
├── report.md
└── manuscript.md
```

and records the session, stat result, artifacts and ledger in `research.sqlite`.

## 2. What it does not do

- no causal or mechanism claims;
- no lineage/population-structure adjustment (P2);
- no external cohort or validation (P2);
- no LLM-generated text (P1 is deterministic);
- no publication label;
- no new sequencing or ingestion.

## 3. CLI

```bash
# List sessions
bacmap research list

# Create an open-test draft (TEST/UNVERIFIED)
bacmap research create \
  --run-id 9a31c2... \
  --gene blaKPC-33 \
  --test-name meropenem \
  --profile open-test

# Show the stat table and artifact paths
bacmap research show rs-0123456789ab

# Print an artifact
bacmap research artifact rs-0123456789ab report
bacmap research artifact rs-0123456789ab manuscript
```

Use `--json` for machine-readable output. `BACMAP_RESEARCH_PROFILE` sets the default profile;
`research` is the safe default, `open-test` is for development.

P2 object lifecycle is also available from the CLI (JSON or file arguments):

```bash
bacmap research study create --question "Does blaKPC associate with meropenem?" --pathogen KPN
bacmap research cohort create --study <study_id> --members cohort_members.json --name discovery
bacmap research cohort freeze <cohort_id>
bacmap research plan create --study <study_id> --cohort <cohort_id> \
  --spec '{"run_id":"...","gene":"blaKPC","test_name":"meropenem"}'
bacmap research plan freeze <plan_id>
bacmap research experiment record --plan <plan_id> --status success --run-id <run_id>
bacmap research claim create --study <study_id> --type association \
  --wording "blaKPC is associated with meropenem resistance" --level E2
bacmap research claim review <claim_id> --decision approve
bacmap research publication <study_id>
```

`cohort create` accepts the OSF fixture shape (`{"members": [...]}`). A publication check
returns each gate's blockers; `ready=true` still requires human review.

## 4. Web

Run `bacmap start web` and open **研究 / Research**:

1. enter `run_id`, gene and test name;
2. choose a governance profile;
3. open the session to see the 2×2 table, diagnostics, figure, report and manuscript;
4. artifacts expose their SHA-256 and path for traceability.

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

See [Research API](../reference/research-api.md) for all endpoints.

## 6. MCP

If the MCP profile allows D2, the server exposes:

- `bacmap_research_capabilities`
- `bacmap_research_sessions`
- `bacmap_research_session`

`cloud` (D1) only receives `bacmap_research_capabilities`; session content is D2 and is not
registered. Research writes are not exposed as MCP tools: creation currently happens via CLI/Web/API.

## 7. Governance profiles

| Profile | Status | Label | Meaning |
|---|---|---|---|
| `open-test` | `complete_test` | `TEST/UNVERIFIED` | fast development; auto-approved test output |
| `research` | `review_required` | `REVIEW REQUIRED` | human review expected before use |
| `publication` | `review_required` | `REVIEW REQUIRED` | publication gates not implemented in P1 |

`open-test` does **not** relax D3/D4 data boundaries. It only relaxes artifact approval for this
deterministic P1 pipeline.

## 8. Evidence and limits

The session ledger records creation (run, gene, test, profile). The stat table and diagnostics are
reproducible from the named run plus local GOM/lab databases. P2 core objects are now available through the API (Study → Cohort → AnalysisPlan → Claim):

- `POST /api/v1/research/studies`
- `POST /api/v1/research/cohorts` + `/{id}/freeze`
- `POST /api/v1/research/plans` + `/{id}/freeze`
- `POST /api/v1/research/claims` + `/{id}/review`
- `POST /api/v1/research/cohorts/preview` (duplicates/missing runs)
- `POST /api/v1/research/plans/{id}/run` (P1 AMR recipe)
- `POST /api/v1/research/experiments` (success/failed/negative/deviation ledger)
- `GET /api/v1/research/studies/{id}/publication-readiness` (G0–G3)
- `POST /api/v1/research/claims/from-session` (session → association claim)
- `GET /api/v1/research/benchmarks/amr` (L0 synthetic benchmark)
- `GET /api/v1/research/benchmarks/bvbrc-amr` (L1 real-data benchmark)
- `GET /api/v1/research/benchmarks/osf-cohort` (L2 cohort/phenotype summary)
- `GET /api/v1/research/benchmarks/verify?dataset=...` (SHA-256 + row-count checks)

A cohort must be frozen before a plan; a plan carries a deterministic hash; a claim records type,
evidence level and review status. Claim review enforces a minimum level/wording gate
(association E2, transmission E3+time/epidemiology, causal E3+design, mechanism E4+functional).
The Web `/research/studies/{id}` page lists cohorts, plans and claims for a study.

The statistics layer also provides:

- Benjamini–Hochberg FDR across multiple targets (`benjamini_hochberg`);
- Mantel–Haenszel pooled odds ratio with Greenland–Robins CI (`mantel_haenszel`);
- sparse-cell diagnostics and explicit Intermediate/zero-cell handling.

Each actual execution can be recorded as an **Experiment** (`success`, `failed`, `negative`,
`deviated`) against the frozen plan hash; deviations require a note. Experiments are append-only
and appear in the ledger. `publication-readiness` evaluates four deterministic gates:

| Gate | Requirement |
|---|---|
| G0 | frozen cohort + frozen plan with valid hash |
| G1 | at least one supported/approved claim; approved claims pass level/wording; no open challenged claim |
| G2 | study and linked sessions are D0–D2 |
| G3 | at least one success/negative experiment whose plan hash matches and has run IDs |

Gate pass is necessary, **not sufficient**: a human publication review is still required, and
the package exporter is not part of P2.

### Real-data scientific benchmarks

The repository ships **code and manifests**, not the data. Public snapshots are placed under
`$BACMAP_HOME/benchmarks/<dataset>/` (or set `BACMAP_BENCHMARK_DATA`):

| Level | Dataset | What it validates |
|---|---|---|
| L0 | synthetic 2×2 | OR/CI/Fisher/BH correctness |
| L1 | BV-BRC *K. pneumoniae* / meropenem | real genotype–phenotype association regression and confounding detection |
| L2 | OSF n78q3 outbreak + colistin | phenotype missingness, cohort composition, negative-result handling |

Run them with `bacmap research benchmark amr|bvbrc|osf|verify-bvbrc|verify-osf`, or use the API.
The L1 benchmark deliberately keeps CTX-M as a **negative/confounded example**: a crude OR below 1
must not be rewritten as a protective mechanism. L2 reports 37.6% colistin-phenotype coverage and
preserves the original study's negative GWAS result.

These are observational L1/L2 benchmarks, not gold-standard causal truth. They do not support
causal, mechanism or transmission claims.

### Real-cohort sensitivity analysis

The BV-BRC L1 benchmark now reports crude and Mantel–Haenszel adjusted estimates, stratified by
the most precise available metadata (`geo_loc_name` → `isolation_source` → `testing_standard`),
plus leave-one-stratum-out and E-values. On the current snapshot:

| Target | Crude OR | MH OR (95% CI) | Leave-one-out range |
|---|---:|---|---|
| OXA-48 | 4.03 | 2.48 (1.60–3.85) | 1.89–2.96 |
| KPC | 113.7 | 33.9 (21.1–54.5) | 26.2–36.6 |
| NDM | 28.0 | 7.87 (4.97–12.47) | 4.93–8.33 |
| CTX-M | 0.70 | 0.71 (0.56–0.91) | 0.53–0.94 |

KPC/NDM attenuate strongly after stratification: the crude estimate is confounded. CTX-M remains
negative, so it stays a counterexample rather than a protective mechanism.

### Outbreak and sporadic-event mining

`research/outbreak.py` clusters **already recorded** events by location + date precision and mines
categorical associations (clustered vs sporadic, study source, lineage). It does not call variants,
build trees or infer transmission direction. On the OSF n78q3 cohort (176 phenotyped events):

- 71 contextual clusters; 145 events clustered, 31 sporadic;
- source mining shows strong study effects (e.g. Pitt OR 11.4, BH q 0.0016; UHL OR 0.35,
  q 0.0031), which are **sampling/source confounding**, not biology;
- transmission claims still require external typing + temporal/epidemiological context.

```bash
bacmap research outbreak --events dev/benchmark-data/osf_n78q3/outbreak_events.json
bacmap research sensitivity --table 70,60,30,20 \
  --strata '[["A",30,20,5,2],["B",25,25,10,8],["C",15,15,15,10]]'
```

### P3 candidate exploration (first slice)

`research/discovery.py` ranks screening associations under an explicit budget. It rejects
confirmatory input, never creates Claims, and marks every candidate as needing independent
confirmation. Candidates are scored by FDR, effect size and sample size; the stop reason is
recorded.

```bash
bacmap research explore --study study-... --cases cases.json \
  --max-tests 200 --max-candidates 20 --min-n 20 --max-q 0.05
```

This is the P3 starting point, not full auto-exploration: Explorer/Verifier/Critic orchestration,
adversarial traps and persistent candidate ledgers are still to be built.

## 9. Design boundary

P1 reuses existing components:

- `runs.sqlite` for run membership;
- `gom.sqlite::strain_amr_genes` for genotype;
- `data/bacmap.sqlite::lab_results` for phenotype;
- `research.sqlite` for research objects;
- existing Web/API/MCP/CLI/DBOS boundaries.

It does not change GOM, Snakemake, DBOS or the five task types.
