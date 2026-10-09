"""Tool schemas — what the LLM reads to decide when to call each tool."""

# ---------------------------------------------------------------------------
# bio_seq_stats — summarize a FASTA/FASTQ/GenBank file
# ---------------------------------------------------------------------------
SEQ_STATS = {
    "name": "bio_seq_stats",
    "description": (
        "Compute statistics for a sequence file (FASTA, FASTQ, or GenBank). "
        "Returns counts (records, total bases), length distribution "
        "(min/max/mean/N50), and GC content. For FASTQ, also per-base quality "
        "scores and Q-score distribution. Use this as the first step of any "
        "sequencing analysis to understand the input data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Absolute or relative path to the sequence file.",
            },
            "format": {
                "type": "string",
                "enum": ["fasta", "fastq", "genbank", "auto"],
                "description": "File format. 'auto' detects from extension (default).",
            },
            "histogram_bins": {
                "type": "integer",
                "description": "Number of bins for length/quality histograms (default 20).",
            },
        },
        "required": ["file"],
    },
}

# ---------------------------------------------------------------------------
# bio_seq_ops — in-memory sequence operations
# ---------------------------------------------------------------------------
SEQ_OPS = {
    "name": "bio_seq_ops",
    "description": (
        "Perform sequence operations: reverse-complement, translate, GC-skew, "
        "motif search, ORF finding, restriction-site detection, k-mer counting. "
        "Operates on a sequence string or a record ID from a loaded file. "
        "Use this for ad-hoc sequence analysis without invoking alignment tools."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "reverse_complement",
                    "translate",
                    "gc_content",
                    "gc_skew",
                    "motif_search",
                    "find_orfs",
                    "restriction_sites",
                    "kmer_count",
                ],
                "description": "Operation to perform.",
            },
            "sequence": {
                "type": "string",
                "description": (
                    "Raw sequence (DNA or RNA). For 'translate' use DNA; codons "
                    "are read from position 0 unless a 'frame' is given."
                ),
            },
            "file": {
                "type": "string",
                "description": "Optional: read sequence(s) from this file instead of 'sequence'.",
            },
            "record_id": {
                "type": "string",
                "description": "If 'file' is given, operate on this specific record.",
            },
            "motif": {
                "type": "string",
                "description": "For 'motif_search': IUPAC motif pattern (e.g. 'GANTC').",
            },
            "frame": {
                "type": "integer",
                "enum": [0, 1, 2],
                "description": "Reading frame for 'translate' (default 0).",
            },
            "min_orf_len": {
                "type": "integer",
                "description": "Minimum ORF length in codons for 'find_orfs' (default 30).",
            },
            "k": {
                "type": "integer",
                "description": "k for 'kmer_count' (default 3).",
            },
            "top": {
                "type": "integer",
                "description": "Return top-N results for 'kmer_count' (default 20).",
            },
            "output_file": {
                "type": "string",
                "description": "Optional: write full result (e.g. all ORFs/k-mers) here.",
            },
        },
        "required": ["operation"],
    },
}

# ---------------------------------------------------------------------------
# bio_fastq_qc — per-read quality control on FASTQ files
# ---------------------------------------------------------------------------
FASTQ_QC = {
    "name": "bio_fastq_qc",
    "description": (
        "Quality control for FASTQ files: per-base quality statistics, adapter "
        "contamination checks, duplication-rate estimate, and length distribution. "
        "Outputs a compact JSON report. For full graphical reports use FastQC via "
        "the shell, but this tool gives quick triage without external tools."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more FASTQ file paths.",
            },
            "sample_reads": {
                "type": "integer",
                "description": "Subsample to at most N reads for speed (0 = all, default 100000).",
            },
            "adapter_file": {
                "type": "string",
                "description": "Optional FASTA of adapter sequences to check for contamination.",
            },
            "report_file": {
                "type": "string",
                "description": "Optional: write a markdown report here in addition to JSON.",
            },
        },
        "required": ["files"],
    },
}

