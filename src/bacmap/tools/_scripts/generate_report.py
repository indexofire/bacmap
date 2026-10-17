"""生成 HTML 分析报告（project.md §7.3 report step）。

用法:
    python scripts/generate_report.py --sample SAM-TYP-001
    python scripts/generate_report.py --all
    python scripts/generate_report.py --cohort                       # SNP cohort
    python scripts/generate_report.py --cohort --group salmonella    # cgMLST cohort
    python scripts/generate_report.py --cohort --group all           # 全部 cgMLST cohort
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from bacmap.config import GOM_DB as _NLI_DB_PATH  # noqa: E402
from bacmap.config import REF_DIR, RESULTS_DIR, WORKFLOWS_DIR
from bacmap.core.analysis.cgmlst_projection import (  # noqa: E402
    ProjectionResult,
    Verdict,
    load_thresholds_from_config,
    project_sample,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile  # noqa: E402
from bacmap.core.utils import (  # noqa: E402
    parse_abricate_tsv,
    parse_cgmlst_profile,
    parse_cgmlst_profiles,
    parse_mlst,
)
from bacmap.core.verify.deterministic_verifier import DeterministicVerifier  # noqa: E402

RESULTS_DIR = RESULTS_DIR
# Module-level so tests can monkey-patch without touching disk.
CGMLST_REFERENCE_DIR = REF_DIR / "cgmlst"
CONFIG_PATH = WORKFLOWS_DIR / "bacmap" / "config" / "config.yaml"

# Fold species strings to reference-library dir names (must match
# config.yaml cgmlst.thresholds keys + build_cgmlst_reference.py output dir).
_CGMLST_SPECIES_DIRS: dict[str, str] = {
    "salmonella": "salmonella",
    "ecoli": "ecoli",
    "escherichiacoli": "ecoli",
    "shigella": "shigella",
    "vparahaemolyticus": "vparahaemolyticus",
    "vibrioparahaemolyticus": "vparahaemolyticus",
}


def _row(label: str, value: str, ok: bool = True) -> str:
    # P2-1：值域含样本衍生字符串（基因名/血清型/verdict），统一转义防 HTML 注入
    cls = "ok" if ok else "fail"
    return (
        f'<tr><td class="label">{html.escape(str(label))}</td>'
        f'<td class="{cls}">{html.escape(str(value))}</td></tr>'
    )


def _gene_table(genes: list[dict], title: str) -> str:
    if not genes:
        return f"<h3>{html.escape(title)}</h3><p>未检出</p>"
    rows = "".join(
        f"<tr><td>{html.escape(str(g.get('GENE', '?')))}</td>"
        f"<td>{html.escape(str(g.get('%IDENTITY', '?')))}</td>"
        f"<td>{html.escape(str(g.get('%COVERAGE', '?')))}</td>"
        f"<td>{html.escape(str(g.get('RESISTANCE', '')))}</td></tr>"
        for g in genes[:20]
    )
    extra = f"<p><em>显示前 20 个，共 {len(genes)} 个</em></p>" if len(genes) > 20 else ""
    return f"""
    <h3>{html.escape(title)} ({len(genes)} genes)</h3>
    <table><tr><th>Gene</th><th>%Identity</th><th>%Coverage</th><th>Resistance</th></tr>
    {rows}</table>{extra}"""


# ---------------------------------------------------------------------------
# Per-sample cgMLST trace-back card (plan todo 9)
# ---------------------------------------------------------------------------


def _extract_species(summary: dict) -> str:
    # Handles both shapes seen in the wild: ``steps.species.species`` (current
    # pipeline output) and ``steps.species.verdict`` (legacy/ingest path).
    sp = summary.get("steps", {}).get("species", {})
    if isinstance(sp, dict):
        return str(sp.get("species") or sp.get("verdict") or "")
    if isinstance(sp, str):
        return sp
    return ""


def _species_dir_name(species: str) -> str:
    folded = species.lower().replace(".", "").replace(" ", "")
    if folded in _CGMLST_SPECIES_DIRS:
        return _CGMLST_SPECIES_DIRS[folded]
    # Fall back to the first word so "Shigella sonnei" -> "shigella" and
    # "Salmonella enterica" -> "salmonella" (covers subspecies strings the
    # species identifier emits for Shigella serovars).
    first_word = species.lower().split()[0].replace(".", "") if species else ""
    if first_word in _CGMLST_SPECIES_DIRS:
        return _CGMLST_SPECIES_DIRS[first_word]
    return species.lower().replace(" ", "")


def _load_reference_profiles(species: str) -> list[CgmlstProfile]:
    # Returns [] when the library is absent or unreadable so the caller can
    # render profile-only stats without crashing the report (graceful
    # degradation per plan todo 9).
    if not species:
        return []
    ref_path = CGMLST_REFERENCE_DIR / _species_dir_name(species) / "reference_profiles.tsv"
    if not ref_path.exists():
        return []
    try:
        return parse_cgmlst_profiles(ref_path.read_text())
    except (ValueError, OSError):
        return []


def _load_top_n_from_config(config_path: Path) -> int:
    try:
        import yaml
    except ImportError:
        return 10
    try:
        loaded = yaml.safe_load(config_path.read_text()) or {}
    except (OSError, ValueError):
        return 10
    cfg: dict[str, object] = loaded if isinstance(loaded, dict) else {}
    projection = cfg.get("cgmlst", {})
    if not isinstance(projection, dict):
        return 10
    nested = projection.get("projection", {})
    if not isinstance(nested, dict):
        return 10
    value = nested.get("top_n")
    return int(value) if isinstance(value, int) and value > 0 else 10


def _compute_projection(profile: CgmlstProfile, species: str) -> ProjectionResult | None:
    # Best-effort: returns None on any failure (no reference library, unknown
    # species, missing thresholds, parse error) so the caller falls back to
    # profile-only rendering instead of crashing the report.
    if not species or profile.n_total == 0:
        return None
    reference = _load_reference_profiles(species)
    if not reference:
        return None
    # Canonical species key (e.g. "shigella") for config/dir lookup, but pass
    # the original species string to project_sample so the S. sonnei caveat
    # check (_is_ssonnei substring match) still fires.
    canonical = _species_dir_name(species)
    try:
        thresholds = load_thresholds_from_config(CONFIG_PATH, canonical)
        top_n = _load_top_n_from_config(CONFIG_PATH)
    except (ValueError, RuntimeError, OSError):
        return None
    try:
        return project_sample(profile, reference, thresholds, species=species, top_n=top_n)
    except ValueError:
        return None


def _verdict_badge_html(verdict: Verdict) -> str:
    label = str(verdict).upper()
    return f'<div class="cgmlst-verdict-badge cgmlst-verdict-{verdict}">{label}</div>'


def _cgmlst_nearest_table(projection: ProjectionResult) -> str:
    if not projection.nearest:
        return ""
    rows = "".join(
        f'<tr><td>{i + 1}</td><td>{m.sample_id}</td><td class="dist">{m.distance}</td></tr>'
        for i, m in enumerate(projection.nearest)
    )
    return f"""
    <h3>Top {len(projection.nearest)} nearest references</h3>
    <table class="cgmlst-nearest">
    <tr><th>#</th><th>Reference</th><th>Allele distance</th></tr>
    {rows}</table>"""


def _cgmlst_caveats_html(caveats: list[str]) -> str:
    if not caveats:
        return ""
    items = "".join(f"<li>{c}</li>" for c in caveats)
    return f'<div class="cgmlst-caveats"><strong>⚠️ Caveats:</strong><ul>{items}</ul></div>'


def _render_cgmlst_section(sample_id: str, summary: dict) -> str:
    # Returns "" when cgmlst.tsv is absent so the section is omitted cleanly
    # (plan todo 9 acceptance). When the TSV exists but no reference library is
    # available, renders profile stats only without projection (graceful
    # degradation).
    cgmlst_path = RESULTS_DIR / sample_id / "typing" / "cgmlst.tsv"
    if not cgmlst_path.exists():
        return ""

    try:
        profile = parse_cgmlst_profile(cgmlst_path.read_text())
    except (ValueError, OSError):
        return ""

    if not profile.scheme or profile.n_total == 0:
        return ""

    species = _extract_species(summary)
    projection = _compute_projection(profile, species)

    missing = profile.n_total - profile.n_called
    missing_rate = (missing / profile.n_total * 100) if profile.n_total else 0.0
    called_pct = (profile.n_called / profile.n_total * 100) if profile.n_total else 0.0

    badge_html = ""
    nearest_html = ""
    caveats: list[str] = []
    projection_rows = ""

    if projection is not None:
        badge_html = _verdict_badge_html(projection.verdict)
        caveats = list(projection.caveats)
        nearest_html = _cgmlst_nearest_table(projection)
        if projection.nearest:
            top = projection.nearest[0]
            projection_rows = (
                f"{_row('Nearest reference', f'{top.sample_id} (distance {top.distance})')}"
                f"{_row('Comparable loci (nearest)', str(projection.n_comparable_loci))}"
            )
        else:
            projection_rows = _row("Nearest reference", "—")
    else:
        badge_html = _verdict_badge_html(Verdict.UNDETERMINED)
        if species and not _load_reference_profiles(species):
            caveats.append(
                f"no reference library at data/reference/cgmlst/"
                f"{_species_dir_name(species)}/; projection skipped"
            )
        elif species:
            caveats.append(
                f"no cgMLST thresholds configured for species {species!r}; projection skipped"
            )
        else:
            caveats.append("species undetermined; projection skipped")

    loci_rows = (
        f"{_row('Scheme', profile.scheme)}"
        f"{_row('Total loci', str(profile.n_total))}"
        f"{_row('Called', f'{profile.n_called} ({called_pct:.1f}%)')}"
        f"{_row('Missing rate', f'{missing_rate:.2f}%')}"
    )
    if profile.novel_loci:
        loci_rows += _row("Novel loci", str(len(profile.novel_loci)))
    if profile.ambiguous_loci:
        loci_rows += _row("Ambiguous loci", str(len(profile.ambiguous_loci)))
    if profile.missing_loci:
        loci_rows += _row("Missing loci", str(len(profile.missing_loci)))

    return f"""
    <h2>🧭 cgMLST 溯源 (Trace-back)</h2>
    {badge_html}
    <table>
    {loci_rows}
    {projection_rows}
    </table>
    {nearest_html}
    {_cgmlst_caveats_html(caveats)}"""


def _render_nli_section(sample_id: str) -> str:
    """P1-4：读回最近一次 nli_reflected 审计事件，渲染「AI 解读自检」章节。

    无事件（未触发人审）/ 无 DB / 读失败 → 空串（章节缺省，报告不受影响）。
    """
    from bacmap.core.verify.nli_reflector import latest_review_flag

    flag = latest_review_flag(_NLI_DB_PATH, sample_id)
    if not flag or not flag.get("needs_human_review"):
        return ""

    claims = flag.get("contradicted_claims", [])
    claim_rows = "".join(
        f"<tr><td>{html.escape(str(c.get('claim_type', '')))}</td>"
        f"<td>{html.escape(str(c.get('value', '')))}"
        f"{'（否定式）' if c.get('negated') else ''}</td>"
        f"<td>{html.escape(str(c.get('evidence', '')))}</td></tr>"
        for c in claims
    )
    return f"""
