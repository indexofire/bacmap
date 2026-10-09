# 汇总报告：聚合所有步骤结果为 JSON

rule report_summary:
    input:
        qc_json = str(WORKDIR) + "/{sample}/qc/{sample}_fastp.json",
        assembly_stats = str(WORKDIR) + "/{sample}/assembly/assembly_stats.tsv",
        species_id = str(WORKDIR) + "/{sample}/species/species_id.json",
        mlst = str(WORKDIR) + "/{sample}/typing/mlst.tsv",
        sistr = str(WORKDIR) + "/{sample}/typing/sistr.json",
        vfdb = str(WORKDIR) + "/{sample}/amr/abricate_vfdb.tsv",
        card = str(WORKDIR) + "/{sample}/amr/abricate_card.tsv",
        amrfinderplus = str(WORKDIR) + "/{sample}/amr/amrfinderplus.tsv",
        plasmidfinder = str(WORKDIR) + "/{sample}/plasmid/abricate_plasmidfinder.tsv",
        ectyper = str(WORKDIR) + "/{sample}/dec/ecoh_serotype.json",
        pathotype = str(WORKDIR) + "/{sample}/dec/pathotype.tsv",
        shigella_serotype = str(WORKDIR) + "/{sample}/dec/shigella_serotype.json",
        vpa_serotype = str(WORKDIR) + "/{sample}/vpa/vpa_serotype.json",
        vpa_virulence = str(WORKDIR) + "/{sample}/vpara/virulence.json",
        annotation = str(WORKDIR) + "/{sample}/annotation/annotation.json",
    output:
        summary = str(WORKDIR) + "/{sample}/report/{sample}_summary.json"
    script:
        "../scripts/collect_summary.py"
