"""Snakemake script: collect all analysis results into a summary JSON."""
import json
from pathlib import Path

sample = snakemake.wildcards.sample
summary = {"sample": sample, "steps": {}}


def opt_input(name):
    """可选步骤产物：该物种不适用时，report 的依赖里根本没有这个输入。"""
    try:
        return getattr(snakemake.input, name)
    except AttributeError:
        return None

def read_file(path, default="N/A"):
    p = Path(path)
    if p.exists() and p.stat().st_size > 0:
        return p.read_text().strip()
    return default

def read_json(path, default=None):
    p = Path(path)
    if p.exists() and p.stat().st_size > 0:
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return default
    return default

def parse_tsv(path, default=None):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return default
    lines = p.read_text().strip().split("\n")
    if len(lines) < 2:
        return default
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) >= len(headers):
            rows.append(dict(zip(headers, fields, strict=False)))
    return rows

def parse_gspec_screen(path):
    """v1.10.19：gspec screen JSON 报告 → abricate 形状的行（共享解析层）。"""
    from bacmap.core.utils import parse_gspec_report

    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    return parse_gspec_report(p.read_text())

qc_path = getattr(snakemake.input, "qc_json", None)
qc = read_json(qc_path, {}) if qc_path else {}  # assembly 直入样本无 fastp 产物
summary["steps"]["qc"] = {
    "after_filtering": qc.get("filtering_result", {}),
    "before_filtering": qc.get("summary", {}).get("before_filtering", {}),
}

asm_text = read_file(snakemake.input.assembly_stats, "")
summary["steps"]["assembly"] = asm_text

quast_text = read_file(snakemake.input.quast, "")
if quast_text:
    summary["steps"]["assembly_quast"] = quast_text

species_id = read_json(snakemake.input.species_id, {})
if not isinstance(species_id, dict):
    species_id = {}
summary["steps"]["species"] = species_id

mlst_text = read_file(snakemake.input.mlst, "")
summary["steps"]["mlst"] = mlst_text

tgmlst_path = opt_input("tgmlst")
if tgmlst_path:
    tgmlst_text = read_file(tgmlst_path, "")
    if tgmlst_text:
        summary["steps"]["gmlst_tgmlst"] = tgmlst_text

sistr_path = opt_input("sistr")  # 非沙门菌：不适用（不进入 DAG，不跑 SISTR）
sistr = read_json(sistr_path, []) if sistr_path else []
if isinstance(sistr, list) and sistr:
    sistr = sistr[0]
if not isinstance(sistr, dict):
    sistr = {}
summary["steps"]["serotype"] = {
    "sistr": sistr.get("serovar", "N/A"),
    "serogroup": sistr.get("serogroup", "N/A"),
    "o_antigen": sistr.get("o_antigen", "N/A"),
    "h1": sistr.get("h1", "N/A"),
    "h2": sistr.get("h2", "N/A"),
}
if sistr_path is None:
    summary["steps"]["serotype"]["sistr_status"] = "not_applicable"
    summary["steps"]["serotype"]["sistr_reason"] = "SISTR 仅用于沙门菌血清型预测"

# gspec 分型（registry 驱动；lmo_sero 等带 typing scheme 的库给出表型）
from bacmap.core.analysis.gspec_typing import (  # noqa: E402
    ecoh_serotype_summary as _ecoh_serotype_summary,
)
from bacmap.core.analysis.gspec_typing import (  # noqa: E402
    shigella_serotype_summary as _shigella_serotype_summary,
)
from bacmap.core.analysis.gspec_typing import (  # noqa: E402
    summarize as summarize_gspec_typing,
)
from bacmap.core.analysis.gspec_typing import (  # noqa: E402
    virulence_marks as _virulence_marks,
)

gspec_tp = summarize_gspec_typing(read_json(snakemake.input.gspec_typing, {}))
summary["steps"]["gspec_typing"] = {
    "status": gspec_tp["status"],
    "databases": gspec_tp["databases"],
}
# 血清群（如 L. monocytogenes Doumith serogroup）并入 serotype 段，注明来源 scheme
if gspec_tp["serogroup"]:
    summary["steps"]["serotype"]["serogroup"] = gspec_tp["serogroup"]
    summary["steps"]["serotype"]["serogroup_scheme"] = gspec_tp["serogroup_scheme"]

summary["steps"]["amr"] = {
    "abricate_vfdb": parse_gspec_screen(snakemake.input.vfdb),
    "abricate_card": parse_gspec_screen(snakemake.input.card),
    "amrfinderplus": parse_tsv(snakemake.input.amrfinderplus, []),
}

