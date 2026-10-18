import sys

# Step 5-9: MLST + AMR + 毒力 + 质粒 + 血清型 (project.md §7.1 steps 5-9)

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species  # noqa: E402
from bacmap.core.analysis.routing import serotype_engine as _routing_engine  # noqa: E402
from bacmap.core.analysis.routing import uses_gapit_db as _routing_uses_db  # noqa: E402

_TABLES = get_workflow_tables()

ABRICATE_MINID = config["tools"]["abricate"]["minid"]
ABRICATE_MINCOV = config["tools"]["abricate"]["mincov"]
_GMLST_SCHEMES = _TABLES.mlst_schemes
_SEROTYPE_ENGINES = _TABLES.serotype_engines
GMLST_BIN = "gmlst"

_AMRFINDER_ORGANISMS = _TABLES.amrfinder_organisms


def _sample_code(sample):
    """samples.tsv species 值（码/标签/显示名）→ 三字母码。"""
    return resolve_species(SAMPLES_DF.loc[sample, "species"])


def _serotype_engine(sample):
    """样本物种 → 血清型引擎（sistr/ecoh/shigatyper…）；无声明 → ""。"""
    return _routing_engine(SAMPLES_DF.loc[sample, "species"])


def _uses_gapit_db(sample, db):
    """样本物种是否声明了该 gapit 库（决定该分型步骤是否适用）。"""
    return _routing_uses_db(SAMPLES_DF.loc[sample, "species"], db)


def _mlst_scheme(sample):
    return _GMLST_SCHEMES.get(_sample_code(sample) or "", "salmonella_2")


def _amr_org_flag(sample):
    code = _sample_code(sample)
    return f"--organism {_AMRFINDER_ORGANISMS[code]}" if code in _AMRFINDER_ORGANISMS else ""
_AMRFINDER_DB_BASE = Path(PROJECT_ROOT / "data/db/amrfinderplus")
# amrfinder -d 需要指向具体版本目录(amrfinder_update 会建 <base>/<version>/)
_AMRFINDER_DB_VERSIONS = sorted(p for p in _AMRFINDER_DB_BASE.iterdir() if p.is_dir()) if _AMRFINDER_DB_BASE.exists() else []
AMRFINDER_DB = str(_AMRFINDER_DB_VERSIONS[-1]) if _AMRFINDER_DB_VERSIONS else str(_AMRFINDER_DB_BASE)
AMRFINDER_MINCOV = config["tools"]["amrfinderplus"]["min_coverage"]

rule typing_mlst:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/typing/mlst.tsv"
    params:
        scheme = lambda wc: _mlst_scheme(wc.sample)
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "{GMLST_BIN} typing mlst -s {params.scheme} "
        "-o {output.result} {input.contigs} || "
        "echo -e 'File\\tScheme\\tST\\n{wildcards.sample}\\t{params.scheme}\\tN/A' > {output.result}"

rule typing_sistr:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
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

rule amr_abricate_vfdb:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/amr/abricate_vfdb.tsv"
    params:
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gapit screen {input.contigs} --db vfdb --minid {params.minid} --mincov {params.mincov} "
        "> {output.result}"

rule amr_abricate_card:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/amr/abricate_card.tsv"
    params:
        pixi = str(__import__("pathlib").Path(sys.executable).resolve().parent),
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    threads: 2
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gapit screen {input.contigs} --db card --minid {params.minid} --mincov {params.mincov} "
        "> {output.result}"

rule amr_abricate_plasmidfinder:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/plasmid/abricate_plasmidfinder.tsv"
    params:
        minid = ABRICATE_MINID,
        mincov = ABRICATE_MINCOV
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "gapit screen {input.contigs} --db plasmidfinder --minid {params.minid} --mincov {params.mincov} "
        "> {output.result}"

rule amr_amrfinderplus:
    input:
        contigs = str(WORKDIR) + "/{sample}/assembly/contigs.fasta"
    output:
        result = str(WORKDIR) + "/{sample}/amr/amrfinderplus.tsv"
    params:
        db = AMRFINDER_DB,
        mincov = AMRFINDER_MINCOV,
        org_flag = lambda wc: _amr_org_flag(wc.sample)
    threads: 4
    shell:
        "mkdir -p $(dirname {output.result}) && "
        "amrfinder -n {input.contigs} -d {params.db} {params.org_flag} "
        "--coverage_min {params.mincov} --threads {threads} "
        "-o {output.result} || touch {output.result}"
