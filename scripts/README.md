# Scripts

Data-preparation helpers used around bacmap runs. They are **not** part of the
bacmap runtime: run them by hand on your data directories before ingestion.

| Script | Use |
|---|---|
| `rename_fastq2.py` | Normalise paired FASTQ names to `<sample>_R1/R2.fastq.gz` (supports `.fq.gz`, digit-only pair ids, complex sample names; newest). |
| `rename_fastq1.py` | Earlier iteration with argparse + `.fq.gz` support. |
| `rename_fastq.py` | First version (`.fastq.gz` only). |

Keep the newest iteration when in doubt; the older ones stay for reference.
Add new helpers here with a one-line description in this README.
