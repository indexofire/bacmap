# v1.4.7 用户裁定：注释能力外移外部工具（gapit/gside/gmlst 均暂无注释子命令，
# 待 gapit 提供后接入）。集成前输出占位结果；规则保留输出契约。
rule genome_annotation:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        annotation = str(WORKDIR) + "/{sample}/annotation/annotation.json"
    shell:
        "mkdir -p $(dirname {output.annotation}) && "
        "printf %s "
        "'{{\"status\":\"pending_external_tool\",\"tool\":\"gapit\",\"sample\":\"{{wildcards.sample}}\","
        "\"total_CDS\":0,\"annotated_CDS\":0,\"annotation_rate\":0.0,\"top_genes\":[]}}' "
        "> {output.annotation}"