summary["steps"]["plasmid"] = {
    "plasmidfinder": parse_gspec_screen(snakemake.input.plasmidfinder),
}

dec_serotype = _ecoh_serotype_summary(gspec_tp["databases"].get("ecoh")) or {}
_shigella_gspec = _shigella_serotype_summary(gspec_tp["databases"].get("shi_sero"))
pathotype_path = opt_input("pathotype")
_dec_applicable = (
    pathotype_path is not None
    or dec_serotype != {}
    or _shigella_gspec is not None
)

if _dec_applicable:
    # ecoh O/H 能力状态/表型已由 gspec typing.json 归一（dec_serotype）。
    # DEC 致病型：gspec `eco_dec` 的 typing 结果（v1.4.18，判定外部化）
    from bacmap.core.analysis.dec_pathotype import (
        summarize as summarize_dec_pathotype,
    )

    dec_pt = summarize_dec_pathotype(read_json(pathotype_path, {}) if pathotype_path else {})
    # gside 标记名小写（"ipah"）；大小写不敏感匹配，且容忍 marker 非 dict/非 list 形态。
    _markers = species_id.get("detected_markers", [])
    _marker_genes = {
        (str(m.get("gene", "")) if isinstance(m, dict) else str(m)).lower()
        for m in (_markers if isinstance(_markers, list) else [])
    }
    ipah = "ipaH_positive" if "ipah" in _marker_genes else "ipaH_negative"
    summary["steps"]["dec"] = {
        "ecoh_serotype": dec_serotype.get("serotype", "N/A"),
        "o_type": dec_serotype.get("o_type", "-"),
        "h_type": dec_serotype.get("h_type", "-"),
        "interpretation": dec_serotype.get("interpretation", ""),
        "pathotype": dec_pt["pathotype"],
        "pathotype_scheme": dec_pt["pathotype_scheme"],
        "pathotype_confidence": dec_pt["pathotype_confidence"],
        "pathotype_genes": dec_pt["pathotype_genes"],
        "pathotype_runner_up": dec_pt["pathotype_runner_up"],
        "pathotype_schemes": dec_pt["pathotype_schemes"],
        "ipaH": ipah,
    }
    if pathotype_path is None:
        summary["steps"]["dec"]["pathotype"] = "N/A"
        summary["steps"]["dec"]["pathotype_status"] = "not_applicable"

    # 志贺菌血清型：gspec shi_sero（marker-set 库）判定。
    shigella_serotype = _shigella_gspec or {}
    if not isinstance(shigella_serotype, dict):
        shigella_serotype = {}
    _shi_status = str(shigella_serotype.get("status", "N/A"))
    _shi_genes = shigella_serotype.get("genes")
    summary["steps"]["dec"]["shigella_serotype"] = shigella_serotype.get(
        "serotype", "N/A"
    )
    summary["steps"]["dec"]["shigella_species"] = shigella_serotype.get(
        "species", "N/A"
    )
    summary["steps"]["dec"]["shigella_status"] = _shi_status
    if _shigella_gspec is not None:
        summary["steps"]["dec"]["shigella_method"] = shigella_serotype.get(
            "method", "gspec shi_sero"
        )
        if isinstance(_shi_genes, list):
            summary["steps"]["dec"]["shigella_ipab"] = (
                "ipaB" if "ipaB" in _shi_genes else ""
            )

    ecoh_serotype_val = dec_serotype.get("serotype", "-:-")
    shigella_serotype_val = str(shigella_serotype.get("serotype") or "Undetermined")
    shigella_ran = _shi_status == "ran"
    _shigella_fallback = {"N/A", "Undetermined", "Not Shigella/EIEC"}

    if shigella_ran and shigella_serotype_val not in _shigella_fallback:
        primary_serotype = shigella_serotype_val
        serotype_method = str(
            shigella_serotype.get("method") or "gspec shi_sero"
        )
    elif ecoh_serotype_val != "-:-":
        primary_serotype = ecoh_serotype_val
        serotype_method = "ecoh_serotyper (DEC/EIEC)"
    else:
        primary_serotype = "N/A"
        serotype_method = "N/A"

    summary["steps"]["dec"]["primary_serotype"] = primary_serotype
    summary["steps"]["dec"]["serotype_method"] = serotype_method
    # 统一入口：前端/报告优先读 steps.serotype.value；沙门菌仍保留 sistr 字段。
    summary["steps"]["serotype"]["value"] = primary_serotype
    summary["steps"]["serotype"]["method"] = serotype_method
