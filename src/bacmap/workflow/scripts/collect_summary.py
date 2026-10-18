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
            rows.append(dict(zip(headers, fields)))
    return rows

qc = read_json(snakemake.input.qc_json, {})
summary["steps"]["qc"] = {
    "after_filtering": qc.get("filtering_result", {}),
    "before_filtering": qc.get("summary", {}).get("before_filtering", {}),
}

asm_text = read_file(snakemake.input.assembly_stats, "")
summary["steps"]["assembly"] = asm_text

species_id = read_json(snakemake.input.species_id, {})
if not isinstance(species_id, dict):
    species_id = {}
summary["steps"]["species"] = species_id

mlst_text = read_file(snakemake.input.mlst, "")
summary["steps"]["mlst"] = mlst_text

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

# gapit 分型（registry 驱动；lm_doumith 等带 typing scheme 的库给出表型）
from bacmap.core.analysis.gapit_typing import summarize as summarize_gapit_typing  # noqa: E402

gapit_tp = summarize_gapit_typing(read_json(snakemake.input.gapit_typing, {}))
summary["steps"]["gapit_typing"] = {
    "status": gapit_tp["status"],
    "databases": gapit_tp["databases"],
}
# 血清群（如 L. monocytogenes Doumith serogroup）并入 serotype 段，注明来源 scheme
if gapit_tp["serogroup"]:
    summary["steps"]["serotype"]["serogroup"] = gapit_tp["serogroup"]
    summary["steps"]["serotype"]["serogroup_scheme"] = gapit_tp["serogroup_scheme"]

summary["steps"]["amr"] = {
    "abricate_vfdb": parse_tsv(snakemake.input.vfdb, []),
    "abricate_card": parse_tsv(snakemake.input.card, []),
    "amrfinderplus": parse_tsv(snakemake.input.amrfinderplus, []),
}

summary["steps"]["plasmid"] = {
    "plasmidfinder": parse_tsv(snakemake.input.plasmidfinder, []),
}

dec_serotype_path = opt_input("ectyper")
pathotype_path = opt_input("pathotype")
shigella_path = opt_input("shigella_serotype")
_dec_applicable = any(
    p is not None for p in (dec_serotype_path, pathotype_path, shigella_path)
)

if _dec_applicable:
    dec_serotype = read_json(dec_serotype_path, {}) if dec_serotype_path else {}
    if not isinstance(dec_serotype, dict):
        dec_serotype = {}
    # DEC 致病型：gapit `ecoli_dec` 的 typing 结果（v1.4.18，判定外部化）
    from bacmap.core.analysis.dec_pathotype import (
        summarize as summarize_dec_pathotype,  # noqa: E402
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

    shigella_serotype = read_json(shigella_path, {}) if shigella_path else {}
    if not isinstance(shigella_serotype, dict):
        shigella_serotype = {}
    summary["steps"]["dec"]["shigella_serotype"] = shigella_serotype.get("serotype", "N/A")
    summary["steps"]["dec"]["shigella_species"] = shigella_serotype.get("species", "N/A")
    if shigella_path is not None:
        summary["steps"]["dec"]["shigella_status"] = shigella_serotype.get("status", "N/A")
        summary["steps"]["dec"]["shigella_ipab"] = shigella_serotype.get("ipaB", "")
    else:
        summary["steps"]["dec"]["shigella_status"] = "not_applicable"

    ecoh_serotype_val = dec_serotype.get("serotype", "-:-")
    shigella_species_val = shigella_serotype.get("species", "N/A")
    shigella_serotype_val = shigella_serotype.get("serotype", "Undetermined")
    shigella_ran = shigella_serotype.get("status") == "ran"

    if shigella_ran and "Shigella" in shigella_species_val:
        primary_serotype = shigella_serotype_val
        serotype_method = "shigatyper"
    elif ecoh_serotype_val != "-:-":
        primary_serotype = ecoh_serotype_val
        serotype_method = "ecoh_serotyper (DEC/EIEC)"
    else:
        primary_serotype = "N/A"
        serotype_method = "N/A"

    summary["steps"]["dec"]["primary_serotype"] = primary_serotype
    summary["steps"]["dec"]["serotype_method"] = serotype_method
else:
    # 非 DEC/志贺菌物种：整段不适用（不跑 gapit ecoli_dec / ecoh / ShigaTyper）
    summary["steps"]["dec"] = {
        "status": "not_applicable",
        "reason": "DEC 致病型 / 志贺菌血清型仅适用于大肠埃希菌与志贺菌",
    }

vpa_serotype_path = opt_input("vpa_serotype")
vpa_serotype = read_json(vpa_serotype_path, {}) if vpa_serotype_path else {}
if not isinstance(vpa_serotype, dict):
    vpa_serotype = {}
if vpa_serotype.get("predicted_serotype"):
    summary["steps"]["vpa_serotype"] = {
        "predicted_serotype": vpa_serotype.get("predicted_serotype", "OUT:KUT"),
        "o_locus": vpa_serotype.get("o_locus", "None"),
        "k_locus": vpa_serotype.get("k_locus", "None"),
        "o_confidence": vpa_serotype.get("o_confidence", "Unknown"),
        "k_confidence": vpa_serotype.get("k_confidence", "Unknown"),
    }

vpa_virulence_path = opt_input("vpa_virulence")
vpa_virulence = read_json(vpa_virulence_path, {}) if vpa_virulence_path else {}
if isinstance(vpa_virulence, dict) and vpa_virulence:
    summary["steps"]["vpa_virulence"] = vpa_virulence

annotation = read_json(snakemake.input.annotation, {})
if isinstance(annotation, dict) and annotation.get("summary"):
    ann_summary = annotation.get("summary", {})
    top_genes = []
    _features = annotation.get("features", [])
    for feat in (_features if isinstance(_features, list) else [])[:20]:
        ident = feat.get("identity", 0) if isinstance(feat, dict) else 0
        if (
            isinstance(feat, dict)
            and feat.get("gene")
            and isinstance(ident, (int, float))
            and ident >= 80
        ):
            top_genes.append({
                "gene": feat["gene"],
                "product": feat.get("product", ""),
                "identity": ident,
                "source": feat.get("source", ""),
            })
    summary["steps"]["annotation"] = {
        "total_CDS": ann_summary.get("total_CDS", 0),
        "annotated_CDS": ann_summary.get("annotated_CDS", 0),
        "annotation_rate": ann_summary.get("annotation_rate", 0),
        "top_genes": top_genes,
    }


Path(snakemake.output.summary).parent.mkdir(parents=True, exist_ok=True)
Path(snakemake.output.summary).write_text(
    json.dumps(summary, ensure_ascii=False, indent=2)
)
