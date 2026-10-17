import sys

# SNP calling + joint variant calling + phylogenetic tree
# Per-species-group: Salmonella / E.coli+Shigella / V.parahaemolyticus
# Each group uses its own reference genome and produces independent tree

import os as _os
from bacmap.core.pathogen_registry import get_workflow_tables  # noqa: E402

_PIXI = str(__import__("pathlib").Path(sys.executable).resolve().parent)
_WD = str(WORKDIR)

# ──────────────────────────────────────────────────────────────
# Species → reference genome mapping (E.coli + Shigella share K-12
# MG1655 — same species taxonomically; groups come from pathogens.yaml)
# ──────────────────────────────────────────────────────────────
_SPECIES_GROUPS = get_workflow_tables().snp_groups

# Derive per-group sample lists (≥2 samples required for joint calling)
_GROUP_SAMPLES = {}
for _grp, _info in _SPECIES_GROUPS.items():
    _samps = [s for s in SAMPLES if SAMPLES_DF.loc[s, "species"] in _info["species"]]
    if len(_samps) >= 2:
        _GROUP_SAMPLES[_grp] = _samps

_ACTIVE_GROUPS = list(_GROUP_SAMPLES.keys())

# Reverse: sample_id → group (for snp_calling reference lookup)
_SAMPLE_GROUP = {}
for _grp, _samps in _GROUP_SAMPLES.items():
    for _s in _samps:
        _SAMPLE_GROUP[_s] = _grp


# ──────────────────────────────────────────────────────────────
# Per-sample BAM: map QC'd reads to species-specific reference
# ──────────────────────────────────────────────────────────────
rule snp_calling:
    input:
        r1 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R1.fastq.gz",
        r2 = str(WORKDIR) + "/{sample}/qc/{sample}_clean_R2.fastq.gz"
    output:
        bam = str(WORKDIR) + "/{sample}/snp/snps.bam"
    params:
        outdir = str(WORKDIR) + "/{sample}/snp",
        ref = lambda wc: _SPECIES_GROUPS[_SAMPLE_GROUP[wc.sample]]["ref"],
        pixi = _PIXI
    threads: 8
    shell:
        "mkdir -p {params.outdir} && "
        "set -o pipefail && "
        "export PATH={params.pixi}:$PATH && "
        "bwa mem -t {threads} -Y -M {params.ref} {input.r1} {input.r2} | "
        "samtools sort -@ 4 -o {output.bam} && "
        "samtools index {output.bam}"


# ──────────────────────────────────────────────────────────────
# Per-group joint variant calling (bcftools mpileup + call)
# ──────────────────────────────────────────────────────────────
rule joint_variant_calling:
    input:
        bams = lambda wc: expand(
            _WD + "/{sample}/snp/snps.bam",
            sample=_GROUP_SAMPLES.get(wc.group, [])
        )
    output:
        vcfgz = _WD + "/snp/{group}/joint.vcf.gz"
    params:
        ref = lambda wc: _SPECIES_GROUPS[wc.group]["ref"],
        samples = lambda wc: _GROUP_SAMPLES.get(wc.group, []),
        group = lambda wc: wc.group
    threads: 8
    run:
        import subprocess
        grp = params.group
        out_dir = _WD + "/snp/" + grp
        _os.makedirs(out_dir, exist_ok=True)
        bam_list = " ".join(_WD + "/" + s + "/snp/snps.bam" for s in params.samples)
        rename_tsv = out_dir + "/joint.vcf.gz.rename.tsv"
        with open(rename_tsv, "w") as fh:
            for s in params.samples:
                fh.write(_WD + "/" + s + "/snp/snps.bam\t" + s + "\n")
        vcfgz = _WD + "/snp/" + grp + "/joint.vcf.gz"
        cmd = (
            "set -o pipefail && "
            "export PATH=" + _PIXI + ":$PATH && "
            "bcftools mpileup -f " + params.ref + " -q 20 -Q 20 --max-depth 200 "
            + bam_list + " | "
            "bcftools call -mv --ploidy 1 | "
            "bcftools reheader -s " + rename_tsv + " | "
            "bcftools view -Oz -o " + vcfgz + " && "
            "bcftools index " + vcfgz
        )
        subprocess.run(cmd, shell=True, check=True, executable="/bin/bash")


# ──────────────────────────────────────────────────────────────
# Per-group SNP matrix → FASTA alignment
# ──────────────────────────────────────────────────────────────
rule snp_matrix:
    input:
        vcfgz = str(WORKDIR) + "/snp/{group}/joint.vcf.gz"
    output:
        fasta = str(WORKDIR) + "/snp/{group}/core_snps.fasta"
    params:
        script = str(PROJECT_ROOT / "workflows/bacmap/scripts/generate_snp_matrix.py"),
        python = sys.executable
    shell:
        "mkdir -p $(dirname {output.fasta}) && "
        "{params.python} {params.script} {input.vcfgz} {output.fasta}"


# ──────────────────────────────────────────────────────────────
# Per-group phylogenetic tree (IQ-TREE GTR+UFBoot)
# ──────────────────────────────────────────────────────────────
rule phylo_tree:
    input:
        fasta = str(WORKDIR) + "/snp/{group}/core_snps.fasta"
    output:
        tree = str(WORKDIR) + "/snp/{group}/core.treefile",
        report = str(WORKDIR) + "/snp/{group}/core.iqtree"
    params:
        group_outdir = str(WORKDIR) + "/snp/{group}",
        pixi = _PIXI,
        prefix = "core_{group}",
        boot_flags = lambda wc: "-bb 1000 -alrt 1000" if len(_GROUP_SAMPLES.get(wc.group, [])) >= 4 else ""
    shell:
        "export PATH={params.pixi}:$PATH && "
        "cd {params.group_outdir} && "
        "iqtree -s core_snps.fasta -m GTR -seed {config[iqtree_seed]} {params.boot_flags} "
        "-nt AUTO -pre {params.prefix} && "
        "cp {params.prefix}.treefile {output.tree} && "
        "cp {params.prefix}.iqtree {output.report}"


# ──────────────────────────────────────────────────────────────
# Per-group SNP summary JSON
# ──────────────────────────────────────────────────────────────
rule snp_summary:
    input:
        tree = str(WORKDIR) + "/snp/{group}/core.treefile",
        fasta = str(WORKDIR) + "/snp/{group}/core_snps.fasta"
    output:
        summary = str(WORKDIR) + "/snp/{group}/snp_summary.json"
    params:
        script = str(PROJECT_ROOT / "workflows/bacmap/scripts/generate_snp_summary.py"),
        python = sys.executable,
        group = "{group}",
        organism = lambda wc: _SPECIES_GROUPS[wc.group]["organism"]
    shell:
        "{params.python} {params.script} {input.tree} {input.fasta} {output.summary} "
        "--group {params.group} --organism \"{params.organism}\""
