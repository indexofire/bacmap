# gapit 分型编排（ADR-20：外部工具；bacmap 只编排 + 适配）。
# 库清单由 registry 的 `gapit_screens` 派生（samples.tsv species → 码 → 库），
# 逐库 screen + typing；无 scheme 的库如实记 no_scheme（不猜测）。
# ecoli_dec 由 dec_pathotype 规则专门处理（DEC 致病型契约），此处排除。

import sys

from bacmap.core.pathogen_registry import gapit_screens_for  # noqa: E402


def _sample_databases(sample):
    return ",".join(gapit_screens_for(SAMPLES_DF.loc[sample, "species"]))


rule gapit_typing:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/gapit/typing.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_gapit_typing.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/{sample}/gapit",
        databases = lambda wc: _sample_databases(wc.sample)
    threads: 4
    shell:
        "mkdir -p {params.workdir} && "
        "{params.python} {params.py_script} --contigs {input.contigs} "
        "--out {output.result} --workdir {params.workdir} "
        "--databases '{params.databases}'"
