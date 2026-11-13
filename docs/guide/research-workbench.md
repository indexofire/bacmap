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

Run `bacmap start web` and open **研究 / Research**. The Web is the primary review surface:

1. choose a run from the dropdown (or type a `run_id` when no runs exist);
2. enter gene/phenotype, choose a governance profile, optionally link a Study/Cohort/Plan and
   add a research note;
3. the session page shows the 2×2 table, diagnostics, the standard and custom figures, the
   `FigureSpec`, the custom-figure provenance manifest and downloadable artifacts with SHA-256;
4. the Study page shows G0–G3, linked sessions with figure thumbnails, the STROBE draft
   (met/partial/missing) and links to the submission package;
5. the research home also links to **Phylogenetic planning** (`/research/phylo`: profile → plan →
   BEAST2 XML / IQ-TREE command) and **Logistic regression** (`/research/stats`: CSV/TSV →
   OR/CI/p table);
6. the Study page also links to the **Cohort builder**: select runs/samples with checkboxes,
   preview duplicate isolates/datasets and missing runs, then create the cohort without hand-
   writing members JSON;
7. the session page also has a **Figure 迭代** gallery for uploading drafts, saving feedback and
   finalizing/rejecting them;
8. the session page renders report/manuscript Markdown safely (raw HTML escaped);
9. the Study page and `/research/studies/{id}/packages` keep a **package history**: each build
   records package_id, label, created_at, file count, blockers and manifest SHA-256; open a
   package to view its manifest/checklist or download a ZIP;
10. stats/phylo results can be saved as **analysis objects** and listed per Study;
11. Study/Session pages show the **evidence graph** (`evidence_edges`);
12. the Study page links to a **STROBE checklist editor**: edit status/evidence/note per item,
    save a draft or sign off (signing requires no `missing` items);
13. the package page shows the manifest, checklist, files and data/code availability, and offers
   a ZIP download.

Natural-language research instructions are handled by an external agent over MCP (Pi/Hermes/
DSH); the agent can read research objects and propose next steps, while writes currently stay in
the Web/CLI/API. The Web remains the human review and result-viewing surface.

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

- `bacmap_research_capabilities` (every profile, including `cloud`/D1)
- `bacmap_research_sessions`, `bacmap_research_session`
- `bacmap_research_request`, `bacmap_research_requests` (draft proposals only — see §13)
- `bacmap_research_power`, `bacmap_research_reporting_checklist`, `bacmap_research_evidence`
- `bacmap_research_figure_spec`, `bacmap_research_figure_recipes`, `bacmap_research_figure_drafts`
- `bacmap_research_analyses`, `bacmap_research_analysis`, `bacmap_research_logistic`, `bacmap_research_phylo_profile`, `bacmap_research_phylo_plan`

`cloud` (D1) only receives `bacmap_research_capabilities`; session content is D2 and is not
registered. The only research write exposed over MCP is the **request draft**
(`bacmap_research_request`); session/Study/Cohort/Plan creation stays on CLI/Web/API behind human
confirmation. See §19 for an end-to-end tutorial with an external agent (DSH).

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
| `forest` | SVG | experimental | effect estimates with 95% CI (log axis, no-effect line) |
| `strobe_flow` | SVG | experimental | inclusion/exclusion flow (STROBE item 13) |
| `heatmap` | Python/matplotlib+seaborn | planned | annotated matrices |
| `pca` | Python/matplotlib | planned | ordination |
| `volcano` | Python/matplotlib | planned | effect vs FDR |
| `tree_rectangular` | R/ggtree | planned | render a Newick tree |
| `custom` | Python | experimental | agent-authored fallback in the `mine` sandbox |

Rules:

1. choose a stable recipe when one expresses the result;
2. `tree_rectangular` only renders a tree — inference (IQ-TREE/Gubbins, model, bootstrap,
   rooting) is a separate workflow step, never an AI-written script;
3. planned recipes are not usable yet; do not pretend they ran — the container recipes
   (`heatmap`/`pca`/`volcano`/`tree_rectangular`) activate once CI publishes pinned images;
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

### Deterministic rendering: figure render

