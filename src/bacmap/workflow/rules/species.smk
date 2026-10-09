# v1.4.7：物种鉴定外移 gside；species_identify 经薄适配器接入 `gside species`
#（脚本 workflow/scripts/gside_species.py 完成 JSON→species_id 形状转换）。
# species_sourmash/species_ani 保留占位——gside `all` 模式内部已涵盖多法仲裁，
# 待 GTDB-Tk 档落地后随 Snakefile 门控一并清理。

import sys

rule species_identify:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/species/species_id.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/gside_species.py"),
        python = sys.executable,
        mode = config["species_mode"]
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.py_script} "
        "--contigs {input.contigs} --out {output.result} --mode {params.mode}"


rule species_sourmash:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/species/species_sourmash.json"
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"method\":\"sourmash\",\"status\":\"pending_gside\","
        "\"interpretation\":\"externalized to gside (v1.4.7)\"}}' "
        "> {output.result}"


rule species_ani:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/species/species_ani.json"
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"method\":\"ani\",\"status\":\"pending_gside\","
        "\"interpretation\":\"externalized to gside (v1.4.7)\"}}' "
        "> {output.result}"
