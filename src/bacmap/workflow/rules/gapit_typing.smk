# gapit 分型编排（ADR-20：外部工具；bacmap 只编排 + 适配）。
# 库清单 = registry 默认 `gapit_screens` + 用户 tool_selection.yaml 的 gapit 段；
# 运行期再由 gside verdict 选物种码过滤（低置信度/Unknown 不路由）。
# gene 库走 screen + typing；cluster 库走 screen --format json（typing 已集成）。
# 无 scheme 的库如实记 no_scheme（不猜测）。
# eco_dec 由 dec_pathotype 规则专门处理；vpara_virulence 由 vpara 规则处理。

import sys

from bacmap.core.pathogen_registry import resolve_species  # noqa: E402


def _sample_databases(sample):
    """samples.tsv 物种 → 用户覆盖后的库列表（gside 运行时会再按 verdict 过滤）。"""
    code = resolve_species(SAMPLES_DF.loc[sample, "species"])
    return ",".join(TOOL_SELECTION.effective_gapit_databases(code, sample=sample))


rule gapit_typing:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta",
        species = str(WORKDIR) + "/{sample}/species/species_id.json",
    output:
        result = str(WORKDIR) + "/{sample}/gapit/typing.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_gapit_typing.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/{sample}/gapit",
        databases = lambda wc: _sample_databases(wc.sample),
        selection = str(TOOL_SELECTION_PATH),
        sample = "{sample}",
    threads: 4
    shell:
        "mkdir -p {params.workdir} && "
        "{params.python} {params.py_script} --contigs {input.contigs} "
        "--species {input.species} --sample {params.sample} "
        "--selection '{params.selection}' "
        "--out {output.result} --workdir {params.workdir} "
        "--databases '{params.databases}' --threads {threads}"