The three builtin SVG recipes (`association_bar`, `forest`, `strobe_flow`) need no external
runtime — bacmap renders them deterministically from the session's FigureSpec:

```bash
bacmap research figure render rs-0123456789ab --recipe forest
bacmap research figure render rs-0123456789ab --recipe strobe_flow
```

The output lands in `research/<session>/figure_<recipe>.svg`, is registered as a `figure`
artifact and writes a `figure.rendered` ledger entry (recipe, renderer, output/spec hashes).
Renderers consume the FigureSpec only and never re-read the stores, so one spec always yields
the same figure. `strobe_flow` derives every count from the `runs.sqlite` roster and the
session statistics (identified → excluded for missing genotype/phenotype → analysed n); no
number is ever typed in by a human or an agent. Re-rendering a recipe is idempotent; a session
may keep several standard figures at once (since schema v6 `research_artifacts` is keyed by
session+kind+path).

Recipes with container/pixi/host runtimes cannot use `render`: it refuses them explicitly
(`volcano` is still planned, `custom` belongs to the sandbox) and points to the sandbox +
`figure attach` path instead.

### B-tier script template: figure template

The `custom` fallback does not start from a blank page. The template is a self-contained
script (stdlib + matplotlib only, no bacmap imports, so it runs inside the
`bacmap-figures:py312` image):

```bash
bacmap research figure template --output figure_script.py
```

It demonstrates every contract requirement: numbers are read from `figure_spec.json` only;
the output format must be allowed by `spec.style.formats` (violation exits); size, font and
dpi come from `spec.style`; a provenance summary is printed at the end. A typical `mine`-path
flow:

1. export the contract with `bacmap research figure spec <session> > figure_spec.json`;
2. hand the template and the contract to a mine task (no network, read-only mounts, image
   `bacmap-figures:py312`);
3. record the result as a draft with `figure draft`, and after human approval register it
   with `bacmap research figure attach <session> --path figure.pdf --code figure_script.py`.

The template covers format and provenance mechanics only; journal-grade layout still needs
human judgement. Do not redraw a figure a deterministic recipe already expresses.

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
Since v1.4.42 `attach` also runs a **deterministic output quality gate** (pure stdlib):
PDFs are checked for the header, page count and font embedding (fonts declared without
`/FontFile*` and without Type3 inline glyphs are rejected; matplotlib's default Type3 and
fonttype 42 both pass); PNGs for structure/CRC, color type and pHYs density (below the
spec dpi or missing pHYs is rejected); SVGs for XML well-formedness, with DTD/ENTITY
rejected. Failures come with actionable re-export hints.

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
missing/invalid values are dropped and counted.

Over MCP (local-trusted, D3): `bacmap_research_logistic`.

### Advanced statistics (ADR-22: externalised to containers)

Mixed-effects logistic, IPTW, propensity matching, KM/log-rank and Cox are **not
implemented inside bacmap** (the main environment carries no statistical-modelling
library); they run through `research` plans (ADR-23):

```json
// bacmap_create_plan task shape
{"task_type": "research", "analysis": "advstats", "method": "cox",
 "data_path": "/abs/cohort.csv", "time": "days", "event": "died",
 "predictors": ["tx", "age"]}
```

The chain: typed spec → bacmap **renders the R script deterministically** (preview with
`bacmap research advstats render --method cox ...`) → a human confirms the plan in
bacmap → the `bacmap-stats:r45` image fits the model in the sandbox (data table
zero-copy read-only mounted, no network) → the result is normalised to
`bacmap.advstats_result/1` (estimates/CIs/p/diagnostics; failures pass through verbatim).
The script is not agent-written: **plan confirmation is the authorisation — no mining
gate**; spec/script/output SHA-256 go to the research ledger, and a changed data table
conflicts at confirmation. Build the image locally:

```bash
podman --cgroup-manager=cgroupfs build -t bacmap-stats:r45 docker/stats/r45
```

Methods and R engines: `mixed_logistic` (lme4 glmer), `iptw` (WeightIt+survey),
`matching` (MatchIt 1:1 nearest), `survival_km` (survfit+survdiff), `cox`
(coxph+cox.zph).

### Research-session tasks (ADR-23: the research plan type)