<h2>⚠️ AI 解读自检（Layer 3 NLI Reflector）</h2>
<table>
<tr><th>指标</th><th>值</th></tr>
{_row("人审标记", "NEEDS HUMAN REVIEW")}
{_row("矛盾率", f"{flag.get('contradiction_rate', 0):.2f}（阈值 {flag.get('threshold', '—')}）")}
{_row("可验证 claims", flag.get("verifiable_count", "—"))}
{_row("佐证 claims", flag.get("corroborated_count", "—"))}
{_row("审计时间", flag.get("timestamp", "—"))}
</table>
<p>以下 AI 解读中的 claims 与管线事实矛盾（人审请核对）：</p>
<table>
<tr><th>Claim 类型</th><th>内容</th><th>事实依据</th></tr>
{claim_rows}
</table>
"""


def generate_html(sample_id: str, summary: dict, verification, output_path: Path):
    steps = summary.get("steps", {})

    sp = steps.get("species", {})
    verdict = sp.get("verdict", "N/A") if isinstance(sp, dict) else str(sp)

    mlst_info = parse_mlst(steps.get("mlst", ""))
    st = mlst_info.get("st", "N/A")
    alleles = mlst_info.get("alleles", {})

    sero = steps.get("serotype", {})
    serovar = sero.get("sistr", "N/A") if isinstance(sero, dict) else "N/A"
    serogroup = sero.get("serogroup", "") if isinstance(sero, dict) else ""
    o_antigen = sero.get("o_antigen", "") if isinstance(sero, dict) else ""
    h1 = sero.get("h1", "") if isinstance(sero, dict) else ""
    h2 = sero.get("h2", "") if isinstance(sero, dict) else ""

    card_genes = parse_abricate_tsv("")
    card_path = RESULTS_DIR / sample_id / "amr" / "abricate_card.tsv"
    if card_path.exists():
        card_genes = parse_abricate_tsv(card_path.read_text())
    vfdb_path = RESULTS_DIR / sample_id / "amr" / "abricate_vfdb.tsv"
    vfdb_genes = parse_abricate_tsv(vfdb_path.read_text()) if vfdb_path.exists() else []
    plasmid_path = RESULTS_DIR / sample_id / "plasmid" / "abricate_plasmidfinder.tsv"
    plasmid_genes = parse_abricate_tsv(plasmid_path.read_text()) if plasmid_path.exists() else []

    asm_stats = steps.get("assembly", "")
    asm_parts = asm_stats.strip().split("\n")[-1].split("\t") if asm_stats else []
    num_contigs = asm_parts[2] if len(asm_parts) > 2 else "?"
    total_len = asm_parts[4] if len(asm_parts) > 4 else "?"

    v_icon = "✅" if verification.passed else "❌"
    v_review = '<span class="warn">⚠️ 需要人工审核</span>' if verification.needs_human_review else ""

    check_rows = "".join(
        f'<tr><td>{c.name}</td><td class="{"ok" if c.passed else "fail"}">'
        f"{'✅' if c.passed else '❌'} {c.message}</td></tr>"
        for c in verification.checks
    )

    allele_str = " ".join(f"{k}={v}" for k, v in alleles.items()) if alleles else "N/A"

    cgmlst_section = _render_cgmlst_section(sample_id, summary)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{sample_id} 分析报告</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #333; }}
h1 {{ color: #1a5276; border-bottom: 3px solid #2980b9; padding-bottom: 0.3em; }}
h2 {{ color: #2874a6; margin-top: 1.5em; }}
h3 {{ color: #2e86c1; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9em; }}
th {{ background: #ebf5fb; }}
td.label {{ font-weight: bold; width: 180px; background: #f8f9fa; }}
.ok {{ color: #27ae60; }}
.fail {{ color: #e74c3c; }}
.warn {{ color: #f39c12; font-weight: bold; }}
.verdict-box {{ display: inline-block; padding: 8px 20px; border-radius: 6px; font-size: 1.2em; font-weight: bold; margin: 10px 0; }}
.verdict-pass {{ background: #d4edda; color: #155724; }}
.verdict-fail {{ background: #f8d7da; color: #721c24; }}
.evidence {{ background: #f0f0f0; padding: 10px; border-radius: 5px; font-size: 0.85em; margin-top: 2em; }}
.cgmlst-verdict-badge {{ display: inline-block; padding: 6px 16px; border-radius: 5px; font-weight: bold; font-size: 1.05em; margin: 6px 0; }}
.cgmlst-verdict-outbreak {{ background: #f8d7da; color: #721c24; }}
.cgmlst-verdict-related {{ background: #fff3cd; color: #856404; }}
.cgmlst-verdict-unrelated {{ background: #d4edda; color: #155724; }}
.cgmlst-verdict-undetermined {{ background: #e9ecef; color: #495057; }}
.cgmlst-nearest td.dist {{ text-align: right; }}
.cgmlst-caveats {{ background: #fff3cd; border-left: 4px solid #f39c12; padding: 8px 12px; margin: 0.5em 0; font-size: 0.88em; }}
.cgmlst-caveats ul {{ margin: 4px 0 0 0; }}
</style></head>
<body>
<h1>🧬 {sample_id} 全基因组分析报告</h1>
<p>生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="verdict-box {"verdict-pass" if verification.passed else "verdict-fail"}">
{v_icon} Verifier: {"ALL PASSED" if verification.passed else f"{verification.failed_count} FAILED"} {v_review}
</div>

<h2>📋 基本信息</h2>
<table>
{_row("样本编号", sample_id)}
{_row("物种判定", verdict, "Salmonella" in verdict)}
{_row("MLST ST", st)}
{_row("MLST Alleles", allele_str)}
{_row("血清型", serovar)}
{_row("血清群", serogroup)}
{_row("抗原式", f"{o_antigen}:{h1}:{h2}")}
{_row("Contigs 数", num_contigs)}
{_row("组装总长度", f"{total_len} bp")}
</table>

<h2>🔬 Deterministic Verifier 校验</h2>
<table>
<tr><th>检查项</th><th>结果</th></tr>
{check_rows}
</table>

{_render_nli_section(sample_id)}

<h2>💊 AMR 耐药基因 (CARD)</h2>
{_gene_table(card_genes, "CARD AMR Genes")}

<h2>🦠 毒力基因 (VFDB)</h2>
{_gene_table(vfdb_genes, "VFDB Virulence Genes")}

<h2>🧬 质粒复制子 (PlasmidFinder)</h2>
{_gene_table(plasmid_genes, "PlasmidFinder")}
{cgmlst_section}

<div class="evidence">
<h3>📌 三元证据链 (project.md §4.5)</h3>
<p><strong>strain_id:</strong> {sample_id}</p>
<p><strong>pipeline_version:</strong> {summary.get("pipeline_version", "salmonella-workflow-v0.1")}</p>
<p><strong>tool_versions:</strong> fastp, Shovill 1.1.0, blastn 2.17.0+, gmlst 0.1.0, SISTR 1.1.3, abricate 1.4.0</p>
<p><strong>database_versions:</strong> CARD 2026-Apr-3, VFDB 2026-Apr-3, PlasmidFinder 2026-Apr-3, PubMLST salmonella_2</p>
</div>

</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _distance_color(d: int, max_d: int) -> str:
    if max_d == 0:
        return "#ffffff"
    ratio = d / max_d
    r = int(255 * ratio)
    g = int(255 * (1 - ratio))
    return f"rgb({r},{g},80)"


def _distance_heatmap_html(samples: list[str], distances: dict[str, int]) -> str:
    """Render an upper/lower-triangular distance heatmap table.

    Shared by the SNP cohort report (``pairwise_distances``) and the cgMLST
    cohort report (``allele_distances``) -- both lookups use the
    ``"sampleA|sampleB" -> int`` convention established by
    ``generate_snp_summary.py``. Cells are shaded by ``_distance_color``
    (green→red gradient keyed off the matrix max). Below-diagonal cells are
    rendered at half opacity so the diagonal symmetry is visible without
    drowning the upper triangle in duplicate saturation.
    """
    max_d = max(distances.values()) if distances else 1
    header = "".join(f"<th>{s}</th>" for s in samples)
    rows = ""
    for i, s1 in enumerate(samples):
        cells = f"<td class='label'>{s1}</td>"
        for j, s2 in enumerate(samples):
            if i == j:
                cells += "<td style='text-align:center;color:#aaa;'>—</td>"
            elif i < j:
                d = distances.get(f"{s1}|{s2}", 0)
                color = _distance_color(d, max_d)
                cells += f"<td style='background:{color};text-align:right;'>{d}</td>"
            else:
                d = distances.get(f"{s2}|{s1}", 0)
                color = _distance_color(d, max_d)
                cells += f"<td style='background:{color};text-align:right;opacity:0.5;'>{d}</td>"
        rows += f"<tr>{cells}</tr>\n"
    return f"<tr><th>样本</th>{header}</tr>\n{rows}"


def _phylotree_block_html(container_id: str, fallback_id: str, newick: str) -> str:
    """Render a phylotree.js + D3 v7 widget from a Newick string.

    Reused by the SNP and cgMLST cohort reports. The rendering pattern
    (``d3.layout.phylotree()`` + ``newick_escaped`` injection) is Newick-
    agnostic: any valid Newick drops straight in, so the cgMLST MST/NJ tree
    and the SNP IQ-TREE share the same JS path -- no new JS dependency.
    """
    newick_escaped = newick.replace("\\", "\\\\").replace("'", "\\'")
    return f"""
