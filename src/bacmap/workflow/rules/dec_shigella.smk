import sys

# DEC + Shigella 分析（project.md §7.3.2-3）
# v1.4.7：ecoh/shigella 血清型判定外移外部工具（用户裁定）；
# v1.4.18：DEC 致病型判定外移 gspec（`eco_dec` 库）——bacmap 不再自判路径型；
# v1.4.24：志贺菌血清型曾接 ShigaTyper（读段级）；
# v1.10.17：已迁移到 gspec `shi_sero`（rules/gspec_typing.smk），本文件只保留
#          gspec `eco_dec` 的 DEC 致病型步骤。
# v1.4.41：ecoh O/H 占位规则删除——ECO 的 O/H 能力状态/表型统一出自
#          gspec typing.json（collect_summary 归一），不再逐菌占位文件。

rule dec_pathotype:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/dec/pathotype.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_dec_typing.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/{sample}/dec",
        db = "eco_dec"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.py_script} --contigs {input.contigs} "
        "--out {output.result} --workdir {params.workdir} --db {params.db}"