A `research` plan can also create a deterministic AMR association draft (equivalent to
the CLI `research create`, but going through plan confirmation and task auditing):

```json
{"task_type": "research", "analysis": "session",
 "run_id": "5468...", "gene": "CARB-23", "test_name": "meropenem",
 "profile": "open-test"}
```

### Sample size and power (a priori design)

Deterministic normal approximation for comparing two proportions (the P1 association
design generalised), pure stdlib:

```bash
# plan a new study: expected resistant proportions per group -> n per group
bacmap research stats power --p1 0.65 --p2 0.45 --power 0.8

# express the design as baseline prevalence + target OR (p1 is derived)
bacmap research stats power --baseline 0.2 --odds 4

# fixed design -> achieved power
bacmap research stats power --p1 0.65 --p2 0.45 --n1 130 --n2 130

# reuse a session's observed proportions as planning assumptions
bacmap research stats power --session rs-0123456789ab
```

The output is `bacmap.power_two_proportions/1`: n per group and total, proportions,
alpha/power/ratio and cautions (extreme proportions <0.05/>0.95 or n<30 per group
suggest an exact method). **Power is a design input**: proportions must come from prior
knowledge or documented planning assumptions — never present post-hoc power of the data
being tested as evidence (the session mode's `achieved_power_at_current_n` is
descriptive only).

Over MCP (D2, read-only compute): `bacmap_research_power`.

### External validation (Woolf homogeneity)

Compare the derivation cohort's 2×2 association against an independent validation
cohort:

```bash
bacmap research stats validate --derivation rs-aaa --validation rs-bbb
```

The output `bacmap.external_validation/1` carries each cohort's OR/95% CI (0.5
correction), the fixed-effects pooled OR, the Q statistic with a chi-square (df=1)
p-value, and a consistency verdict. **Consistency is not replication success** — the
validation cohort may be underpowered (pair with `stats power`); heterogeneity means
the estimates must not be pooled without explaining the difference.

### Submission package

```bash
bacmap research package <study_id> --out ./submission --json
```

The package contains:

- `submission_manifest.json` — study, readiness gates, blockers, file hashes, data/code
  availability statements;
- `strobe_checklist.json` / `strobe_checklist.md` — deterministic STROBE draft with
  met/partial/missing items and evidence IDs;
- `artifacts/<session_id>/...` — session figures, reports and manuscripts copied with SHA-256;
- `supplementary/analyses.json` + `analyses.tsv` — persisted analysis results with hashes;
  the manifest also carries an `analyses` summary list.

The checklist is a draft, not a publication approval. Narrative items (abstract, discussion,
limitations, generalisability, funding/conflicts) remain `missing` until a human completes them.
Gate pass is necessary, not sufficient.

Over MCP (D2, read-only): `bacmap_research_reporting_checklist`.


## 13. Research requests (agent → human)

Natural-language instructions can start as a **draft request**, not an execution:

1. the agent calls MCP `bacmap_research_request` with the question, run IDs,
   gene/phenotype, analysis type, optional members/plan spec and a note. This writes only a
   draft to `research.sqlite`; it creates no Study/Cohort/Plan and runs nothing;
2. the Web **研究请求收件箱** lists proposed requests; the human reviews/edits the members and
   plan spec and clicks **确认并创建**;
3. bacmap creates Study → frozen Cohort → frozen Plan → optional session, and records the IDs
   on the request;
4. **拒绝** marks the request rejected with a note.

CLI fallback:

```bash
bacmap research request create --question "..." --run-id run-1 \
  --gene blaKPC-33 --test-name meropenem --analysis association
bacmap research request list
bacmap research request approve <request_id> --note "approved"
bacmap research request reject <request_id> --note "not needed"
```

MCP (D2+, local-trusted): `bacmap_research_request`, `bacmap_research_requests`.


## 14. Figure iteration

Drafts are first-class objects with feedback and a finalization gate:

1. upload an SVG/PNG/PDF draft on the session page (≤10 MiB), with a note;
2. the **Figure 迭代** gallery lists drafts, SHA-256, author and status;
3. add feedback per draft; the draft stays `draft`;
4. **最终 attach** finalizes it as the custom figure (`figure_custom` + provenance manifest);
   **拒绝** marks it rejected.

