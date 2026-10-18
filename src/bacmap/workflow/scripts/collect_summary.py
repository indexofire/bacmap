"""Snakemake script: collect all analysis results into a summary JSON."""
import json
from pathlib import Path

sample = snakemake.wildcards.sample
summary = {"sample": sample, "steps": {}}

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

sistr = read_json(snakemake.input.sistr, [])
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

summary["steps"]["amr"] = {
    "abricate_vfdb": parse_tsv(snakemake.input.vfdb, []),
    "abricate_card": parse_tsv(snakemake.input.card, []),
    "amrfinderplus": parse_tsv(snakemake.input.amrfinderplus, []),
}

summary["steps"]["plasmid"] = {
    "plasmidfinder": parse_tsv(snakemake.input.plasmidfinder, []),
}

dec_serotype = read_json(snakemake.input.ectyper, {})
if not isinstance(dec_serotype, dict):
    dec_serotype = {}
# DEC 致病型：gapit `ecoli_dec` 的 typing 结果（v1.4.18，判定外部化）
from bacmap.core.analysis.dec_pathotype import summarize as summarize_dec_pathotype  # noqa: E402

dec_pt = summarize_dec_pathotype(read_json(snakemake.input.pathotype, {}))
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

shigella_serotype = read_json(snakemake.input.shigella_serotype, {})
if not isinstance(shigella_serotype, dict):
    shigella_serotype = {}
summary["steps"]["dec"]["shigella_serotype"] = shigella_serotype.get("serotype", "N/A")
summary["steps"]["dec"]["shigella_species"] = shigella_serotype.get("species", "N/A")

ecoh_serotype_val = dec_serotype.get("serotype", "-:-")
shigella_species_val = shigella_serotype.get("species", "N/A")
shigella_serotype_val = shigella_serotype.get("serotype", "Undetermined")

if "Shigella" in shigella_species_val and "Undetermined" not in shigella_serotype_val:
    primary_serotype = shigella_serotype_val
    serotype_method = "shigella_serotyper"
elif ecoh_serotype_val != "-:-":
    primary_serotype = ecoh_serotype_val
    serotype_method = "ecoh_serotyper (DEC/EIEC)"
else:
    sistr_serovar = sistr.get("serovar", "N/A") if isinstance(sistr, dict) else "N/A"
    primary_serotype = sistr_serovar
    serotype_method = "SISTR (Salmonella)"

summary["steps"]["dec"]["primary_serotype"] = primary_serotype
summary["steps"]["dec"]["serotype_method"] = serotype_method

vpa_serotype = read_json(snakemake.input.vpa_serotype, {})
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

vpa_virulence = read_json(snakemake.input.vpa_virulence, {})
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