# ---------------------------------------------------------------------------
# bio_seq_convert — convert between sequence file formats
# ---------------------------------------------------------------------------
SEQ_CONVERT = {
    "name": "bio_seq_convert",
    "description": (
        "Convert a sequence file between formats: FASTA, FASTQ, GenBank, EMBL, "
        "NEXUS, PhylIP, Stockholm, Clustal, GFF. Useful before running a tool "
        "that requires a specific input format."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "input_file": {
                "type": "string",
                "description": "Input sequence file.",
            },
            "output_file": {
                "type": "string",
                "description": "Output file path.",
            },
            "output_format": {
                "type": "string",
                "enum": [
                    "fasta",
                    "fastq",
                    "genbank",
                    "embl",
                    "nexus",
                    "phylip",
                    "stockholm",
                    "clustal",
                    "gff",
                ],
                "description": "Target format.",
            },
        },
        "required": ["input_file", "output_file", "output_format"],
    },
}

# ---------------------------------------------------------------------------
# bio_blast — NCBI BLAST search
# ---------------------------------------------------------------------------
BLAST = {
    "name": "bio_blast",
    "description": (
        "Run a BLAST search. Two modes: (1) 'remote' queries the NCBI BLAST API "
        "(requires internet, no local database needed); (2) 'local' runs a local "
        "makeblastdb+blastn/blastp pipeline against a user-provided subject file "
        "(requires the blast+ CLI installed). Use this for sequence identification "
        "and homology discovery."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["remote", "local"],
                "description": "'remote' (NCBI) or 'local' (blast+ CLI).",
            },
            "query": {
                "type": "string",
                "description": (
                    "Query: raw sequence, or path to a FASTA file if query_is_file=true."
                ),
            },
            "query_is_file": {
                "type": "boolean",
                "description": "If true, 'query' is a file path.",
            },
            "program": {
                "type": "string",
                "enum": ["blastn", "blastp", "blastx", "tblastn", "tblastx"],
                "description": "BLAST program (default blastn).",
            },
            "database": {
                "type": "string",
                "description": (
                    "Remote: NCBI DB name (nt, nr, refseq_rna, swissprot, etc.). "
                    "Local: subject FASTA file path."
                ),
            },
            "expect": {
                "type": "number",
                "description": "E-value threshold (default 10).",
            },
            "max_hits": {
                "type": "integer",
                "description": "Maximum number of hits to report (default 10).",
            },
            "output_file": {
                "type": "string",
                "description": "Optional: write tabular BLAST output here.",
            },
        },
        "required": ["mode", "query"],
    },
}

# ---------------------------------------------------------------------------
# bio_align — read alignment with BWA / minimap2 / STAR
# ---------------------------------------------------------------------------
ALIGN = {
    "name": "bio_align",
    "description": (
        "Align sequencing reads to a reference genome. Wraps BWA-MEM (short-read DNA), "
        "minimap2 (long-read, RNA-seq), or STAR (RNA-seq splice-aware). Requires the "
        "relevant tool installed. Indexes the reference on first use. Produces a sorted, "
        "indexed BAM by default. Use bio_samtools for downstream SAM/BAM manipulation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "aligner": {
                "type": "string",
                "enum": ["bwa-mem", "minimap2", "star"],
                "description": "Which aligner to use.",
            },
            "reference": {
                "type": "string",
                "description": "Path to reference genome FASTA (will be indexed if needed).",
            },
            "reads": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Read files: 1 for single-end, 2 for paired-end.",
            },
            "output_bam": {
                "type": "string",
                "description": "Output BAM path (sorted + indexed by default).",
            },
            "preset": {
                "type": "string",
                "description": "minimap2 preset: map-pb, map-ont, splice, etc. (minimap2 only).",
            },
            "read_type": {
                "type": "string",
                "enum": ["short", "long"],
                "description": (
                    "Read type for auto aligner selection: 'long' routes FASTQ to minimap2, "
                    "'short' to BWA-MEM. Omit to auto-sniff read lengths from the FASTQ."
                ),
            },
            "extra_args": {
                "type": "string",
                "description": "Extra CLI args passed verbatim to the aligner.",
            },
        },
        "required": ["aligner", "reference", "reads", "output_bam"],
    },
}

