# bacmap Tool Reference

**English** | [简体中文](tools.zh-CN.md)

The tool registry in `bacmap.tools.registry` is the single catalog of what bacmap can do. Each entry is a `ToolSpec` with a name, version, description, effect, and trust layer. One source of truth feeds the MCP server, the Hermes plugin, and the built-in agents. This page documents all 23 registered tools; all currently sit at version 0.1.0.

Every tool carries an effect label. `read` tools query stored results. `compute` tools run analysis or wrap external binaries without writing persistent state. `write` tools change the GOM or the database, and they are never registered into MCP directly. The MCP server exposes the 20 read/compute tools plus two task tools, `bacmap_submit_task` and `bacmap_task_status`. Submitting a task through that pair is the sole write entry point. In read-only mode (`bacmap mcp --read-only`), even the task tools stay unregistered.

Trust layers mark how much autonomy the calling layer has: L1 is the fixed pipeline, invoke only, no rewriting; L2 is controlled exploration in a sandbox with human review; L3 is free conversation behind gates. The 23 tools split into 7 read, 13 compute, and 3 write. The three write tools are `bio_analyze_pathogen`, `bio_add_lab_result`, and `bio_add_metadata`.

## Summary

| Tool | Effect | Purpose |
| --- | --- | --- |
| bio_add_lab_result | write | Record a wet lab result (AST, serology, biochemical, PCR) for a sample |
| bio_add_metadata | write | Add or update strain background and epidemiological metadata |
| bio_align | compute | Align reads to a reference genome (BWA-MEM, minimap2, STAR) |
| bio_analyze_pathogen | write | Run the full pathogen analysis pipeline for a sample |
| bio_blast | compute | Run a BLAST search against NCBI or a local subject file |
| bio_cgmlst | compute | Trace a sample's cgMLST profile against the local reference library |
| bio_diagnose | read | Diagnose pipeline failures from Snakemake logs or stderr |
| bio_fastq_qc | compute | Quality control for FASTQ files with a compact JSON report |
| bio_gene_scan | compute | Scan contigs for AMR, virulence, serotype, or plasmid genes |
| bio_generate_report | compute | Generate an HTML report with results and evidence chain |
| bio_get_result | read | Retrieve the analysis summary for a completed sample |
| bio_list_samples | read | List all samples and their analysis status |
| bio_query_lab_results | read | Query wet lab experiment results for a sample |
| bio_query_metadata | read | Query strain background metadata with epidemiological filters |
| bio_review_flags | read | List NLI Reflector audit events flagged for human review |
| bio_samtools | compute | Wrap common samtools operations on SAM/BAM/FASTA files |
| bio_search_samples | read | Find strains by serotype, MLST ST, AMR gene, organism, or keyword |
| bio_seq_convert | compute | Convert sequence files between formats |
| bio_seq_ops | compute | Run sequence operations such as translation, ORF finding, and k-mer counting |
| bio_seq_stats | compute | Compute statistics for a sequence file |
| bio_snp_tree | compute | Retrieve the cohort SNP tree and pairwise SNP distances |
| bio_variant | compute | Call, filter, query, annotate, or build consensus from variants |
| bio_verify_result | compute | Run deterministic verification on results, with optional NLI reflection |

## Tool details

### bio_add_lab_result

Version `v0.1.0` | Effect: `write` | Trust layer: `L3`

Record a wet lab experiment result (AST, serology, biochemical, PCR) for a sample. Use this when the user wants to enter phenotypic data such as disk diffusion results, MIC values, or classical serotyping results.

**Parameters**

- `strain_id` *(required)*: `string`. Strain/sample identifier.
- `category` *(required)*: `string`. Test category: `ast`, `serology`, `biochemical`, `pcr`.
- `test_name` *(required)*: `string`. Test name (e.g. Ampicillin, O antigen, oxidase).
- `result` *(required)*: `string`. Raw result value (e.g. 16, O4, positive).
- `interpretation`: `string`. S, I, R, positive, negative.
- `method`: `string`. Method used (broth_microdilution, disk_diffusion, antiserum).
- `unit`: `string`. Unit (ug/mL, mm).

