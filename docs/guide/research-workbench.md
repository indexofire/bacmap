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

## 10. Publication figures


### R/Python runtimes

Recipes declare where they run; do not install R/Python packages ad hoc during an analysis.

| Runtime | When | How |
|---|---|---|
| `builtin` | SVG/deterministic recipes | runs inside bacmap |
| `container` | R/ggtree, matplotlib, seaborn | Apptainer/Podman image (`bacmap-figures:r4`, `bacmap-figures:py312`) |
| `pixi` | offline/no-container machines | optional `figures` pixi environment with pinned packages |
| `host` | development only | existing `Rscript`/Python; not reproducible |

Check availability with:

```bash
bacmap research figure runtimes
```

Container images are the reproducible default: the image digest is recorded with the artifact.
The main bacmap environment stays small; R and plotting libraries do not become runtime
dependencies of the analysis pipeline. If a recipe needs a package that is not in its image, add
it to the image build and bump the recipe version — never `install.packages()` at run time.

### Iterating from an example figure

A user can point at a published figure or describe a layout. The agent must not copy the image.
Instead it extracts a **style brief** into the `FigureSpec.style` fields:

- `journal`: target journal or `""`;
- `panel_layout`: `single`, `2x2`, `top-bottom`, ...;
- `palette_colors`: explicit hex values when the user requires them;
- `reference_note`: human description of the reference (“Lancet-style forest, no gridlines”);
- `width_mm`, `height_mm`, `dpi`, `font_family`, `font_size_pt`.

The loop is: `FigureSpec` + style brief + recipe → draft render → user feedback → update the
brief/recipe parameters → re-render. Record drafts as intermediate artifacts; only the approved
figure is attached with hashes. The reference image itself is never stored in the repository or
redistributed by bacmap.


### Recipe library

Link a session to its study/cohort/plan at creation time so the figure spec and package carry the
full provenance chain:

```bash
bacmap research create --run-id run-1 --gene blaKPC-33 --test-name meropenem \
  --profile research --study <study_id> --cohort <cohort_id> --plan <plan_id>
```

`bacmap research figure recipes` lists the versioned recipes. A recipe is executable only when
its status is `stable`/`experimental` and it has an entrypoint; `planned` recipes document the
roadmap and are never silently faked.

| Recipe | Language | Status | Use |
|---|---|---|---|
| `association_bar` | SVG | stable | P1 2×2 association bars |
| `forest` | Python/matplotlib | planned | effect estimates with 95% CI |
| `heatmap` | Python/matplotlib+seaborn | planned | annotated matrices |
| `pca` | Python/matplotlib | planned | ordination |
| `volcano` | Python/matplotlib | planned | effect vs FDR |
| `tree_rectangular` | R/ggtree | planned | render a Newick tree |
| `strobe_flow` | SVG | planned | cohort flow |
| `custom` | Python | experimental | agent-authored fallback in the `mine` sandbox |

Rules:

1. choose a stable recipe when one expresses the result;
2. `tree_rectangular` only renders a tree — inference (IQ-TREE/Gubbins, model, bootstrap,
   rooting) is a separate workflow step, never an AI-written script;
3. planned recipes are not usable yet; do not pretend they ran;
4. if no recipe fits, use `custom` in the sandbox and attach the result with hashes;
5. do not copy figures from papers. A published figure can be a human-provided style reference;
   translate the idea into a recipe/spec, never reproduce the image.


Figures follow the same rule as statistics: the numbers come from bacmap; the narrative and a
custom layout may come from an agent.

| Tier | Generated by | Use | Provenance |
|---|---|---|---|
| **A. Deterministic standard** | bacmap (`FigureSpec` + fixed renderer) | 2×2 bars, forest, flow | spec/data/output SHA-256 |
| **B. Custom publication** | agent-authored script executed in the `mine` sandbox | journal-specific panels, annotations | spec/data/code/output SHA-256 + human sign-off |
| **C. Paper skill** | agent guidance | figure choice, palette, caption, journal style | guidance only |

Every session stores `figure_spec.json`; read it with:

