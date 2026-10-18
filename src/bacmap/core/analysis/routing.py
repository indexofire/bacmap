"""工作流路由（ADR-20 配套）：按病原注册表决定**每个样本适用哪些步骤**。

设计（v1.4.24）：物种鉴定之后的种以下步骤必须按 `core/pathogens.yaml` 路由，
不得对不适用物种执行外部工具：

- SISTR 只做**沙门菌**血清型；
- ShigaTyper（未来迁 gapit）只做**志贺菌**血清型；
- `ecoh`（gapit）只做**大肠埃希菌** O/H；
- `ecoli_dec`（gapit）只做**大肠埃希菌/志贺菌** DEC 致病型；
- `vpara_virulence`/vpara 血清型只做**副溶血性弧菌**。

本模块是纯函数（无 Snakemake 依赖），供 `rules/report.smk` 构造条件依赖，也便于单测。
"""

from __future__ import annotations

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species


def serotype_engine(species_value: str) -> str:
    """物种值（码/标签/显示名）→ 血清型引擎；未声明 → 空串。"""
    code = resolve_species(species_value)
    if code is None:
        return ""
    return get_workflow_tables().serotype_engines.get(code, "")


def uses_gapit_db(species_value: str, db: str) -> bool:
    """该物种是否声明了给定 gapit 库（决定对应分型步骤是否适用）。"""
    code = resolve_species(species_value)
    if code is None:
        return False
    return db in get_workflow_tables().gapit_screens.get(code, [])


def report_inputs(sample: str, species_value: str, workdir: str) -> dict[str, str]:
    """样本的 summary 依赖（只含适用步骤；不适用者不进入 DAG）。"""
    base = f"{workdir}/{sample}"
    files: dict[str, str] = {
        "qc_json": f"{base}/qc/{sample}_fastp.json",
        "assembly_stats": f"{base}/assembly/assembly_stats.tsv",
        "species_id": f"{base}/species/species_id.json",
        "mlst": f"{base}/typing/mlst.tsv",
        "vfdb": f"{base}/amr/abricate_vfdb.tsv",
        "card": f"{base}/amr/abricate_card.tsv",
        "amrfinderplus": f"{base}/amr/amrfinderplus.tsv",
        "plasmidfinder": f"{base}/plasmid/abricate_plasmidfinder.tsv",
        "gapit_typing": f"{base}/gapit/typing.json",
        "annotation": f"{base}/annotation/annotation.json",
    }
    engine = serotype_engine(species_value)
    if engine == "sistr":
        files["sistr"] = f"{base}/typing/sistr.json"
    if engine == "ecoh":
        files["ectyper"] = f"{base}/dec/ecoh_serotype.json"
    if engine == "shigatyper":
        files["shigella_serotype"] = f"{base}/dec/shigella_serotype.json"
    if uses_gapit_db(species_value, "ecoli_dec"):
        files["pathotype"] = f"{base}/dec/pathotype.json"
    if uses_gapit_db(species_value, "vpara_virulence"):
        files["vpa_serotype"] = f"{base}/vpa/vpa_serotype.json"
        files["vpa_virulence"] = f"{base}/vpara/virulence.json"
    return files