Only finalized drafts enter the submission package. Draft upload is Web-only; agents can list
drafts and feedback over MCP (`bacmap_research_figure_drafts`) but cannot finalize them.

CLI fallback:

```bash
bacmap research figure drafts <session_id>
bacmap research figure feedback <draft_id> --text "use colorblind palette"
bacmap research figure finalize <draft_id> --recipe custom [--code plot.py]
bacmap research figure reject <draft_id> --note "wrong layout"
```


## 15. Markdown rendering and package history

Session pages render `report.md` and `manuscript.md` with a small safe Markdown subset
(headings, lists, tables, code, bold/italic, links). Raw HTML is escaped and links are limited
to http(s), mailto and relative paths.

Package builds are versioned under `research/packages/<study_id>/<package_id>/` and recorded in
`research.sqlite`:

- `GET /research/studies/{study_id}/packages` — history;
- `POST /research/studies/{study_id}/packages` — build a new package (label optional);
- `GET /research/packages/{package_id}` — manifest, checklist, files, blockers;
- `GET /research/packages/{package_id}/download.zip` — ZIP download.

The older `/research/studies/{study_id}/package` route remains as a quick rebuild view.


## 16. Checklist editing and sign-off

`/research/studies/{study_id}/checklist` lets a human edit the deterministic STROBE draft:

- per-item status (`met`/`partial`/`missing`/`not_applicable`), evidence and note;
- **保存草稿** stores overrides in `checklist_reviews` (migration 8);
- **签字确认** requires no `missing` item and records reviewer/time/note;
- **重置** removes overrides and returns to the automatic draft.

Package builds merge the current overrides, so the manifest carries the edited checklist and
`checklist_review` status. Sign-off is a reporting aid, not a replacement for G0–G3 or human
publication review.


## 17. Evidence graph

Research objects are linked automatically in `evidence_edges`:

| Edge | Meaning |
|---|---|
| `cohort --COHORT_OF--> study` | cohort belongs to a study |
| `plan --PLAN_OF--> study` / `plan --PLANS_COHORT--> cohort` | plan provenance |
| `session --PART_OF--> study` / `USES_COHORT` / `GENERATED_BY` | session provenance |
| `claim --CLAIM_OF--> study` / `SUPPORTED_BY--> session` | claim evidence |
| `experiment --EXPERIMENT_OF--> study` / `TESTS--> plan` | execution ledger |
| `checklist --CHECKLIST_OF--> study` | checklist edit/sign-off |
| `package --PACKAGE_OF--> study` | submission package |
| `request --REQUEST_OF--> study` | approved research request |

Edges are idempotent (`ensure_edge`), shown on the Study and Session pages, and readable over
MCP with `bacmap_research_evidence` or CLI `bacmap research evidence <identifier>`.


## 18. Persisted analysis results

Deterministic results can be saved as first-class objects linked to a Study:

- logistic / power / external-validation / advanced-statistics results（Web 表单可填
  Study 自动保存；CLI 支持 `--study`；容器化的 advstats 经 `research` 计划另行留痕）；
- phylogenetic profile/plan/XML (Web "保存到 Study" action; generic CLI save).

Each record stores `analysis_id`, type, title, input paths + SHA-256, params, result JSON,
`result_sha256`, author/time, and an `ANALYSIS_OF` evidence edge.

```bash
bacmap research analysis list --study <study_id>
bacmap research analysis show <analysis_id>
bacmap research analysis save --study <study_id> --type phylo --result result.json \
  --input alignment.fasta --title "core alignment"
```

Web: `/research/studies/{study_id}/analyses` and `/research/analyses/{analysis_id}`.
MCP (read-only): `bacmap_research_analyses`, `bacmap_research_analysis`.

## 19. Tutorial: driving research from an external agent (DSH)

This tutorial covers the two questions asked most often: *how do I talk to bacmap from DSH?* and
*what actually counts as a research project?*

### 19.1 One-time setup

Register the MCP server in the DSH profile you use (`$DSH_HOME` defaults to `~/.dsh`; each
`profiles/<name>/` directory carries its own copy — edit the profile you actually launch):