```bash
bacmap research figure spec rs-0123456789ab
```

or over MCP with `bacmap_research_figure_spec` (D2). The spec contains the exact table and
statistics, source IDs (`session_id`, `run_id`, `stat_sha256`, `plan_id`), style constraints
(width/height, dpi, formats, colorblind-safe palette) and the caption constraints.

After a custom figure is rendered, register it with provenance:

```bash
bacmap research figure draft rs-0123456789ab --path draft.svg --note "first pass"
bacmap research figure attach rs-0123456789ab \
  --path figure.pdf --code plot.py
```

`attach` refuses a spec from another session, an output format the spec does not allow, or a
missing script. The `figure_custom` and `figure_manifest` artifacts record `spec_sha256`,
`data_sha256`, `code_sha256` and `output_sha256`.

Custom scripts must run through the existing open path (`mine` plan: no network, read-only
mounts, mining gate and human signature); the sandbox image must contain the plotting stack
(for example matplotlib or R). Do not redraw a standard figure with AI when the deterministic
renderer already expresses it.

## 11. Phylogenetic planning (ML and BEAST2)

Tree inference stays a workflow step. The AI plans parameters from a deterministic profile;
bacmap validates the plan and renders the BEAST2 XML. The AI never writes free-form XML into a
run.

```bash
bacmap research phylo profile --alignment core.fasta [--dates dates.tsv] --json
bacmap research phylo plan --profile profile.json --goal bayesian --json
bacmap research phylo validate --profile profile.json --plan plan.json
bacmap research phylo xml --profile profile.json --plan plan.json \
  --alignment core.fasta -o beast.xml --validate
bacmap research phylo iqtree --plan plan.json --alignment core.fasta
```

- `PhyloProfile`: taxa, sites, missing/ambiguous data, variable and informative sites, dates,
  warnings. It is deterministic and read-only.
- `PhyloPlan`: substitution model, rate heterogeneity, clock model, tree prior, chain length,
  burn-in, sampling interval, seed, outgroup, partitions and the AI's rationale.
- The AI may revise the plan; `validate` enforces bounds (chain length, burn-in, outgroup,
  profile hash). `xml` renders a versioned template, records plan/XML/alignment hashes and can
  run `beast -validate`.
- BEAST2 template v1 supports HKY/GTR, optional `+G`, strict clock and constant coalescent.
  Relaxed clocks, birth-death/Yule priors and partitions are rejected with a clear message;
  use the `mine` open path for custom XML (hashes + human sign-off).
- BEAUti replacement: the AI chooses parameters and explains trade-offs, bacmap renders and
  validates the XML, a human confirms, and the workflow runs it.

Over MCP (local-trusted only, D3): `bacmap_research_phylo_profile` and
`bacmap_research_phylo_plan`.

## 12. Regression and submission package

### Multivariable logistic regression

```bash
bacmap research stats logistic --data cohort.csv --outcome resistant \
  --predictors gene_present,age,lineage --json
```

The implementation is deterministic IRLS (no scipy): coefficients, odds ratios, Wald 95%
CIs, two-sided p-values and diagnostics (events, convergence, separation warning). Rows with
missing/invalid values are dropped and counted. Mixed-effects, IPTW, matching and survival
models are **not** implemented yet; do not let an agent fake them.

Over MCP (local-trusted, D3): `bacmap_research_logistic`.

### Submission package

```bash
bacmap research package <study_id> --out ./submission --json
```

The package contains:

- `submission_manifest.json` — study, readiness gates, blockers, file hashes, data/code
  availability statements;
- `strobe_checklist.json` / `strobe_checklist.md` — deterministic STROBE draft with
  met/partial/missing items and evidence IDs;
- `artifacts/<session_id>/...` — session figures, reports and manuscripts copied with SHA-256.

The checklist is a draft, not a publication approval. Narrative items (abstract, discussion,
limitations, generalisability, funding/conflicts) remain `missing` until a human completes them.
Gate pass is necessary, not sufficient.

Over MCP (D2, read-only): `bacmap_research_reporting_checklist`.