# ---------------------------------------------------------------------------
# bio_samtools — SAM/BAM manipulation wrapper
# ---------------------------------------------------------------------------
SAMTOOLS = {
    "name": "bio_samtools",
    "description": (
        "Wrap common samtools operations: sort, index, view (filter/region), "
        "depth, flagstat, mpileup, faidx, idxstats. Requires samtools installed. "
        "Use this for any SAM/BAM file manipulation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "sort",
                    "index",
                    "view",
                    "depth",
                    "flagstat",
                    "mpileup",
                    "faidx",
                    "idxstats",
                    "fasta_index",
                ],
                "description": "samtools subcommand to run.",
            },
            "input": {
                "type": "string",
                "description": "Primary input file (BAM/SAM/FASTA).",
            },
            "output": {
                "type": "string",
                "description": "Output file path (where applicable).",
            },
            "region": {
                "type": "string",
                "description": "Genomic region for 'view' (e.g. 'chr1:1000-5000').",
            },
            "flags": {
                "type": "string",
                "description": "samtools view flags (e.g. '-F 4' to exclude unmapped, '-q 30').",
            },
            "extra_args": {
                "type": "string",
                "description": "Extra args passed verbatim to samtools.",
            },
        },
        "required": ["operation", "input"],
    },
}

# ---------------------------------------------------------------------------
# bio_variant — variant calling / manipulation
# ---------------------------------------------------------------------------
VARIANT = {
    "name": "bio_variant",
    "description": (
        "Call or manipulate variants. Operations: 'mpileup_call' (bcftools mpileup+call "
        "from a BAM), 'filter' (bcftools filter on quality/depth), 'query' (bcftools query "
        "to extract fields), 'annotate' (add VCF annotations), 'consensus' (bcftools consensus "
        "to apply variants to a reference). Requires bcftools and/or samtools."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "mpileup_call",
                    "filter",
                    "query",
                    "annotate",
                    "consensus",
                ],
                "description": "Variant operation to perform.",
            },
            "input": {
                "type": "string",
                "description": "Input file (BAM for calling, VCF for filtering/query/annotate).",
            },
            "output": {
                "type": "string",
                "description": "Output file path.",
            },
            "reference": {
                "type": "string",
                "description": "Reference FASTA (required for mpileup_call, consensus, faidx).",
            },
            "query": {
                "type": "string",
                "description": (
                    "bcftools query format string (e.g. '%CHROM\\t%POS\\t%REF\\t%ALT\\n')."
                ),
            },
            "filter_expr": {
                "type": "string",
                "description": "bcftools filter expression (e.g. 'QUAL>30 && DP>10').",
            },
            "extra_args": {
                "type": "string",
                "description": "Extra args passed verbatim to bcftools.",
            },
        },
        "required": ["operation", "input"],
    },
}


# ---------------------------------------------------------------------------
# High-level analysis tools (project.md §7 Salmonella pipeline)
# ---------------------------------------------------------------------------

ANALYZE_PATHOGEN = {
    "name": "bio_analyze_pathogen",
    "description": (
        "Run the full pathogen analysis pipeline (QC, assembly, species "
        "identification via invA/uidA/ipaH three-gene routing, MLST, "
        "serotyping, AMR, virulence, plasmid, DEC pathotype, report). "
        "Works for Salmonella, DEC (E. coli), Shigella, EIEC — species "
        "routing is automatic. Returns a summary of results. "
        "For pipeline guidance and troubleshooting, load skill: "
        "skill_view('hermes_bacmap:run-pipeline')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "Sample ID from samples.tsv."},
            "cores": {"type": "integer", "description": "CPU cores (default 8)."},
        },
        "required": ["sample_id"],
    },
}

GET_RESULT = {
    "name": "bio_get_result",
    "description": (
        "Retrieve analysis summary for a completed sample. Returns species "
        "type (Salmonella/E.coli/Shigella), MLST ST, serotype, ipaH status, "
        "DEC pathotype, AMR/virulence/plasmid gene counts. "
        "For result interpretation, load skill: "
        "skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "Sample ID."},
        },
        "required": ["sample_id"],
    },
}

VERIFY_RESULT = {
    "name": "bio_verify_result",
    "description": (
        "Run deterministic verification on results. Checks species, MLST, "
        "serotype, AMR. Flags critical resistance (CTX-M/NDM/KPC/mcr-1) "
        "for human review. Optionally pass interpretation_text (your own "
        "draft interpretation of the sample) to also run the Layer 3 NLI "
        "Reflector: claims in the text are checked against the sample's "
        "facts, and a high contradiction rate flags NEEDS_HUMAN_REVIEW. "
        "For understanding verification rules, load skill: "
        "skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "Sample ID."},
            "interpretation_text": {
                "type": "string",
                "description": (
                    "Optional LLM interpretation text to reflect against "
                    "sample facts (Layer 3 NLI Reflector)."
                ),
            },
        },
        "required": ["sample_id"],
    },
}

