import os
import sys
from pathlib import Path

# Step 5-9: MLST + AMR + 毒力 + 质粒 + 血清型 (project.md §7.1 steps 5-9)

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species  # noqa: E402
from bacmap.core.analysis.routing import serotype_engine as _routing_engine  # noqa: E402
from bacmap.core.analysis.routing import uses_gspec_db as _routing_uses_db  # noqa: E402

_TABLES = get_workflow_tables()

ABRICATE_MINID = config["tools"]["abricate"]["minid"]
ABRICATE_MINCOV = config["tools"]["abricate"]["mincov"]
GMLST_BIN = "gmlst"

_AMRFINDER_ORGANISMS = _TABLES.amrfinder_organisms


def _sample_code(sample):
    """samples.tsv species 值（码/标签/显示名）→ 三字母码。"""
    return resolve_species(SAMPLES_DF.loc[sample, "species"])


def _serotype_engine(sample):
    """样本物种 → 血清型引擎（sistr/ecoh…）；志贺菌走 gspec shi_sero；无声明 → ""。"""
    return _routing_engine(SAMPLES_DF.loc[sample, "species"])


def _uses_gspec_db(sample, db):
    """样本物种是否声明了该 gspec 库（决定该分型步骤是否适用）。"""
    return _routing_uses_db(SAMPLES_DF.loc[sample, "species"], db)


def _mlst_scheme(sample):
    """用户覆盖后的 gmlst mlst 方案；未选 mlst → 空串（写 none/N/A，不猜方案）。"""
    code = _sample_code(sample)
    plan = TOOL_SELECTION.effective_gmlst(code, sample=sample)
    if "mlst" not in plan.modes:
        return ""
    return plan.schemes.get("mlst", "")


def _tgmlst_enabled(sample):
    plan = TOOL_SELECTION.effective_gmlst(_sample_code(sample), sample=sample)
    return "1" if "tgmlst" in plan.modes else "0"


def _amr_org_flag(sample):
    code = _sample_code(sample)
    return f"--organism {_AMRFINDER_ORGANISMS[code]}" if code in _AMRFINDER_ORGANISMS else ""


# AMRFinderPlus database: base directory may contain version subdirs created by
# `amrfinder_update`; pick the latest. Override with BACMAP_AMRFINDER_DB.
_AMRFINDER_DB_BASE = Path(
    os.environ.get("BACMAP_AMRFINDER_DB", str(PROJECT_ROOT / "data/db/amrfinderplus"))
)
_AMRFINDER_DB_VERSIONS = (
    sorted(p for p in _AMRFINDER_DB_BASE.iterdir() if p.is_dir())
    if _AMRFINDER_DB_BASE.exists()
    else []
)
AMRFINDER_DB = (
    str(_AMRFINDER_DB_VERSIONS[-1]) if _AMRFINDER_DB_VERSIONS else str(_AMRFINDER_DB_BASE)
)
AMRFINDER_MINCOV = config["tools"]["amrfinderplus"]["min_coverage"]


rule typing_mlst:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/typing/mlst.tsv"
    params:
        scheme = lambda wc: _mlst_scheme(wc.sample),
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "if [ -n \"{params.scheme}\" ]; then "
        "{GMLST_BIN} typing mlst -s {params.scheme} "
        "-o {output.result} {input.contigs} || "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\t{params.scheme}\\tN/A' > {output.result}; "
        "else "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\tnone\\tN/A' > {output.result}; "
        "fi"

rule typing_tgmlst:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/typing/tgmlst.tsv"
    params:
        enabled = lambda wc: _tgmlst_enabled(wc.sample)
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "if [ '{params.enabled}' = '1' ]; then "
        "{GMLST_BIN} typing tgmlst --format tsv -t {threads} "
        "-o {output.result} {input.contigs} || "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\ttgmlst\\tN/A' > {output.result}; "
        "else "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\ttgmlst\\tN/A' > {output.result}; "
        "fi"

rule typing_sistr:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        json = str(WORKDIR) + "/{sample}/typing/sistr.json",
        cgmlst = str(WORKDIR) + "/{sample}/typing/sistr_cgmlst.csv"
    threads: config["tools"]["sistr"]["threads"]
    params:
        prefix = str(WORKDIR) + "/{sample}/typing/{sample}_sistr"
    shell:
        "mkdir -p $(dirname {output.json}) && "
        "sistr -i {input.contigs} {wildcards.sample} "
        "-f json -o {params.prefix}.json -MM --more-results "
        "--run-mash -p {output.cgmlst} -t {threads} -T $(dirname {output.json}) && "
        "mv {params.prefix}.json {output.json} || "
        "( echo '{{\"serovar\":\"N/A\",\"serogroup\":\"N/A\",\"o_antigen\":\"N/A\",\"h1\":\"N/A\",\"h2\":\"N/A\"}}' > {output.json} && "
        "touch {output.cgmlst} )"

rule gspec_screen_vfdb:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/gspec/vfdb.json"
    params:
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gspec screen {input.contigs} --db vfdb --minid {params.minid} --mincov {params.mincov} "
        "-f json -o {output.result}"

rule gspec_screen_card:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/gspec/card.json"
    params:
        pixi = str(__import__("pathlib").Path(sys.executable).resolve().parent),
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    threads: 2
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gspec screen {input.contigs} --db card --minid {params.minid} --mincov {params.mincov} "
        "-f json -o {output.result}"

rule gspec_screen_plasmidfinder:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/gspec/plasmidfinder.json"
    params:
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gspec screen {input.contigs} --db plasmidfinder --minid {params.minid} --mincov {params.mincov} "
        "-f json -o {output.result}"

rule amr_amrfinderplus:
    """NCBI AMRFinderPlus: AMR genes + point mutations (curated per-family cutoffs).

    gspec also ships the AMRFinderPlus Reference Gene Catalog as `ncbi`, but that
    is presence-only (no point mutations) and uses more permissive 80/80 defaults;
    the dedicated binary is kept for mutation-aware AMR calls.
    """
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/{sample}.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/amr/amrfinderplus.tsv"
    params:
        db = AMRFINDER_DB,
        mincov = AMRFINDER_MINCOV,
        org_flag = lambda wc: _amr_org_flag(wc.sample),
    threads: 4
    shell:
        "set -euo pipefail; "
        "if [ ! -e {params.db} ]; then "
        "echo \"AMRFinderPlus database not found: {params.db}\" >&2; "
        "echo \"Run amrfinder_update --database {params.db} or set BACMAP_AMRFINDER_DB\" >&2; "
        "exit 2; fi; "
        "mkdir -p $(dirname {output.result}) && "
        "amrfinder -n {input.contigs} -d {params.db} {params.org_flag} "
        "--coverage_min {params.mincov} --threads {threads} "
        "-o {output.result}"
