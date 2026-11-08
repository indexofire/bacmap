import sys

# DEC + Shigella 分析（project.md §7.3.2-3）
# v1.4.7：ecoh/shigella 血清型判定外移外部工具（用户裁定）；
# v1.4.18：DEC 致病型判定外移 gspec（`eco_dec` 库）——bacmap 不再自判路径型；
# v1.4.24：志贺菌血清型接 **ShigaTyper**（读段级外部工具；未来迁 gspec），
#          且本文件各步骤仅在物种适用时由 report 依赖触发（SISTR 只属沙门菌）。
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


rule shigella_serotype:
    input:
        r1 = r1_path,
        r2 = r2_path
    output:
        result = str(WORKDIR) + "/{sample}/dec/shigella_serotype.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_shigatyper.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/{sample}/dec",
        sample = "{sample}"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.py_script} "
        "--r1 {input.r1} --r2 {input.r2} --sample {params.sample} "
        "--out {output.result} --workdir {params.workdir}"
