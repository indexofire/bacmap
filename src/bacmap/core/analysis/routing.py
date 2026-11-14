"""工作流路由（ADR-20 配套）：按病原注册表决定**每个样本适用哪些步骤**。

设计（v1.4.24）：物种鉴定之后的种以下步骤必须按 `core/pathogens.yaml` 路由，
不得对不适用物种执行外部工具：

- SISTR 只做**沙门菌**血清型；
- 志贺菌血清型由 gspec `shi_sero` 库承担（v1.10.17 起不再走读段级 ShigaTyper）；
- `eco_dec`（gspec）只做**大肠埃希菌/志贺菌** DEC 致病型；
- 其余种以下判定（`vpa_vf` 毒力标记、`ecoh` O/H、`vpa_ok` O/K、
  `lmo_sero` 血清群等）统一走 `gspec_typing` 通用规则：库清单来自注册表 +
  用户覆盖，结论由 collect_summary 从 typing.json 归一（v1.4.41）。

本模块是纯函数（无 Snakemake 依赖），供 `rules/report.smk` 构造条件依赖，也便于单测。
"""

from __future__ import annotations

from bacmap.core.pathogen_registry import get_workflow_tables, resolve_species
from bacmap.core.tool_selection import ToolSelection


def serotype_engine(species_value: str) -> str:
    """物种值（码/标签/显示名）→ 血清型引擎；未声明 → 空串。"""
    code = resolve_species(species_value)
    if code is None:
        return ""
    return get_workflow_tables().serotype_engines.get(code, "")


def uses_gspec_db(
    species_value: str,
    db: str,
    *,
    selection: ToolSelection | None = None,
    sample: str | None = None,
) -> bool:
    """该物种是否声明了给定 gspec 库（决定对应分型步骤是否适用）。

    ``selection`` 存在时以用户覆盖后的生效库为准；缺省保持 registry 默认
    （向后兼容，单测/旧调用零变化）。
    """
    code = resolve_species(species_value)
    if code is None:
        return False
    if selection is not None:
        return db in selection.effective_gspec_databases(code, sample=sample)
    return db in get_workflow_tables().gspec_screens.get(code, [])


def report_inputs(
    sample: str,
    species_value: str,
    workdir: str,
    *,
    has_qc: bool = True,
    selection: ToolSelection | None = None,
) -> dict[str, str]:
    """样本的 summary 依赖（只含适用步骤；不适用者不进入 DAG）。

    ``has_qc=False`` 用于 assembly 直入样本（无 reads，无 fastp 产物）：
    qc_json 不进 DAG，summary 的 qc 段由脚本侧容错为空。
    """
    base = f"{workdir}/{sample}"
    files: dict[str, str] = {
        "assembly_stats": f"{base}/assembly/assembly_stats.tsv",
        "quast": f"{base}/assembly/quast/transposed_report.tsv",
        "contig_stats": f"{base}/assembly/contig_stats.tsv",
        "species_id": f"{base}/species/species_id.json",
        "mlst": f"{base}/typing/mlst.json",
        # v1.10.19：gspec screen 以 JSON 为主输出（保留 provenance），
        # TSV 布局仅在旧运行目录由读取层回退。
        "vfdb": f"{base}/gspec/vfdb.json",
        "card": f"{base}/gspec/card.json",
        "amrfinderplus": f"{base}/amr/amrfinderplus.tsv",
        "plasmidfinder": f"{base}/gspec/plasmidfinder.json",
        "gspec_typing": f"{base}/gspec/typing.json",
        "annotation": f"{base}/annotation/annotation.json",
    }
    if has_qc:
        files["qc_json"] = f"{base}/qc/{sample}_fastp.json"
    engine = serotype_engine(species_value)
    if engine == "sistr":
        files["sistr"] = f"{base}/typing/sistr.json"
    if uses_gspec_db(species_value, "eco_dec", selection=selection, sample=sample):
        files["pathotype"] = f"{base}/dec/pathotype.json"
    # v1.4.41：vpara_virulence（gspec 通用筛查）与各占位血清型文件不再有专用
    # 产物 —— 毒力标记与 O/K、ecoh 血清型结论都出自 gspec/typing.json，由
    # collect_summary 归一；未声明对应库的物种不产生相应 summary 段。
    if selection is not None:
        code = resolve_species(species_value)
        if code is not None:
            plan = selection.effective_gmlst(code, sample=sample)
            if "tgmlst" in plan.modes:
                files["tgmlst"] = f"{base}/typing/tgmlst.json"
    return files