GENERATE_REPORT = {
    "name": "bio_generate_report",
    "description": (
        "Generate HTML report with all results, verifier output, and "
        "evidence chain. Returns file path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {"type": "string", "description": "Sample ID."},
        },
        "required": ["sample_id"],
    },
}

LIST_SAMPLES = {
    "name": "bio_list_samples",
    "description": ("List all samples and their analysis status."),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


GENE_SCAN = {
    "name": "bio_gene_scan",
    "description": (
        "Scan assembled contigs against a gene database (card/vfdb/ecoh/"
        "plasmidfinder/resfinder) to detect AMR, virulence, serotype, or "
        "plasmid genes. Returns JSON with gene list, identity, coverage. "
        "Supports multi-database scanning in one call. "
        "For AMR gene clinical significance (ESBL/carbapenemase/AmpC), "
        "load skill: skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contigs_path": {
                "type": "string",
                "description": "Path to assembled contigs FASTA.",
            },
            "database": {
                "type": "string",
                "description": (
                    "Database name: card, vfdb, ecoh, plasmidfinder,"
                    " resfinder, ncbi, megares, victors, ecoli_vf."
                    " Or comma-separated for multi-db."
                ),
            },
            "min_identity": {
                "type": "number",
                "description": "Minimum % identity (default 80).",
            },
            "min_coverage": {
                "type": "number",
                "description": "Minimum % coverage (default 80).",
            },
        },
        "required": ["contigs_path", "database"],
    },
}


SNP_TREE = {
    "name": "bio_snp_tree",
    "description": (
        "Retrieve the cohort-level SNP phylogenetic tree and pairwise "
        "distance matrix. Returns Newick tree string, sample list, "
        "SNP site count, missing rate, and all pairwise SNP distances. "
        "Use this when the user asks about genetic relatedness, "
        "outbreak clusters, phylogenetic relationships, or SNP distances "
        "between samples. For SNP distance interpretation thresholds "
        "(0-5=outbreak, 6-15=possibly related), load skill: "
        "skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


REVIEW_FLAGS = {
    "name": "bio_review_flags",
    "description": (
        "List Layer 3 NLI Reflector audit events (nli_reflected) from the "
        "GOM: which samples were flagged by the AI interpretation "
        "self-check, with contradiction rate, threshold, and the "
        "contradicted claims. This is the human-review read-back surface — "
        "use it when the user asks which samples need review, what the AI "
        "got wrong, or to trace a flagged sample's audit trail."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max events to return (default 50, newest first).",
            },
        },
        "required": [],
    },
}

CGLST_TRACEBACK = {
    "name": "bio_cgmlst",
    "description": (
        "Trace a single sample's cgMLST allele profile against the local "
        "reference library (EnteroBase HierCC convention, Hamming allele "
        "distance, missing-on-either excluded). Returns the top-N nearest "
        "references, the per-species verdict (outbreak/related/unrelated/"
        "undetermined), the thresholds applied, and any caveats (e.g. "
        "S. sonnei HC5/HC10 unreliable, V. parahaemolyticus UNVERIFIED). "
        "Use this for high-resolution source attribution / 溯源 when the "
        "user asks whether two isolates are part of the same outbreak "
        "cluster, or to find the nearest reference strain for a sample. "
        "Requires cgMLST typing to have been run and ingested "
        "(bio_analyze_pathogen covers this); call bio_analyze_pathogen "
        "first if no profile exists. For cgMLST threshold interpretation, "
        "load skill: skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {
                "type": "string",
                "description": "Sample ID whose cgMLST profile should be traced back.",
            },
        },
        "required": ["sample_id"],
    },
}


SEARCH_SAMPLES = {
    "name": "bio_search_samples",
    "description": (
        "Search across all ingested sample results to find strains by "
        "serotype, MLST ST, AMR gene, organism, or free-text keyword. "
        "Supports multi-field AND queries (e.g., serotype=Typhimurium "
        "AND amr_gene=blaCTX-M-15). Use for traceability: 'find all "
        "strains with same serotype' or 'which strains carry gene X'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-text search (fallback). Searches organism, "
                    "strain_id, serotype, MLST, AMR genes via FTS5."
                ),
            },
            "serotype": {
                "type": "string",
                "description": "Exact serotype match (e.g., Typhimurium, Enteritidis).",
            },
            "mlst_st": {
                "type": "string",
                "description": "MLST ST number (e.g., ST19, 19). Normalized to ST-prefix.",
            },
            "amr_gene": {
                "type": "string",
                "description": "AMR gene name, exact match (e.g., blaCTX-M-15, tet(A)).",
            },
            "organism": {
                "type": "string",
                "description": "Organism name, substring match (e.g., Salmonella, E.coli).",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 50).",
                "default": 50,
            },
        },
    },
}


