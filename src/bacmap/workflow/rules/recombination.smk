# 重组检测（Gubbins，ADR-20：外部工具，bacmap 只编排 + 适配）。
# 仅对 `pathogens.yaml` 中 plan.recombination=true 的 cohort 组生成目标
# （由 run_analysis.py 依 registry 派生），工具缺失时脚本写 status=skipped。

import sys

from bacmap.core.pathogen_registry import get_workflow_tables  # noqa: E402

_RECOMB_GROUPS = set(get_workflow_tables().recombination_groups)


rule recombination_detect:
    input:
        alignment = str(WORKDIR) + "/snp/{group}/core_snps.fasta"
    output:
        result = str(WORKDIR) + "/snp/{group}/recombination.json"
    params:
        py_script = str(PROJECT_ROOT / "workflows/bacmap/scripts/run_recombination.py"),
        python = sys.executable,
        workdir = str(WORKDIR) + "/snp/{group}/gubbins",
        seed = config["iqtree_seed"]
    threads: 4
    shell:
        "mkdir -p {params.workdir} && "
        "{params.python} {params.py_script} --alignment {input.alignment} "
        "--out {output.result} --workdir {params.workdir} --threads {threads} "
        "--seed {params.seed}"
