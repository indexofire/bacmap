# Step 2: Shovill 组装 (project.md §7.1 step 2)
# Shovill 封装 SPAdes，自动做 read correction + assembly + contig filtering

SHOVILL_MINLEN = config["tools"]["shovill"]["minlen"]
SHOVILL_RAM = config["tools"]["shovill"]["ram"]
SHOVILL_DEPTH = config["tools"]["shovill"]["depth"]

rule assembly_shovill:
    input:
        r1 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R1.fastq.gz",
        r2 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R2.fastq.gz"
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/shovill",
        minlen = SHOVILL_MINLEN,
        ram = SHOVILL_RAM,
        depth = SHOVILL_DEPTH
    shell:
        "mkdir -p $(dirname {output.contigs}) && "
        "shovill --R1 {input.r1} --R2 {input.r2} "
        "--outdir {params.outdir} --force "
        "--minlen {params.minlen} --ram {params.ram} --depth {params.depth} "
        "--cpus {threads} && "
        "cp {params.outdir}/contigs.fa {output.contigs}"

rule assembly_stats:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        stats = str(WORKDIR) + "/{sample}/assembly/assembly_stats.tsv"
    shell:
        "seqkit stats -T {input.contigs} > {output.stats}"