VALIDATE_TAXONOMY = {
    "name": "bio_validate_taxonomy",
    "description": (
        "Validate genome taxonomy and quality. Two modes: 'simple' "
        "(default, marker-gene based, fast) and 'standard' (CheckM2 "
        "completeness/contamination + GTDB-Tk taxonomy, requires "
        "external databases). Use 'standard' when user asks for "
        "rigorous species verification or contamination check."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {
                "type": "string",
                "description": "Sample ID with assembled contigs.",
            },
            "mode": {
                "type": "string",
                "description": (
                    "Validation mode: 'simple' (marker genes, default)"
                    " or 'standard' (CheckM2 + GTDB-Tk)."
                ),
                "default": "simple",
            },
        },
        "required": ["sample_id"],
    },
}


ANNOTATE = {
    "name": "bio_annotate",
    "description": (
        "Annotate assembled contigs using a Python-native Prokka replacement. "
        "Predicts CDS with pyrodigal (same algorithm as Prodigal), annotates "
        "via blastp against Prokka protein databases (sprot, IS, AMR), and "
        "outputs structured JSON optimized for AI interpretation. Use this "
        "when the user asks to annotate a genome, find genes, or identify "
        "gene functions in assembled contigs. For gene function interpretation, "
        "load skill: skill_view('hermes_bacmap:interpret-results')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contigs_path": {
                "type": "string",
                "description": "Path to assembled contigs FASTA file.",
            },
            "sample_id": {
                "type": "string",
                "description": (
                    "Sample identifier for locus_tag prefix"
                    " (optional, auto-detected from path if omitted)."
                ),
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Output JSON path (optional, default: {sample}/annotation/annotation.json)."
                ),
            },
        },
        "required": ["contigs_path"],
    },
}


DIAGNOSE = {
    "name": "bio_diagnose",
    "description": (
        "Diagnose pipeline failures by parsing Snakemake logs. Returns error "
        "type, root cause, affected rule, and suggested recovery commands. "
        "Use this when analysis fails or the user reports pipeline errors. "
        "Handles OOM, lock conflicts, missing tools, missing databases, "
        "missing input files, disk full, and Snakemake version issues."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "log_path": {
                "type": "string",
                "description": (
                    "Path to Snakemake log file. If omitted, reads the latest log automatically."
                ),
            },
            "stderr_text": {
                "type": "string",
                "description": "Raw stderr text to diagnose (alternative to log_path).",
            },
        },
    },
}


VPA_SEROTYPE = {
    "name": "bio_vpa_serotype",
    "description": (
        "Predict V. parahaemolyticus O/K serotype from assembled contigs. "
        "Uses minimap2 alignment + sourmash k-mer containment + gene-level "
        "verification (Kaptive-style). Returns predicted serotype (e.g. O3:K6), "
        "confidence level, coverage, identity, missing genes, and alerts. "
        "Use this when the user asks about V. parahaemolyticus serotyping."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contigs_path": {
                "type": "string",
                "description": "Path to assembled contigs FASTA.",
            },
            "sample_id": {
                "type": "string",
                "description": "Sample identifier (optional, auto-detected from path).",
            },
        },
        "required": ["contigs_path"],
    },
}


QUERY_METADATA = {
    "name": "bio_query_metadata",
    "description": (
        "Query strain background metadata (patient info, isolation details, "
        "outbreak linkage) from the strain_metadata table. Supports filtering "
        "by province, outbreak_id, sample_source, date range, and custom "
        "extra JSON fields. Use this when the user asks about sample "
        "background, epidemiological info, or outbreak investigations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "strain_id": {
                "type": "string",
                "description": "Specific strain ID to look up (optional).",
            },
            "province": {"type": "string", "description": "Filter by province."},
            "outbreak_id": {"type": "string", "description": "Filter by outbreak ID."},
            "sample_source": {
                "type": "string",
                "description": "Filter by sample source (clinical/food/environment).",
            },
            "isolation_date_from": {
                "type": "string",
                "description": "Date range start (YYYY-MM-DD).",
            },
            "isolation_date_to": {"type": "string", "description": "Date range end (YYYY-MM-DD)."},
        },
    },
}


