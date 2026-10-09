# v1.4.7：分类学校验外移 gside，集成前输出占位结果。
rule taxonomy_validation:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/taxonomy/validation.json"
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "printf %s "
        "'{{\"status\":\"pending_gside\","
        "\"interpretation\":\"taxonomy validation externalized to gside (v1.4.7)\"}}' "
        "> {output.result}"
