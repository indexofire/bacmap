# Flexible Workflow Architecture (PLAN #5)

> Status: design proposal (2026-11-09); platform probing and the long-read/hybrid assembly
> rules landed in 0.1.5.

## Problem

Fixed Snakemake pipelines are reproducible and auditable for routine surveillance, but they lack
flexibility for ad-hoc requests (for example, "add a virulence screen to this batch" or "try a
different assembler"). Agents and LLMs are good at understanding and decomposing exactly these
non-standard requests.

## Approach: a two-layer flexibility model

```
┌─────────────────────────────────────────────────────────┐
│ Fixed layer (routine surveillance)                      │
│ ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│ │ registry│──→│ smk     │──→│  gates  │──→│  GOM    │ │
│ │(pathogens│  │ rules   │   │(gate/   │   │(evidence│ │
│ │ .yaml)  │   │(determ.)│   │ audit)  │   │ chain)  │ │
│ └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│                                                          │
│  ✓ reproducible  ✓ auditable  ✓ same result for anyone  │
├─────────────────────────────────────────────────────────┤
│ Flexible layer (ad-hoc analysis)                        │
│ ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│ │ agent   │──→│ AI-built│──→│ human   │──→│ mine    │ │
│ │(understand│ │ smk+args│   │ review  │   │ sandbox │ │
│ │ request)│   │         │   │(confirm)│   │ execute │ │
│ └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│                                                          │
│  ✓ flexible  ✓ agent-assisted  ✓ human gate  ✓ one-off  │
└─────────────────────────────────────────────────────────┘
```

### Fixed layer (unchanged)

- **Registry-driven**: `pathogens.yaml` registers species → generic `species.smk`/
  `gspec_typing.smk` rules route automatically. A new species is a YAML entry, not rule code.
- **Deterministic pipeline**: gside (species) → flye/spades (assembly) → gspec (typing) → gmlst
  (MLST) → verifier → report. Every step is reproducible and hashed.
- **Gates and audit**: analysis_claims gate, STROBE checklist, G0–G3 publication gates.

### Flexible layer (AI-assisted)

Three paths with increasing trust requirements:

| Path | What the agent does | What the human does | Execution environment | Lifecycle |
|---|---|---|---|---|
| **A. research plan** | propose a typed analysis (session/advstats) | confirm the plan in bacmap | container (`bacmap-stats`) | results persist |
| **B. mine sandbox** | write a free-form script (Python/R) | review the script + sign | mine sandbox (no network) | artifacts enter the mining gate |
| **C. AI-generated smk** (new) | generate a custom Snakefile + parameters | review the smk rules + confirm | separate sandbox (no network) | **one-off, archived after the run** |

#### Path C: AI-generated temporary smk (the core addition)

```
User request: "screen these 10 isolates for blaNDM + re-assemble with flye"
    ↓
Agent: read the registry (confirm species) → generate Snakefile + config.yaml
    ↓
bacmap: static validation (syntax/rule names/path allowlist)
    ↓
Human: review the generated smk (fully shown in the confirmation UI) → confirm
    ↓
Sandbox execution (no network, read-only inputs, output hashes recorded)
    ↓
Archive: smk file + config + run log + artifact hashes → one-off record
```

**Key constraints**:

- Generated smk files may only reference external tools registered in the registry
  (gside/gspec/gmlst/flye, …).
- Input paths must come from the plan input fingerprint (verified at confirmation time).
- Runs in a separate sandbox (same shape as mine, but with snakemake installed).
- Archived runs cannot be re-run (one-off by design — promote frequent needs to a fixed-layer
  rule instead).

## Platform routing rules (PLAN #4)

| Detection | Assembler | Trigger | smk rule |
|---|---|---|---|
| illumina | spades/shovill (existing) | median read length ≤400 bp, R1/R2 only | `assembly.smk` |
| nanopore | flye `--nano-hq` (R10.4.1 SUP, Q20+; legacy R9.4 can set `--nano-raw`) | median read length ≥1 kb, wide distribution, longread only | `assembly_long.smk` |
| pacbio_hifi | flye `--pacbio-hifi` | median read length ≥5 kb, tight distribution, longread only | `assembly_long.smk` |
| hybrid (short + long) | unicycler | the same sample has R1/R2 + longread | `assembly_long.smk` |
| special | trycycler | user writes `trycycler` in the samples.tsv `platform` column (requires R1/R2 + longread) | `assembly_long.smk` |

Trycycler must be installed separately: its conda package currently requires Python <3.11, while
bacmap runs on Python 3.12. Flye and unicycler are installed with the default pixi environment.

Probing is triggered by `bacmap detect` or `task submit --fastq-dir` (`core/fastq_probe.py`), and
the result is written to the samples.tsv `platform` column. Users can override the probe result
in that column (`ont` / `pacbio_hifi`).

### New samples.tsv column (0.1.5)

```
sample    species    R1       R2       longread               assembly    platform
SAMP-001  SAL        ...      ...                             (empty)     illumina
SAMP-002  VPA        (empty)  (empty)  /path/ont_reads.fq     (empty)     nanopore
SAMP-003  VPA        ...      ...      /path/ont_reads.fq     (empty)     ont
SAMP-004  ECO        (empty)  (empty)                         .../fna     (empty)
```

- `longread`: long-read FASTQ path (auto-detected or filled in manually)
- `platform`: sequencing platform (`ont`/`pacbio_hifi`/`illumina`/`trycycler`; the probe result
  can be overridden)

Trycycler is an advanced, best-effort path: its `reconcile` step may require manual curation of
the clusters; inspect `clusters/cluster_*` if the rule fails.

## Resource arbitration (PLAN #10)

When `[llm.resources] co_located = true`:

- Snakemake `--cores` automatically subtracts the cores reserved for the LLM (4 by default,
  configurable).
- While LLM inference is active (an active connection is detected), the pipeline runs with
  reduced cores.
- When the LLM is idle, the pipeline returns to full cores.

When `co_located = false` (recommended):

- The LLM runs on the GPU server (`location = "lan"` or `"cloud"`).
- Bioinformatics runs at full speed on the x86_64 server.
- No contention.

## Next implementation steps (by priority)

1. ✅ FASTQ platform probing (`core/fastq_probe.py`, implemented)
2. ✅ samples.tsv `platform` column (manual override of the probe result; no separate CLI flag)
3. Path C: add `analysis=custom_smk` to `research` plans (generate → review → sandbox → archive)
4. ✅ flye/unicycler/trycycler smk rules (new `rules/assembly_long.smk`)
5. Resource arbitration logic (automatic core reduction when `co_located=true`)