ADD_METADATA = {
    "name": "bio_add_metadata",
    "description": (
        "Add or update strain background metadata (patient name, age, "
        "isolation date, province, outbreak ID, etc.). Creates a new record "
        "or updates an existing one. Use this when the user wants to record "
        "or modify epidemiological information for a sample."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "strain_id": {
                "type": "string",
                "description": "Strain/sample identifier.",
            },
            "data": {
                "type": "object",
                "description": (
                    "Metadata fields to set. Core fields: patient_name,"
                    " patient_age, patient_gender, isolation_date, province,"
                    " city, sample_source, outbreak_id."
                    " Custom fields stored in extra JSON."
                ),
            },
        },
        "required": ["strain_id", "data"],
    },
}


QUERY_LAB_RESULTS = {
    "name": "bio_query_lab_results",
    "description": (
        "Query wet lab experiment results (AST drug susceptibility, "
        "classical serology, biochemical tests, PCR) for a sample. "
        "Supports filtering by sample, category, test_name, result, "
        "and interpretation. Use this when the user asks about "
        "phenotypic results, antibiotic resistance testing, or "
        "serological findings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sample_id": {
                "type": "string",
                "description": "Strain ID to look up (optional). If omitted, returns all results.",
            },
            "category": {
                "type": "string",
                "description": "Filter by category: ast, serology, biochemical, pcr, pfge.",
            },
            "test_name": {
                "type": "string",
                "description": "Filter by test name (e.g., Cefotaxime, Ciprofloxacin, O-antigen).",
            },
            "result": {
                "type": "string",
                "description": "Filter by result value (e.g., >=8, Positive, Negative).",
            },
            "interpretation": {
                "type": "string",
                "description": (
                    "Filter by interpretation: R (resistant), S (susceptible),"
                    " I (intermediate), positive, negative."
                ),
            },
        },
    },
}


ADD_LAB_RESULT = {
    "name": "bio_add_lab_result",
    "description": (
        "Record a wet lab experiment result (AST, serology, biochemical, PCR) "
        "for a sample. Use this when the user wants to enter phenotypic "
        "data such as disk diffusion results, MIC values, or classical "
        "serotyping results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "strain_id": {"type": "string", "description": "Strain/sample identifier."},
            "category": {
                "type": "string",
                "description": "Test category: ast, serology, biochemical, pcr.",
            },
            "test_name": {
                "type": "string",
                "description": "Test name (e.g. Ampicillin, O antigen, oxidase).",
            },
            "result": {
                "type": "string",
                "description": "Raw result value (e.g. 16, O4, positive).",
            },
            "interpretation": {"type": "string", "description": "S, I, R, positive, negative."},
            "method": {
                "type": "string",
                "description": "Method used (broth_microdilution, disk_diffusion, antiserum).",
            },
            "unit": {"type": "string", "description": "Unit (ug/mL, mm)."},
        },
        "required": ["strain_id", "category", "test_name", "result"],
    },
}

SPECIES_COMPARE = {
    "name": "bio_species_compare",
    "description": (
        "Compare every species-identification method run on one strain "
        "(marker genes, ANI, sourmash, GTDB-Tk, kraken2) and show the "
        "cross-method agreement matrix with the arbitration verdict. "
        "Conflicts within the same evidence layer are flagged "
        "NEEDS_REVIEW for human adjudication."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "strain_id": {
                "type": "string",
                "description": "Strain/sample ID (e.g., SAM-TYP-001).",
            },
        },
        "required": ["strain_id"],
    },
}

DB_SETUP = {
    "name": "bio_db_setup",
    "description": (
        "Deploy species-identification reference databases by tier. "
        "action=list shows tiers with sizes and readiness; action=run starts "
        "the download in the background (non-blocking, log at data/db/setup.log) "
        "— poll progress with bio_db_status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "run"],
                "description": "list = show tiers; run = start background install",
            },
            "tier": {
                "type": "string",
                "description": "One of: instant, mini, sourmash, full, standard (for run)",
            },
        },
        "required": ["action"],
    },
}

DB_STATUS = {
    "name": "bio_db_status",
    "description": (
        "Report installed species-ID databases (from manifests) and the tail "
        "of any running/finished background setup log."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}