### bio_add_metadata

Version `v0.1.0` | Effect: `write` | Trust layer: `L3`

Add or update strain background metadata (patient name, age, isolation date, province, outbreak ID, etc.). Creates a new record or updates an existing one. Use this when the user wants to record or modify epidemiological information for a sample.

**Parameters**

- `strain_id` *(required)*: `string`. Strain/sample identifier.
- `data` *(required)*: `object`. Metadata fields to set. Core fields: `patient_name`, `patient_age`, `patient_gender`, `isolation_date`, `province`, `city`, `sample_source`, `outbreak_id`. Custom fields stored in extra JSON.

### bio_align

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Align sequencing reads to a reference genome. Wraps BWA-MEM (short-read DNA), minimap2 (long-read, RNA-seq), or STAR (RNA-seq splice-aware). Requires the relevant tool installed. Indexes the reference on first use. Produces a sorted, indexed BAM by default. Use bio_samtools for downstream SAM/BAM manipulation.

**Parameters**

- `aligner` *(required)*: `string`, enum `bwa-mem|minimap2|star`. Which aligner to use.
- `reference` *(required)*: `string`. Path to reference genome FASTA (will be indexed if needed).
- `reads` *(required)*: `array`. Read files: 1 for single-end, 2 for paired-end.
- `output_bam` *(required)*: `string`. Output BAM path (sorted + indexed by default).
- `preset`: `string`. minimap2 preset: map-pb, map-ont, splice, etc. (minimap2 only).
- `read_type`: `string`, enum `short|long`. Read type for auto aligner selection: 'long' routes FASTQ to minimap2, 'short' to BWA-MEM. Omit to auto-sniff read lengths from the FASTQ.
- `extra_args`: `string`. Extra CLI args passed verbatim to the aligner.

### bio_analyze_pathogen

Version `v0.1.0` | Effect: `write` | Trust layer: `L1`

Run the full pathogen analysis pipeline (QC, assembly, species identification via invA/uidA/ipaH three-gene routing, MLST, serotyping, AMR, virulence, plasmid, DEC pathotype, report). Works for Salmonella, DEC (E. coli), Shigella, EIEC; species routing is automatic. Returns a summary of results. For pipeline guidance and troubleshooting, load skill: skill_view('hermes_bacmap:run-pipeline').

**Parameters**

- `sample_id` *(required)*: `string`. Sample ID from samples.tsv.
- `cores`: `integer`. CPU cores (default 8).

### bio_blast

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Run a BLAST search. Two modes: (1) 'remote' queries the NCBI BLAST API (requires internet, no local database needed); (2) 'local' runs a local makeblastdb+blastn/blastp pipeline against a user-provided subject file (requires the blast+ CLI installed). Use this for sequence identification and homology discovery.

**Parameters**

- `mode` *(required)*: `string`, enum `remote|local`. 'remote' (NCBI) or 'local' (blast+ CLI).
- `query` *(required)*: `string`. Query: raw sequence, or path to a FASTA file if query_is_file=true.
- `query_is_file`: `boolean`. If true, 'query' is a file path.
- `program`: `string`, enum `blastn|blastp|blastx|tblastn|tblastx`. BLAST program (default blastn).
- `database`: `string`. Remote: NCBI DB name (nt, nr, refseq_rna, swissprot, etc.). Local: subject FASTA file path.
- `expect`: `number`. E-value threshold (default 10).
- `max_hits`: `integer`. Maximum number of hits to report (default 10).
- `output_file`: `string`. Optional: write tabular BLAST output here.

### bio_cgmlst

Version `v0.1.0` | Effect: `compute` | Trust layer: `L1`

Trace a single sample's cgMLST allele profile against the local reference library (EnteroBase HierCC convention, Hamming allele distance, missing-on-either excluded). Returns the top-N nearest references, the per-species verdict (outbreak/related/unrelated/undetermined), the thresholds applied, and any caveats (e.g. S. sonnei HC5/HC10 unreliable, V. parahaemolyticus UNVERIFIED). Use this for high-resolution source attribution when the user asks whether two isolates are part of the same outbreak cluster, or to find the nearest reference strain for a sample. Requires cgMLST typing to have been run and ingested (bio_analyze_pathogen covers this); call bio_analyze_pathogen first if no profile exists. For cgMLST threshold interpretation, load skill: skill_view('hermes_bacmap:interpret-results').

