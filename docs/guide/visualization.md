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

## API endpoints

See [HTTP API](../reference/api.md) for the complete `/api/v1/gvixb/...` endpoint list.

## Tests

 bacmap host integration is covered by:

```bash
pixi run -e dev pytest -q tests/unit/test_gvixb.py
```

gvixb frontend algorithms are tested inside the gvixb project.