<div id="{container_id}"></div>
<div class="fallback-tree" id="{fallback_id}">{newick}</div>
<script>
if (typeof d3 !== 'undefined' && typeof phylotree !== 'undefined') {{
    var tree = d3.layout.phylotree()
        .svg(d3.select("#{container_id}").append("svg:svg"))
        .options({{'selectable': false, 'collapsible': false}});
    tree({newick_escaped});
    tree.layout();
    document.getElementById('{fallback_id}').style.display = 'none';
}}
</script>"""


def generate_cohort_html(snp_summary: dict, output_path: Path):

    newick = snp_summary.get("tree_newick", "")
    n_sites = snp_summary.get("n_snp_sites", 0)
    n_samples = snp_summary.get("n_samples", 0)
    missing = snp_summary.get("missing_rate", 0)
    samples = snp_summary.get("samples", [])
    distances = snp_summary.get("pairwise_distances", {})

    max_d = max(distances.values()) if distances else 1

    dist_header = "".join(f"<th>{s}</th>" for s in samples)
    dist_rows = ""
    for i, s1 in enumerate(samples):
        cells = f"<td class='label'>{s1}</td>"
        for j, s2 in enumerate(samples):
            if i == j:
                cells += "<td style='text-align:center;color:#aaa;'>—</td>"
            elif i < j:
                key = f"{s1}|{s2}"
                d = distances.get(key, 0)
                color = _distance_color(d, max_d)
                cells += f"<td style='background:{color};text-align:right;'>{d}</td>"
            else:
                key = f"{s2}|{s1}"
                d = distances.get(key, 0)
                color = _distance_color(d, max_d)
                cells += f"<td style='background:{color};text-align:right;opacity:0.5;'>{d}</td>"
        dist_rows += f"<tr>{cells}</tr>\n"

    newick_escaped = newick.replace("\\", "\\\\").replace("'", "\\'")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>SNP 系统发育分析报告</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://raw.githack.com/rdvelin/phylotree.js/master/dist/phylotree.js"></script>
<link rel="stylesheet" href="https://raw.githack.com/rdvelin/phylotree.js/master/dist/phylotree.css">
<style>
body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #333; }}
h1 {{ color: #1a5276; border-bottom: 3px solid #2980b9; padding-bottom: 0.3em; }}
h2 {{ color: #2874a6; margin-top: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 0.85em; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
th {{ background: #ebf5fb; }}
td.label {{ font-weight: bold; background: #f8f9fa; }}
.stats-box {{ display: flex; gap: 20px; margin: 1em 0; }}
.stat-card {{ background: #ebf5fb; padding: 12px 24px; border-radius: 8px; text-align: center; }}
.stat-card .value {{ font-size: 1.8em; font-weight: bold; color: #2980b9; }}
.stat-card .label {{ font-size: 0.85em; color: #666; }}
#tree-container {{ background: #fff; border: 1px solid #ddd; border-radius: 5px; padding: 10px; min-height: 400px; }}
.fallback-tree {{ font-family: monospace; white-space: pre; font-size: 0.8em; background: #f8f9fa; padding: 1em; overflow-x: auto; }}
</style></head>
<body>
<h1>🌲 SNP 系统发育分析报告</h1>
<p>生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="stats-box">
<div class="stat-card"><div class="value">{n_samples}</div><div class="label">样本数</div></div>
<div class="stat-card"><div class="value">{n_sites:,}</div><div class="label">SNP 位点数</div></div>
<div class="stat-card"><div class="value">{missing * 100:.1f}%</div><div class="label">缺失率</div></div>
<div class="stat-card"><div class="value">{len(distances)}</div><div class="label">比较对数</div></div>
</div>

<h2>🌳 系统发育树 (Maximum Likelihood, GTR+UFBoot1000)</h2>
<div id="tree-container"></div>
<div class="fallback-tree" id="fallback">{newick}</div>

<h2>📊 SNP 距离矩阵</h2>
<table>
<tr><th>样本</th>{dist_header}</tr>
{dist_rows}
</table>

<script>
if (typeof d3 !== 'undefined' && typeof phylotree !== 'undefined') {{
    var tree = d3.layout.phylotree()
        .svg(d3.select("#tree-container").append("svg:svg"))
        .options({{'selectable': false, 'collapsible': false}});
    tree({newick_escaped});
    tree.layout();
    document.getElementById('fallback').style.display = 'none';
}}
</script>

</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Cohort cgMLST report (plan todo 14)
# ---------------------------------------------------------------------------


def _thresholds_html(thresholds: dict[str, object]) -> str:
    """Render the ``thresholds_applied`` audit-trail block (empty if absent)."""
    if not thresholds:
        return ""
    items = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in thresholds.items())
    return f'<div class="cgmlst-thresholds"><h3>Applied thresholds</h3><dl>{items}</dl></div>'


def generate_cgmlst_cohort_html(cgmlst_summary: dict, output_path: Path) -> None:
    """Render the cgMLST cohort tree + allele-distance heatmap HTML.

    Reads the cgMLST summary schema (samples/n_samples/scheme/n_loci/
    allele_distances/tree_newick/missing_rate/thresholds_applied) produced
    by ``generate_cgmlst_summary.py``. ``allele_distances`` uses the same
    ``"sampleA|sampleB" -> int`` convention as the SNP ``pairwise_distances``
    dict, so the heatmap reuses ``_distance_heatmap_html``. The tree reuses
    ``_phylotree_block_html`` (same phylotree.js + D3 v7 stack as the SNP
    cohort report -- Newick-agnostic, no new JS dependency).
    """
    newick = cgmlst_summary.get("tree_newick", "")
    scheme = cgmlst_summary.get("scheme", "N/A")
    n_loci = cgmlst_summary.get("n_loci", 0)
    n_samples = cgmlst_summary.get("n_samples", 0)
    missing = cgmlst_summary.get("missing_rate", 0)
    samples = cgmlst_summary.get("samples", [])
    distances = cgmlst_summary.get("allele_distances", {})
    group = cgmlst_summary.get("group", "cohort")
    organism = cgmlst_summary.get("organism", "")
    thresholds = cgmlst_summary.get("thresholds_applied", {})

    int_distances = {str(k): int(v) for k, v in distances.items()}

    heatmap_rows = _distance_heatmap_html(samples, int_distances)
    tree_block = _phylotree_block_html(
        container_id="cgmlst-tree-container",
        fallback_id="cgmlst-fallback",
        newick=newick,
    )
    thresholds_block = _thresholds_html(thresholds)
    title_organism = f" ({organism})" if organism else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>cgMLST 等位基因距离分析报告 [{group}]</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://raw.githack.com/rdvelin/phylotree.js/master/dist/phylotree.js"></script>
<link rel="stylesheet" href="https://raw.githack.com/rdvelin/phylotree.js/master/dist/phylotree.css">
<style>
body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #333; }}
h1 {{ color: #1a5276; border-bottom: 3px solid #2980b9; padding-bottom: 0.3em; }}
h2 {{ color: #2874a6; margin-top: 1.5em; }}
h3 {{ color: #2e86c1; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 0.85em; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
th {{ background: #ebf5fb; }}
td.label {{ font-weight: bold; background: #f8f9fa; }}
.stats-box {{ display: flex; gap: 20px; margin: 1em 0; flex-wrap: wrap; }}
.stat-card {{ background: #ebf5fb; padding: 12px 24px; border-radius: 8px; text-align: center; }}
.stat-card .value {{ font-size: 1.8em; font-weight: bold; color: #2980b9; }}
.stat-card .label {{ font-size: 0.85em; color: #666; }}
#cgmlst-tree-container {{ background: #fff; border: 1px solid #ddd; border-radius: 5px; padding: 10px; min-height: 400px; }}
.fallback-tree {{ font-family: monospace; white-space: pre; font-size: 0.8em; background: #f8f9fa; padding: 1em; overflow-x: auto; }}
.cgmlst-thresholds dl {{ display: grid; grid-template-columns: maxcontent 1fr; gap: 4px 12px; margin: 0.5em 0; }}
.cgmlst-thresholds dt {{ font-weight: bold; color: #555; }}
.cgmlst-thresholds dd {{ margin: 0; }}
</style></head>
<body>
<h1>🧭 cgMLST 等位基因距离分析报告 [{group}]{title_organism}</h1>
<p>生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="stats-box">
<div class="stat-card"><div class="value">{scheme}</div><div class="label">Scheme</div></div>
<div class="stat-card"><div class="value">{n_loci:,}</div><div class="label">Loci</div></div>
<div class="stat-card"><div class="value">{n_samples}</div><div class="label">样本数</div></div>
<div class="stat-card"><div class="value">{missing * 100:.1f}%</div><div class="label">缺失率</div></div>
<div class="stat-card"><div class="value">{len(int_distances)}</div><div class="label">比较对数</div></div>
</div>

<h2>🌳 cgMLST 树 (Hamming allele distance, MST/NJ)</h2>
{tree_block}

<h2>📊 等位基因距离矩阵 (Allele Distance Heatmap)</h2>
<table>
{heatmap_rows}
</table>

{thresholds_block}

</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _render_one_cgmlst_cohort(group: str, emit_pdf: bool = False) -> int:
    """Render a single cgMLST cohort report. Returns 0 ok / 1 if summary missing."""
    summary_path = RESULTS_DIR / "cgmlst" / group / "cgmlst_summary.json"
    if not summary_path.exists():
        print(
            f"  ✗ {summary_path} not found. Run cgmlst_summary rule first "
            "(workflows/bacmap/rules/cgmlst.smk)."
        )
        return 1
    cgmlst_summary = json.loads(summary_path.read_text())
    output = RESULTS_DIR / "cgmlst" / group / "cohort_report.html"
    generate_cgmlst_cohort_html(cgmlst_summary, output)
    print(f"  ✅ cgMLST cohort report [{group}]: {output}")
    if emit_pdf:
        _emit_pdf(output)
    return 0


def _render_cgmlst_cohort_groups(group: str, emit_pdf: bool = False) -> int:
    """Render one cgMLST cohort group, or all of them when ``group == "all"``.

    Mirrors the per-group iteration in ``ingest_results.py:248-268``
    (``ingest_cohort_snp``).
    """
    if group == "all":
        cgmlst_dir = RESULTS_DIR / "cgmlst"
        if not cgmlst_dir.exists():
            print(
                f"  ✗ {cgmlst_dir} not found. Run cgmlst_summary rule first "
                "(workflows/bacmap/rules/cgmlst.smk)."
            )
            return 1
        group_dirs = sorted(
            d for d in cgmlst_dir.iterdir() if d.is_dir() and (d / "cgmlst_summary.json").exists()
        )
        if not group_dirs:
            print(f"  ✗ No cgMLST cohort summaries found in {cgmlst_dir}")
            return 1
        rendered = 0
        for group_dir in group_dirs:
            if _render_one_cgmlst_cohort(group_dir.name, emit_pdf=emit_pdf) == 0:
                rendered += 1
        return 0 if rendered > 0 else 1

    return _render_one_cgmlst_cohort(group, emit_pdf=emit_pdf)


def html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """HTML → PDF：headless chromium 打印（对 D3/phylotree 渲染保真），
    weasyprint 兜底；均不可用或失败返回 False。

    P2-1（安全）：默认启用 chromium 沙箱；仅在沙箱化运行失败（容器/无
    user-ns 环境）时降级 --no-sandbox 重试一次并告警。
    """
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        exe = shutil.which(name)
        if exe is None:
            continue
        base_cmd = [
            exe,
            "--headless",
            "--disable-gpu",
            "--virtual-time-budget=15000",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        for sandbox in (True, False):
            cmd = base_cmd if sandbox else [*base_cmd[:3], "--no-sandbox", *base_cmd[3:]]
            try:
                proc = subprocess.run(  # noqa: S603
                    cmd, capture_output=True, timeout=120, check=False
                )
            except subprocess.TimeoutExpired:
                print(f"  ⚠ PDF: {name} timed out on {html_path.name}")
                return False
            if proc.returncode == 0 and pdf_path.exists():
                return True
            if not sandbox:
                print(f"  ⚠ PDF: {name} failed even with --no-sandbox")
    try:
        from weasyprint import HTML
    except ImportError:
        return False
    HTML(str(html_path)).write_pdf(str(pdf_path))
    return pdf_path.exists()


def main() -> int:
    return main_args(sys.argv[1:])


def main_args(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="生成 HTML 分析报告")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", type=str)
    group.add_argument("--all", action="store_true")
    group.add_argument("--cohort", action="store_true")
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="同时生成 PDF（headless chromium 打印，weasyprint 兜底）",
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help=(
            "cgMLST cohort group name (e.g. salmonella). Renders the cgMLST "
            "cohort report from results/cgmlst/<group>/cgmlst_summary.json. "
            "Use '--group all' to iterate every group. Requires --cohort."
        ),
    )
    args = parser.parse_args(argv)

    if args.group is not None and not args.cohort:
        parser.error("--group requires --cohort")

    if args.cohort:
        if args.group is not None:
            return _render_cgmlst_cohort_groups(args.group, emit_pdf=args.pdf)

        snp_path = RESULTS_DIR / "snp" / "snp_summary.json"
        if not snp_path.exists():
            print(f"  ✗ {snp_path} not found. Run snp_summary rule first.")
            return 1
        snp_summary = json.loads(snp_path.read_text())
        output = RESULTS_DIR / "snp" / "cohort_report.html"
        generate_cohort_html(snp_summary, output)
        print(f"  ✅ Cohort report: {output}")
        if args.pdf:
            _emit_pdf(output)
        return 0

    v = DeterministicVerifier()

    if args.all:
        import csv

        with (WORKFLOWS_DIR / "bacmap/config/samples.tsv").open() as f:
            samples = [r["sample"] for r in csv.DictReader(f, delimiter="\t")]
    else:
        samples = [args.sample]

    for sid in samples:
        sp = RESULTS_DIR / sid / "report" / f"{sid}_summary.json"
        if not sp.exists():
            print(f"  ✗ {sid}: summary.json not found")
            continue
        with sp.open() as f:
            summary = json.load(f)
        verification = v.verify_all(summary)
        output = RESULTS_DIR / sid / "report" / f"{sid}_report.html"
        generate_html(sid, summary, verification, output)
        icon = "✅" if verification.passed else "⚠️"
        print(
            f"  {icon} {sid}: {output.name} ({'passed' if verification.passed else 'NEEDS REVIEW'})"
        )
        if args.pdf:
            _emit_pdf(output)

    return 0


def _emit_pdf(html_output: Path) -> None:
    pdf_path = html_output.with_suffix(".pdf")
    if html_to_pdf(html_output, pdf_path):
        print(f"  📄 PDF: {pdf_path}")
    else:
        print("  ⚠ PDF: 无可用转换器（chromium/weasyprint），跳过")


if __name__ == "__main__":
    sys.exit(main())
