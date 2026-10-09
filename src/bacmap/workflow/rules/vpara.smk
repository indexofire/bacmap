import sys

# V. parahaemolyticus 相关规则
# v1.4.7：vpara_targets（物种靶点判定）与 vpara_serotype（O/K 血清型）分别外移
# gside / gapit（用户裁定），集成前输出占位；vpara_virulence 保留
# （blastn 外部二进制编排，与 abricate 规则同类，第 5 步随 gapit 复评）。

rule vpara_targets:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/vpara/targets_blastn.tsv",
        verdict = str(WORKDIR) + "/{sample}/vpara/species_verdict.txt"
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "touch {output.result} && "
        "echo pending_gside > {output.verdict}"


rule vpara_virulence:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/vpara/virulence.json"
    params:
        python = sys.executable,
        db = str(PROJECT_ROOT / "data/reference/virulence/vpara_targets_blastdb")
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{params.python} -c \""
        "import json, subprocess; "
        "contigs='{input.contigs}'; "
        "genes={{}}; "
        "for g in ['tdh','trh','tlh']: "
        "  r=subprocess.run(['blastn','-query',contigs,'-db','{params.db}','-outfmt','6 sseqid pident','-evalue','1e-50','-word_size','28'],capture_output=True,text=True,timeout=60); "
        "  hits=[l for l in r.stdout.split('\\n') if g.upper() in l.upper()]; "
        "  genes[g]=len(hits)>0; "
        "json.dump({{k:v for k,v in genes.items()}},open('{output.result}','w')); "
        "\" || echo '{{\"tdh\":false,\"trh\":false,\"tlh\":false}}' > {output.result}"


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
