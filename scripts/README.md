# Scripts

Data-preparation helpers used around bacmap runs. They are **not** part of the
bacmap runtime: run them by hand on your data directories before ingestion.

| Script | Use |
|---|---|
| `renamefq.py` | Normalise paired FASTQ names to `<sample>_R1/R2.fastq.gz` — supports `.fq.gz`/`.fastq.gz`, digit-only pair ids (converted to `R1`/`R2`), and complex sample names (sample id = text before the first underscore). |
| `extract_genes.sh` | Extract two genes' CDS intervals from GFF file(s), report whether they sit on the same contig; CSV output. Requires GNU parallel. |
| `json2tsv.py` | Flatten NCBI datasets JSON (BioSample attributes incl. serotype) into a TSV table. |

Add new helpers here with a one-line description in this README.
