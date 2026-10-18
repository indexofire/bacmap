import sys

# DEC + Shigella 分析（project.md §7.3.2-3）
# v1.4.7：ecoh/shigella 血清型判定外移 gapit（用户裁定），集成前输出占位；
# v1.4.18：DEC 致病型判定外移 gapit（`ecoli_dec` 库）——bacmap 不再自判路径型。

rule dec_ecoh_serotype:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/dec/ecoh_serotype.json"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"serotype\":\"pending_gapit\",\"o_type\":\"-\",\"h_type\":\"-\","
        "\"o_antigen_hits\":[],\"h_antigen_hits\":[],"
        "\"interpretation\":\"serotyping externalized to gapit (v1.4.7)\"}}' "
        "> {output.result}"


rule dec_pathotype:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/dec/pathotype.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_dec_typing.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/{sample}/dec",
        db = "ecoli_dec"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.py_script} --contigs {input.contigs} "
        "--out {output.result} --workdir {params.workdir} --db {params.db}"


rule shigella_serotype:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/dec/shigella_serotype.json"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"species\":\"N/A\",\"serotype\":\"pending_gapit\",\"confidence\":\"none\","
        "\"detected_genes\":[],"
        "\"interpretation\":\"serotyping externalized to gapit (v1.4.7)\"}}' "
        "> {output.result}"