else:
    # 非 DEC/志贺菌物种：整段不适用（不跑 gspec eco_dec / ecoh / shi_sero）
    summary["steps"]["dec"] = {
        "status": "not_applicable",
        "reason": "DEC 致病型 / 志贺菌血清型仅适用于大肠埃希菌与志贺菌",
    }

# VPA O/K 血清型（gspec `vpa_ok` cluster 库是权威来源；未选库/无表型时如实
# unavailable，不再由占位规则产出文件）。段仅在该样本物种声明了 vpa_ok 或
# 为 VPA 时写出，与旧契约一致。
_vpa_ok = gspec_tp["databases"].get("vpa_ok")
if isinstance(_vpa_ok, dict) and _vpa_ok.get("status") == "ran":
    _phenotypes = _vpa_ok.get("phenotypes") if isinstance(_vpa_ok.get("phenotypes"), dict) else {}
    _o = _phenotypes.get("o_group", {}) if isinstance(_phenotypes.get("o_group"), dict) else {}
    _k = _phenotypes.get("k_group", {}) if isinstance(_phenotypes.get("k_group"), dict) else {}
    _serotype = str(_vpa_ok.get("phenotype") or "")
    if not _serotype:
        _serotype = ":".join(
            part for part in (str(_o.get("phenotype") or ""), str(_k.get("phenotype") or "")) if part
        )
    if _serotype:
        summary["steps"]["vpa_serotype"] = {
            "predicted_serotype": _serotype,
            "o_locus": str(_o.get("phenotype") or "None"),
            "k_locus": str(_k.get("phenotype") or "None"),
            "o_confidence": str(_o.get("confidence") or "Unknown"),
            "k_confidence": str(_k.get("confidence") or "Unknown"),
            "source": "gspec:vpa_ok",
        }
# VPA 毒力标记（tdh/trh/tlh）按基因名扫 gspec 各库（官方 vpa_vf 或用户
# 显式选择的库；v1.4.41 前的私有 vpara_virulence 库同样命中）；
# O/K 血清型的 unavailable 语义按样本物种（registry 解析）判定。
from bacmap.core.pathogen_registry import resolve_species as _resolve_species  # noqa: E402

_sample_code = _resolve_species(
    str(species_id.get("species") or species_id.get("verdict") or "")
)
_vpa_virulence = _virulence_marks(gspec_tp["databases"])
if _vpa_virulence is not None:
    summary["steps"]["vpa_virulence"] = _vpa_virulence
if "vpa_serotype" not in summary["steps"] and _sample_code == "VPA":
    summary["steps"]["vpa_serotype"] = {
        "status": "unavailable",
        "reason": "gspec 尚无副溶血性弧菌血清型数据库",
    }

# v1.10.23 流式首屏：prelim 阶段无注释输入——getattr 容缺，标 pending。
_annotation_path = getattr(snakemake.input, "annotation", "")
annotation = read_json(_annotation_path, {}) if _annotation_path else {}
if not annotation:
    summary["prelim"] = True
if isinstance(annotation, dict) and annotation.get("summary"):
    ann_summary = annotation.get("summary", {})
    top_genes = []
    _features = annotation.get("features", [])
    for feat in (_features if isinstance(_features, list) else [])[:20]:
        ident = feat.get("identity") if isinstance(feat, dict) else None
        if (
            isinstance(feat, dict)
            and feat.get("gene")
            and not feat.get("hypothetical")
            and "hypothetical" not in str(feat.get("product", "")).lower()
            and (
                ident is None
                or (isinstance(ident, (int, float)) and ident >= 80)
            )
        ):
            top_genes.append({
                "gene": feat["gene"],
                "product": feat.get("product", ""),
                "identity": ident,
                "source": feat.get("source", ""),
            })
    summary["steps"]["annotation"] = {
        "status": annotation.get("status", "ok") if annotation else "pending",
        "total_CDS": ann_summary.get("total_CDS", 0),
        "annotated_CDS": ann_summary.get("annotated_CDS", 0),
        "annotation_rate": ann_summary.get("annotation_rate", 0),
        "bakta": ann_summary.get("bakta", {}),
        "eggnog": ann_summary.get("eggnog", {}),
        "top_genes": top_genes,
    }


Path(snakemake.output.summary).parent.mkdir(parents=True, exist_ok=True)
Path(snakemake.output.summary).write_text(
    json.dumps(summary, ensure_ascii=False, indent=2)
)
