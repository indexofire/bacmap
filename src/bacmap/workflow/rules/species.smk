# 物种鉴定：整体由 gside 承担（ADR-20）。
# `species_identify` 经薄适配器（workflow/scripts/gside_species.py）调用
# `gside species`，由 config `species_mode` 选择鉴定档位
# （simple→marker / panel / skani_gtdb→panel / mash_refseq / sourmash / all / standard→all）。
# gside `all` 模式内部已完成多法仲裁并自动纳入 GTDB-Tk 档（就绪后），
# 故此处不再保留 species_ani / species_sourmash 等分档占位规则。

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