```yaml
# $DSH_HOME/profiles/<profile>/cordis.patch.yml
- insert:
  - id: mcp-bacmap
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: bacmap
      transport: stdio
      command: pixi
      args: ['run', '--manifest-path', '/path/to/bacmap/pixi.toml', '-e', 'default',
             'bacmap', 'start', 'mcp', '--profile', 'local-trusted']
      failOnStartupError: true
```

`--profile cloud` (the default) is the right choice when the harness model is a cloud LLM —
including DSH with `deepseek-account`. The cloud profile exposes D1 by default and at most D2
(admin relaxation via `[llm.data_policy] cloud_max_data_class = "D2"`); D3/D4 never leave the
local network (ADR-16). Research session content is D2, so it appears once the admin relaxes the
cloud ceiling to D2. Use `--profile local-trusted` (D4) **only when the harness talks to a local or
intranet model** — it is gated by `[mcp] allow_local_trusted = true` and must not be used with
cloud endpoints.

Then install the role guidance and check the wiring:

```bash
bacmap agent install --harness generic --with-skills   # DSH uses generic + .bacmap/skills
bacmap agent doctor
dsh tui --dump-config
```

Connectivity check: ask the agent to “list bacmap research capabilities” — it should call
`bacmap_research_capabilities`, which is visible in every profile.

### 19.2 Retrieval vs research: which one is my question?

| What you want | It is | Tool / surface |
|---|---|---|
| “Which strains carry gene X?” | **retrieval** (read-only) | `bio_search_samples` (`organism` + `amr_gene`), `bio_query_lab_results`, `bio_query_metadata` |
| “Is gene X associated with phenotype Y in this cohort?” | **research** (statistics) | `bacmap_research_request` → human confirms → session (2×2, OR/CI, Fisher p, figure, report) |

A lookup is not a research project; the research project starts when the cohort becomes a
reviewable statistical question with a governance profile and human sign-off.

### 19.3 Is `run_id` mandatory?

For a P1 session, yes — `run_id + gene + test_name` are required — but the run is only the
**cohort selector**, not the object being analysed:

```python
strain_ids = _run_strains(home, run_id)       # selects which isolates enter the analysis
genes      = _gene_present(home, strain_ids)  # gene presence from strain_amr_genes (whole GOM DB)
phenos     = _phenotypes(home, strain_ids)    # phenotype from lab_results (whole DB)
```

Practical consequences:

- Salmonella isolated in **one batch analyze run** → that `run_id` already means “all Salmonella in
  the database”; use it directly.
- Strains spread over **several runs** → propose with `run_ids` / `members` + `pathogen_scope`
  (Study/Cohort line, §13), or submit one batch analyze task first so a single cohort run exists.

### 19.4 End-to-end dialogue

```text
1. "Search all Salmonella carrying blaCTX-M-55 and show their ciprofloxacin results"
   → bio_search_samples { organism: "Salmonella", amr_gene: "blaCTX-M-55" } + bio_query_lab_results

2. "Is that cohort large enough for an association test?"
   → bacmap_research_power

3. "Propose a research request: blaCTX-M-55 carriage vs ciprofloxacin resistance,
    Salmonella scope, runs <run_id>"
   → bacmap_research_request (writes a `proposed` draft only)

4. Human step: Web → 研究请求收件箱 → review members/plan spec → 确认并创建
   → Study → frozen Cohort → frozen Plan → session with 2×2 / OR / figure / report
```

### 19.5 Boundaries you must know

1. **A proposal is not an execution.** `bacmap_research_request` only writes a draft; confirmation
   happens in bacmap's own surfaces (Web inbox, `bacmap research request approve`, `/api/v1`).
   MCP elicitation or harness tool approval is not confirmation evidence (ADR-21).
2. **P1 scope**: one AMR association per session, deterministic statistics, no LLM-written text and
   no new data collection. `open-test` output is labelled `TEST/UNVERIFIED`; `research` /
   `publication` are `REVIEW REQUIRED`.
3. **Data prerequisites**: an existing run (`runs.sqlite`), the gene in `strain_amr_genes`
   (`gom.sqlite`) and the phenotype in `lab_results`. If they are missing, run an analyze task or
   ingest lab results first.
