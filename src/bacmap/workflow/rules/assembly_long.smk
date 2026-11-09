# Step 2L: 长读/混合组装（PLAN #4，0.1.5）
#
# 三种路径，按 samples.tsv 列自动路由：
#   - longread 列有值、无 R1/R2 → flye（长读单独组装）
#   - R1/R2 + longread 都有值  → unicycler（混合组装：短读骨架 + 长读补洞）
#   - 用户显式指定 trycycler    → trycycler（多组装器一致性合并，高级路径）
#
# samples.tsv 新增列：
#   longread  = 长读 FASTQ 路径（.fastq.gz / .fastq / .fq.gz）
#   platform  = 可选（ont | pacbio_hifi），缺省由 core/fastq_probe 自动探测
#
# v1.4.42 与 shovill 路径的衔接：flye/unicycler 产物落位
# assembly/flye/contigs.fa 或 assembly/unicycler/contigs.fa，
# 经 contigs_finalize 统一为 assembly/contigs.fasta（下游无差别消费）。

FLYE_MINLEN = config.get("tools", {}).get("flye", {}).get("minlen", 1000)
# genome_size 可选：flye 2.9+ 自动估计；仅在用户显式配置时传入
FLYE_GENOMESIZE = config.get("tools", {}).get("flye", {}).get("genome_size", "")
UNICYCLER_MODE = config.get("tools", {}).get("unicycler", {}).get("mode", "normal")

# 样本分类（在 Snakefile 顶部由 SAMPLES_DF 定义）
# LONGREAD_SAMPLES: 有 longread 列且非空
# HYBRID_SAMPLES: 同时有 R1/R2 和 longread


def _longread_path(wc):
    return str(PROJECT_ROOT / SAMPLES_DF.loc[wc.sample, "longread"])


def _detect_platform(sample):
    """探测或读取样本的测序平台（ont | pacbio_hifi）。"""
    declared = _col(sample, "platform").strip().lower()
    if declared in ("ont", "nanopore"):
        return "ont"
    if declared in ("pacbio", "pacbio_hifi", "hifi"):
        return "pacbio_hifi"
    # 自动探测（读长启发式）
    from bacmap.core.fastq_probe import classify, probe_file

    lr = SAMPLES_DF.loc[sample, "longread"]
    path = Path(PROJECT_ROOT / lr) if not Path(lr).is_absolute() else Path(lr)
    try:
        result = classify(probe_file(path, sample_reads=500))
        if result == "nanopore":
            return "ont"
        if result == "pacbio_hifi":
            return "pacbio_hifi"
    except (OSError, ValueError):
        pass
    return "ont"  # 缺省按 ONT 处理（更常见的长读场景）


rule assembly_flye:
    """长读单独组装（ONT R10.4+ SUP → --nano-hq；旧 R9.4 → --nano-raw；
    PacBio HiFi → --pacbio-hifi）。"""
    input:
        reads = lambda wc: _longread_path(wc)
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/flye/contigs.fa"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/flye",
        platform_flag = lambda wc: _flye_platform_flag(wc.sample),
        minlen = FLYE_MINLEN,
        genomesize = FLYE_GENOMESIZE,
    shell:
        "mkdir -p {params.outdir} && "
        "flye {params.platform_flag} {input.reads} "
        "--out-dir {params.outdir} --threads {threads} "
        "--min-overlap {params.minlen}"
        + (" --genome-size {params.genomesize}" if params.genomesize else "")
        + " && "
        "cp {params.outdir}/assembly.fasta {output.contigs}"


def _flye_platform_flag(sample: str) -> str:
    """按平台/配置返回 flye 读类型标志。

    - ont：默认 ``--nano-hq``（R10.4.1 SUP，Q20+）；旧 R9.4 可配 ``--nano-raw``
    - pacbio_hifi：``--pacbio-hifi``
    """
    platform = _detect_platform(sample)
    if platform == "pacbio_hifi":
        return "--pacbio-hifi"
    # ONT：读配置的 quality mode（默认 hq = R10.4+ SUP）
    ont_mode = config.get("tools", {}).get("flye", {}).get("ont_mode", "hq")
    return f"--nano-{ont_mode}"


rule assembly_unicycler:
    """混合组装：短读（SPAdes 骨架）+ 长读（补洞/桥接），输出完整基因组。"""
    input:
        r1 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R1.fastq.gz",
        r2 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R2.fastq.gz",
        long = lambda wc: _longread_path(wc)
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/unicycler/contigs.fa"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/unicycler",
        mode = UNICYCLER_MODE,
    shell:
        "mkdir -p {params.outdir} && "
        "unicycler -1 {input.r1} -2 {input.r2} -l {input.long} "
        "-o {params.outdir} -t {threads} --mode {params.mode} && "
        "cp {params.outdir}/assembly.fasta {output.contigs}"


rule assembly_trycycler:
    """多组装器一致性合并（高级路径）：合并 flye + shovill + unicycler 的组装结果。

    需要至少两个组装器的 contigs 作为输入。用户在 samples.tsv 的 platform 列
    显式写 "trycycler" 触发此路径。
    """
    input:
        contigs_list = lambda wc: _trycycler_inputs(wc)
    output:
        contigs = str(WORKDIR) + "/{sample}/assembly/trycycler/contigs.fa"
    threads: config["threads"]
    params:
        outdir = str(WORKDIR) + "/{sample}/assembly/trycycler",
    shell:
        "mkdir -p {params.outdir}/clusters && "
        "trycycler cluster "
        + " ".join("--assemblies {0}".format(a) for a in {input.contigs_list}) + " "
        "--out_dir {params.outdir}/clusters --threads {threads} && "
        "trycycler consensus --clusters {params.outdir}/clusters "
        "--out_dir {params.outdir} --threads {threads} && "
        "cp {params.outdir}/consensus.fasta {output.contigs}"


def _trycycler_inputs(wc):
    """收集 trycycler 的输入组装结果（至少两个组装器的 contigs）。"""
    paths = []
    for assembler_dir in ("flye", "shovill", "unicycler"):
        p = Path(WORKDIR) / wc.sample / "assembly" / assembler_dir / "contigs.fa"
        if p.is_file():
            paths.append(str(p))
    if len(paths) < 2:
        # Snakemake DAG 解析时可能文件尚未生成，返回期望路径
        paths = [
            str(WORKDIR / wc.sample / "assembly" / d / "contigs.fa")
            for d in ("flye", "shovill")
        ]
    return paths
