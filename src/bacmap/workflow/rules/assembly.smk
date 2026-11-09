# Step 2: 组装 (project.md §7.1 step 2)
# v1.4.33 双入口：reads 样本 fastp→shovill 组装；assembly 直入样本（已组装
# FASTA）经 contigs_finalize 直接汇入同一 contigs 通道，下游规则无差别消费。

SHOVILL_MINLEN = config["tools"]["shovill"]["minlen"]
SHOVILL_RAM = config["tools"]["shovill"]["ram"]
SHOVILL_DEPTH = config["tools"]["shovill"]["depth"]


def _contigs_src(wc):
    """contigs 的上游：按输入形态路由到对应组装器。

    - assembly 直入样本 → 用户 FASTA
    - 纯长读（longread 列，无 R1/R2）→ flye（ONT/PacBio 平台探测）
    - 混合（R1/R2 + longread）→ unicycler
    - 纯短读（R1/R2，无 longread）→ shovill
    """
    if wc.sample in FASTA_SAMPLES:
        return assembly_path(wc)
    if wc.sample in LONG_ONLY_SAMPLES:
        return str(WORKDIR) + "/" + wc.sample + "/assembly/flye/contigs.fa"
    if wc.sample in HYBRID_SAMPLES:
        return str(WORKDIR) + "/" + wc.sample + "/assembly/unicycler/contigs.fa"
    return str(WORKDIR) + "/" + wc.sample + "/assembly/shovill/contigs.fa"


rule assembly_shovill:
    input:
        r1 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R1.fastq.gz",
        r2 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R2.fastq.gz"
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/shovill/contigs.fa"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/shovill",
        minlen = SHOVILL_MINLEN,
        ram = SHOVILL_RAM,
        depth = SHOVILL_DEPTH
    shell:
        "mkdir -p {params.outdir} && "
        "shovill --R1 {input.r1} --R2 {input.r2} "
        "--outdir {params.outdir} --force "
        "--minlen {params.minlen} --ram {params.ram} --depth {params.depth} "
        "--cpus {threads}"


rule contigs_finalize:
    """统一 contigs 通道：shovill 产物或提供的 FASTA 落位 assembly/contigs.fasta。"""
    input:
        src = _contigs_src
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    shell:
        "mkdir -p $(dirname {output.contigs}) && cp {input.src} {output.contigs}"


rule assembly_stats:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        stats = str(WORKDIR) + "/{sample}/assembly/assembly_stats.tsv"
    shell:
        "seqkit stats -T {input.contigs} > {output.stats}"
