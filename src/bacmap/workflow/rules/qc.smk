import sys

import sys

# Step 1: fastp 质控 (project.md §7.1 step 1)

FASTP_Q = config["tools"]["fastp"]["qualified_quality_phred"]
FASTP_LEN = config["tools"]["fastp"]["length_required"]

# With kraken2 prefilter enabled AND its custom library installed (gating in
# Snakefile), fastp consumes the unclassified (scrubbed) reads; otherwise raw.
def _r1_in(wc):
    if _KRAKEN2_ACTIVE:
        return str(WORKDIR) + "/" + wc.sample + "/kraken2/" + wc.sample + "_unc_1.fq"
    return r1_path(wc)


def _r2_in(wc):
    if _KRAKEN2_ACTIVE:
        return str(WORKDIR) + "/" + wc.sample + "/kraken2/" + wc.sample + "_unc_2.fq"
    return r2_path(wc)


rule qc_fastp:
    input:
        r1 = _r1_in,
        r2 = _r2_in
    output:
        r1_clean = temp(str(WORKDIR) + "/{sample}/qc/{sample}_clean_R1.fastq.gz"),
        r2_clean = temp(str(WORKDIR) + "/{sample}/qc/{sample}_clean_R2.fastq.gz"),
        json = str(WORKDIR) + "/{sample}/qc/{sample}_fastp.json",
        html = str(WORKDIR) + "/{sample}/qc/{sample}_fastp.html"
    threads: config["threads"]
    shell:
        "mkdir -p $(dirname {output.json}) && "
        "fastp -i {input.r1} -I {input.r2} "
        "-o {output.r1_clean} -O {output.r2_clean} "
        "--qualified_quality_phred {FASTP_Q} "
        "--length_required {FASTP_LEN} "
        "--detect_adapter_for_pe "
        "--json {output.json} --html {output.html} "
        "--thread {threads}"


rule kraken2_prefilter:
    input:
        r1 = r1_path,
        r2 = r2_path
    output:
        r1_unc = str(WORKDIR) + "/{sample}/kraken2/{sample}_unc_1.fq",
        r2_unc = str(WORKDIR) + "/{sample}/kraken2/{sample}_unc_2.fq",
        report = str(WORKDIR) + "/{sample}/kraken2/kraken2_report.txt",
        bracken = str(WORKDIR) + "/{sample}/kraken2/bracken.tsv",
        result = str(WORKDIR) + "/{sample}/kraken2/kraken2_prefilter.json"
    params:
        pixi = str(__import__("pathlib").Path(sys.executable).resolve().parent),
        db = str(PROJECT_ROOT / "data/db/kraken2_custom"),
        report_py = str(PROJECT_ROOT / "workflows/bacmap/scripts/kraken2_report.py"),
        python = sys.executable,
        species = lambda wc: str(SAMPLES_DF.loc[wc.sample, "species"]),
        outdir = str(WORKDIR) + "/{sample}/kraken2"
    threads: 4
    shell:
        "export PATH={params.pixi}:$PATH && mkdir -p {params.outdir} && "
        "kraken2 --paired --db {params.db} --threads {threads} "
        "--report {output.report} --output {params.outdir}/kraken2_out.txt "
        "--unclassified-out {params.outdir}/{wildcards.sample}_unc_#.fq "
        "{input.r1} {input.r2} && "
        "bracken -d {params.db} -i {output.report} -o {output.bracken} "
        "-k 35 -l S -t {threads} && "
        "{params.python} {params.report_py} --report {output.report} "
        "--bracken {output.bracken} --declared-species '{params.species}' "
        "--output {output.result}"
