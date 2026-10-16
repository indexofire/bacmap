import sys

# V. parahaemolyticus 相关规则
# 物种靶点判定由 gside species 统一承担（ADR-20，见 rules/species.smk），此处不再保留
# `vpara_targets` 占位规则。
# v1.4.7：vpara_serotype（O/K 血清型）外移 gapit，集成前输出占位。
# v1.4.9：vpara_virulence 完成 gapit 换装（gapit 自定义库 vpara_virulence）。

rule vpara_virulence:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/vpara/virulence.json"
    params:
        python = sys.executable,
        script = str(PROJECT_ROOT / "workflows/bacmap/scripts/vpara_virulence.py"),
        db = config["databases"].get("vpara_virulence", "vpara_virulence"),
        datadir = str(PROJECT_ROOT / "refs" / "gapit"),
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} {params.script} "
        "--contigs {input.contigs} --db {params.db} --datadir {params.datadir} "
        "--out {output.result}"


rule vpara_serotype:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/vpa/vpa_serotype.json"
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"predicted_serotype\":\"pending_gapit\",\"o_locus\":\"None\",\"k_locus\":\"None\","
        "\"o_confidence\":\"Unknown\",\"k_confidence\":\"Unknown\","
        "\"interpretation\":\"serotyping externalized to gapit (v1.4.7)\"}}' "
        "> {output.result}"
