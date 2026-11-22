# gvixb integration

**gvixb** is an independent local 3D bacterial genome visualization framework. bacmap is a host
application: it prepares result adapters and JSON endpoints, while gvixb renders the visualization.
The local checkout is expected to be a sibling of this repository at `../gvixb`.

The canonical gvixb documentation is maintained inside the gvixb project:

```text
<gvixb-project>/docs/
├── index.md
├── installation.md
├── configuration.md
├── views.md
├── data-contracts.md
├── integration-bacmap.md
├── plugins.md
├── development.md
└── troubleshooting.md
```

This bacmap page only records host-side responsibilities.

## Entry points

The Vue console's sample, run and GOM pages list the gvixb views that actually exist for the
current result (`/api/v1/samples/{id}` → `gvixb`, `/api/v1/runs/{id}` and
`/api/v1/gom/objects/{id}` → `gvixb_views`); legacy `/samples/...`, `/runs/...` and `/gom/...`
deep links redirect to the console.

The result page also exposes a **Demo** button in the top-right corner (`/gvixb/demo/`), which
serves the upstream gvixb demo dataset from the same local server (no external network).

Run-scoped gvixb pages also have a **view** selector for the current isolate's assembly/annotation
circle and the run's tree/mst views, and accept a same-origin
`?view=phylo&endpoint=/api/v1/gvixb/...` override. The demo page's Phylo/MST buttons open `/static/gvixb/demo/preview.html` (the same modular preview shell as
the upstream `scripts/preview/preview-dev.html`); the upstream preview-dev file itself is not shipped.

| bacmap page | gvixb view |
|---|---|
| Console sample page (`/console/samples/<dataset>`) | latest-result assembly or annotated circle |
| Console run page (`/console/runs/<run_id>`) | run-scoped assembly, trees and MST |
| Console GOM page (`/console/gom/<object_id>`) | result linked to a GOM analysis object |
| Result pages under `/gvixb/...` | the 3D visualization itself (assembly, circle, tree, MST) |

## bacmap responsibilities

- run/task resolution and `succeeded` checks;
- run-scoped result reads from `results/runs/<task_id>/`;
- dataset/group membership checks;
- fixed-file allowlisting and symlink-escape rejection;
- parsing assembly FASTA, CARD/VFDB TSVs, Bakta GFF3, eggNOG TSVs, tree summaries and gmlst MST;
- serving `/api/v1/gvixb/...`;
- serving gvixb assets from `/static/gvixb/`;
- Web authentication and CSP/security headers.

gvixb is not given direct access to `results/`, SQLite files or bacmap configuration.

## Static bundle

gvixb owns and publishes:

```text
<gvixb-project>/web/
```

bacmap vendors it at:

```text
src/bacmap/interfaces/web/static/gvixb/
```

When changing gvixb, sync from the gvixb project:

```bash
cd <gvixb-project>
python3 scripts/sync-bacmap.py --bacmap /path/to/bacmap
```

## SNP tree payload (`gvixb.phylogeny/v2`)

`/api/v1/gvixb/runs/{run_id}/tree/snp/{group}` emits the gvixb phylogeny v2
contract: the IQ-TREE Newick (declared `unrooted`, `inferred`), `SH-aLRT/UFBoot`
support annotations when the ≥4-sample bootstrap ran, per-sample metadata,
presence/absence matrices and a compressed pairwise-SNP distance triangle.

- **Metadata whitelist** — only epidemiological strain fields are emitted:
  `isolation_date`/`collection_date` (ISO precision preserved: `YYYY`,
  `YYYY-MM`, `YYYY-MM-DD`), `province`/`city`/`district`, `sample_source`/
  `sample_type`/`food_category`/`food_name` and `outbreak_id`, plus `ST` and
  `serotype` from the per-sample report. All D4 identifying fields
  (`patient_*`, `onset_date`, `hospital`, `submit_date`, `cluster_note`, …)
  and `extra` are never sent to the browser.
- **Matrices** — `amr` (CARD), `vf` (VFDB) and `plasmidfinder` gene presence
  matrices: `1` present, `0` screened-but-absent, `null` when a sample has no
  screen result. A matrix is omitted entirely if no sample was screened.
- **Distances** — upper-triangle SNP differences (`null` for missing pairs).
- **cgMLST** — the tree endpoint is withdrawn for cgMLST cohorts: the
  cgMLST "Newick" is an MST serialised as a tree (aggregated labels, samples
  on internal nodes), not a phylogeny. The HTML page redirects (307) to the
  MST view and the API returns 410; use
  `/api/v1/gvixb/runs/{run_id}/mst/{group}` instead.

## API endpoints

See [HTTP API](../reference/api.md) for the complete `/api/v1/gvixb/...` endpoint list.

## Tests

 bacmap host integration is covered by:

```bash
pixi run -e dev pytest -q tests/unit/test_gvixb.py
```

gvixb frontend algorithms are tested inside the gvixb project.