**Parameters**

- `sample_id` *(required)*: `string`. Sample ID whose cgMLST profile should be traced back.

### bio_diagnose

Version `v0.1.0` | Effect: `read` | Trust layer: `L1`

Diagnose pipeline failures by parsing Snakemake logs. Returns error type, root cause, affected rule, and suggested recovery commands. Use this when analysis fails or the user reports pipeline errors. Handles OOM, lock conflicts, missing tools, missing databases, missing input files, disk full, and Snakemake version issues.

**Parameters**

- `log_path`: `string`. Path to Snakemake log file. If omitted, reads the latest log automatically.
- `stderr_text`: `string`. Raw stderr text to diagnose (alternative to log_path).

### bio_fastq_qc

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Quality control for FASTQ files: per-base quality statistics, adapter contamination checks, duplication-rate estimate, and length distribution. Outputs a compact JSON report. For full graphical reports use FastQC via the shell, but this tool gives quick triage without external tools.

**Parameters**

- `files` *(required)*: `array`. One or more FASTQ file paths.
- `sample_reads`: `integer`. Subsample to at most N reads for speed (0 = all, default 100000).
- `adapter_file`: `string`. Optional FASTA of adapter sequences to check for contamination.
- `report_file`: `string`. Optional: write a markdown report here in addition to JSON.

### bio_gene_scan

Version `v0.1.0` | Effect: `compute` | Trust layer: `L1`

Scan assembled contigs against a gene database (card/vfdb/ecoh/plasmidfinder/resfinder) to detect AMR, virulence, serotype, or plasmid genes. Returns JSON with gene list, identity, coverage. Supports multi-database scanning in one call. For AMR gene clinical significance (ESBL/carbapenemase/AmpC), load skill: skill_view('hermes_bacmap:interpret-results').

**Parameters**

- `contigs_path` *(required)*: `string`. Path to assembled contigs FASTA.
- `database` *(required)*: `string`. Database name: card, vfdb, ecoh, plasmidfinder, resfinder, ncbi, megares, victors, ecoli_vf. Or comma-separated for multi-db.
- `min_identity`: `number`. Minimum % identity (default 80).
- `min_coverage`: `number`. Minimum % coverage (default 80).

### bio_generate_report

Version `v0.1.0` | Effect: `compute` | Trust layer: `L1`

Generate HTML report with all results, verifier output, and evidence chain. Returns file path.

**Parameters**

- `sample_id` *(required)*: `string`. Sample ID.

### bio_get_result

Version `v0.1.0` | Effect: `read` | Trust layer: `L1`

Retrieve analysis summary for a completed sample. Returns species type (Salmonella/E.coli/Shigella), MLST ST, serotype, ipaH status, DEC pathotype, AMR/virulence/plasmid gene counts. For result interpretation, load skill: skill_view('hermes_bacmap:interpret-results').

**Parameters**

- `sample_id` *(required)*: `string`. Sample ID.

### bio_list_samples

Version `v0.1.0` | Effect: `read` | Trust layer: `L1`

List all samples and their analysis status.

**Parameters**: none

### bio_query_lab_results

Version `v0.1.0` | Effect: `read` | Trust layer: `L3`

Query wet lab experiment results (AST drug susceptibility, classical serology, biochemical tests, PCR) for a sample. Supports filtering by sample, category, test_name, result, and interpretation. Use this when the user asks about phenotypic results, antibiotic resistance testing, or serological findings.

**Parameters**

- `sample_id`: `string`. Strain ID to look up (optional). If omitted, returns all results.
- `category`: `string`. Filter by category: `ast`, `serology`, `biochemical`, `pcr`, `pfge`.
- `test_name`: `string`. Filter by test name (e.g., Cefotaxime, Ciprofloxacin, O-antigen).
- `result`: `string`. Filter by result value (e.g., >=8, Positive, Negative).
- `interpretation`: `string`. Filter by interpretation: R (resistant), S (susceptible), I (intermediate), positive, negative.

