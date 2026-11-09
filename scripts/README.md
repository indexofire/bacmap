# Scripts

Data-preparation helpers and installation tooling for bacmap.

## Installation

| Script | Use |
|---|---|
| `setup.sh` | One-line installer: `curl -fsSL https://raw.githubusercontent.com/indexofire/bacmap/main/scripts/setup.sh \| bash` |

## Data preparation

These are **not** part of the bacmap runtime — run them by hand on your data
directories before ingestion.

| Script | Use |
|---|---|
| `renamefq.py` | Normalise paired FASTQ names to `<sample>_R1/R2.fastq.gz` |
| `extract_genes.sh` | Extract gene CDS intervals from GFF file(s) |
| `json2tsv.py` | Flatten NCBI datasets JSON into a TSV table |
| `setup_annotation_dbs.py` | Download Bakta and eggNOG-mapper databases into `$BACMAP_HOME/refs/` (Bakta light ≈4 GB; eggNOG ≈tens of GB) |
