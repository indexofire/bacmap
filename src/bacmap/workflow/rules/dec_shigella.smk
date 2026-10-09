import sys

# DEC + Shigella 分析（project.md §7.3.2-3）
# v1.4.7：ecoh/shigella 血清型判定外移 gapit（用户裁定），集成前输出占位；
# dec_pathotype 保留（abricate 外部工具编排 + 规则脚本，第 5 步随 gapit 复评）。

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
        vfdb = str(WORKDIR) + "/{sample}/amr/abricate_vfdb.tsv"
    output:
        result = str(WORKDIR) + "/{sample}/dec/pathotype.tsv"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/call_pathotype.py"),
        python = sys.executable
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.py_script} --vfdb {input.vfdb} --output {output.result}"


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