### bio_query_metadata

Version `v0.1.0` | Effect: `read` | Trust layer: `L3`

Query strain background metadata (patient info, isolation details, outbreak linkage) from the strain_metadata table. Supports filtering by province, outbreak_id, sample_source, and date range. Use this when the user asks about sample background, epidemiological info, or outbreak investigations.

**Parameters**

- `strain_id`: `string`. Specific strain ID to look up (optional).
- `province`: `string`. Filter by province.
- `outbreak_id`: `string`. Filter by outbreak ID.
- `sample_source`: `string`. Filter by sample source (clinical/food/environment).
- `isolation_date_from`: `string`. Date range start (YYYY-MM-DD).
- `isolation_date_to`: `string`. Date range end (YYYY-MM-DD).

### bio_review_flags

Version `v0.1.0` | Effect: `read` | Trust layer: `L1`

List Layer 3 NLI Reflector audit events (nli_reflected) from the GOM: which samples were flagged by the AI interpretation self-check, with contradiction rate, threshold, and the contradicted claims. This is the human-review read-back surface. Use it when the user asks which samples need review, what the AI got wrong, or to trace a flagged sample's audit trail.

**Parameters**

- `limit`: `integer`. Max events to return (default 50, newest first).

### bio_samtools

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Wrap common samtools operations: sort, index, view (filter/region), depth, flagstat, mpileup, faidx, idxstats. Requires samtools installed. Use this for any SAM/BAM file manipulation.

**Parameters**

- `operation` *(required)*: `string`, enum `sort|index|view|depth|flagstat|mpileup|faidx|idxstats|fasta_index`. samtools subcommand to run.
- `input` *(required)*: `string`. Primary input file (BAM/SAM/FASTA).
- `output`: `string`. Output file path (where applicable).
- `region`: `string`. Genomic region for 'view' (e.g. 'chr1:1000-5000').
- `flags`: `string`. samtools view flags (e.g. '-F 4' to exclude unmapped, '-q 30').
- `extra_args`: `string`. Extra args passed verbatim to samtools.

### bio_search_samples

Version `v0.1.0` | Effect: `read` | Trust layer: `L3`

Search across all ingested sample results to find strains by serotype, MLST ST, AMR gene, organism, or free-text keyword. Supports multi-field AND queries (e.g., serotype=Typhimurium AND amr_gene=blaCTX-M-15). Use for traceability: 'find all strains with same serotype' or 'which strains carry gene X'.

**Parameters**

- `query`: `string`. Free-text search (fallback). Searches organism, strain_id, serotype, MLST, AMR genes via FTS5.
- `serotype`: `string`. Exact serotype match (e.g., Typhimurium, Enteritidis).
- `mlst_st`: `string`. MLST ST number (e.g., ST19, 19). Normalized to ST-prefix.
- `amr_gene`: `string`. AMR gene name, exact match (e.g., blaCTX-M-15, tet(A)).
- `organism`: `string`. Organism name, substring match (e.g., Salmonella, E.coli).
- `limit`: `integer`. Max results (default 50).

### bio_seq_convert

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Convert a sequence file between formats: FASTA, FASTQ, GenBank, EMBL, NEXUS, PhylIP, Stockholm, Clustal, GFF. Useful before running a tool that requires a specific input format.

**Parameters**

- `input_file` *(required)*: `string`. Input sequence file.
- `output_file` *(required)*: `string`. Output file path.
- `output_format` *(required)*: `string`, enum `fasta|fastq|genbank|embl|nexus|phylip|stockholm|clustal|gff`. Target format.

### bio_seq_ops

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Perform sequence operations: reverse-complement, translate, GC-skew, motif search, ORF finding, restriction-site detection, k-mer counting. Operates on a sequence string or a record ID from a loaded file. Use this for ad-hoc sequence analysis without invoking alignment tools.

**Parameters**

- `operation` *(required)*: `string`, enum `reverse_complement|translate|gc_content|gc_skew|motif_search|find_orfs|restriction_sites|kmer_count`. Operation to perform.
- `sequence`: `string`. Raw sequence (DNA or RNA). For 'translate' use DNA; codons are read from position 0 unless a 'frame' is given.
- `file`: `string`. Optional: read sequence(s) from this file instead of 'sequence'.
- `record_id`: `string`. If 'file' is given, operate on this specific record.
- `motif`: `string`. For 'motif_search': IUPAC motif pattern (e.g. 'GANTC').
- `frame`: `integer`, enum `0|1|2`. Reading frame for 'translate' (default 0).
- `min_orf_len`: `integer`. Minimum ORF length in codons for 'find_orfs' (default 30).
- `k`: `integer`. k for 'kmer_count' (default 3).
- `top`: `integer`. Return top-N results for 'kmer_count' (default 20).
- `output_file`: `string`. Optional: write full result (e.g. all ORFs/k-mers) here.

### bio_seq_stats

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Compute statistics for a sequence file (FASTA, FASTQ, or GenBank). Returns counts (records, total bases), length distribution (min/max/mean/N50), and GC content. For FASTQ, also per-base quality scores and Q-score distribution. Use this as the first step of any sequencing analysis to understand the input data.

**Parameters**

- `file` *(required)*: `string`. Absolute or relative path to the sequence file.
- `format`: `string`, enum `fasta|fastq|genbank|auto`. File format. 'auto' detects from extension (default).
- `histogram_bins`: `integer`. Number of bins for length/quality histograms (default 20).

### bio_snp_tree

Version `v0.1.0` | Effect: `compute` | Trust layer: `L1`

Retrieve the cohort-level SNP phylogenetic tree and pairwise distance matrix. Returns Newick tree string, sample list, SNP site count, missing rate, and all pairwise SNP distances. Use this when the user asks about genetic relatedness, outbreak clusters, phylogenetic relationships, or SNP distances between samples. For SNP distance interpretation thresholds (0-5=outbreak, 6-15=possibly related), load skill: skill_view('hermes_bacmap:interpret-results').

**Parameters**: none

### bio_variant

Version `v0.1.0` | Effect: `compute` | Trust layer: `L2`

Call or manipulate variants. Operations: 'mpileup_call' (bcftools mpileup+call from a BAM), 'filter' (bcftools filter on quality/depth), 'query' (bcftools query to extract fields), 'annotate' (add VCF annotations), 'consensus' (bcftools consensus to apply variants to a reference). Requires bcftools and/or samtools.

**Parameters**

- `operation` *(required)*: `string`, enum `mpileup_call|filter|query|annotate|consensus`. Variant operation to perform.
- `input` *(required)*: `string`. Input file (BAM for calling, VCF for filtering/query/annotate).
- `output`: `string`. Output file path.
- `reference`: `string`. Reference FASTA (required for mpileup_call, consensus).
- `query`: `string`. bcftools query format string (e.g. '%CHROM\t%POS\t%REF\t%ALT\n').
- `filter_expr`: `string`. bcftools filter expression (e.g. 'QUAL>30 && DP>10').
- `extra_args`: `string`. Extra args passed verbatim to bcftools.

### bio_verify_result

Version `v0.1.0` | Effect: `compute` | Trust layer: `L1`

Run deterministic verification on results. Checks species, MLST, serotype, AMR. Flags critical resistance (CTX-M/NDM/KPC/mcr-1) for human review. Optionally pass interpretation_text (your own draft interpretation of the sample) to also run the Layer 3 NLI Reflector: claims in the text are checked against the sample's facts, and a high contradiction rate flags NEEDS_HUMAN_REVIEW. For understanding verification rules, load skill: skill_view('hermes_bacmap:interpret-results').

**Parameters**

- `sample_id` *(required)*: `string`. Sample ID.
- `interpretation_text`: `string`. Optional LLM interpretation text to reflect against sample facts (Layer 3 NLI Reflector).

---

Spec source: the runtime registry in `bacmap.tools.registry`. It is the authoritative record of tool names, versions, effects, trust layers, and parameter schemas. When the registry changes, regenerate this document.
