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
import math
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from bacmap.config import GOM_DB as _NLI_DB_PATH
from bacmap.config import REF_DIR, RESULTS_DIR, WORKFLOWS_DIR
from bacmap.core.analysis.cgmlst_projection import (
    ProjectionResult,
    Verdict,
    load_thresholds_from_config,
    project_sample,
)
from bacmap.core.analysis.cgmlst_types import CgmlstProfile
from bacmap.core.utils import (
    parse_cgmlst_profile,
    parse_mlst,
)
from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

RESULTS_DIR = RESULTS_DIR
# Module-level so tests can monkey-patch without touching disk.
CONFIG_PATH = WORKFLOWS_DIR / "bacmap" / "config" / "config.yaml"


def _row(label: str, value: str, ok: bool = True) -> str:
    # P2-1：值域含样本衍生字符串（基因名/血清型/verdict），统一转义防 HTML 注入
    cls = "ok" if ok else "fail"
    return (
        f'<tr><td class="label">{html.escape(str(label))}</td>'
        f'<td class="{cls}">{html.escape(str(value))}</td></tr>'
    )


def _antigen_locus(value: str) -> str:
    """VPA 抗原位点：``OL10V1`` → ``OL10``；``KL4`` 保持；未知位点原样。"""
    text = str(value or "").strip()
    return re.sub(r"V\d+$", "", text) if text else ""


def _vpa_formula_from_screen(sample_dir: Path) -> str:
    """从 gspec ``vpa_ok_screen.json`` 取 O/K 位点（旧 summary 无位点 ID 时）。"""
    path = sample_dir / "gspec" / "vpa_ok_screen.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    files = document.get("files")
    entry = files[0] if isinstance(files, list) and files and isinstance(files[0], dict) else {}
    phenotypes = entry.get("phenotypes")
    if not isinstance(phenotypes, dict):
        return ""

    def winner(name: str) -> str:
        call = phenotypes.get(name)
        return _antigen_locus(call.get("winner_locus", "")) if isinstance(call, dict) else ""

    o_locus, k_locus = winner("o_group"), winner("k_group")
    return f"{o_locus}:{k_locus}" if o_locus and k_locus else ""


def _bar_chart(rows: Sequence[tuple[str, float | int]], unit: str = "", limit: int = 10) -> str:
    """Pure-CSS horizontal bars (no scripts; works under the sandbox CSP)."""
    rows = [(str(name), float(value or 0)) for name, value in rows[:limit] if name]
    if not rows:
        return '<p class="muted">未检出</p>'
    top = max(value for _, value in rows) or 1
    pieces = []
    for name, value in rows:
        width = max(1.0, value / top * 100)
        shown = f"{value:g}" if unit == "" else f"{value:g}{unit}"
        pieces.append(
            '<div class="bar-row">'
            f'<span class="bar-label" title="{html.escape(name)}">{html.escape(name)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{width:.1f}%"></span></span>'
            f'<span class="bar-value mono">{html.escape(shown)}</span>'
            "</div>"
        )
    return '<div class="bars">' + "".join(pieces) + "</div>"


def _num(value: object) -> float:
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _class_counts(genes: list[dict]) -> list[tuple[str, int]]:
    from collections import Counter

    counts: Counter[str] = Counter()
    for gene in genes:
        raw = str(gene.get("RESISTANCE", "") or "")
        for part in raw.replace(";", ",").split(","):
            name = part.strip()
            if name and name.lower() not in {"serotype", "virulence", "replicon"}:
                counts[name] += 1
    return counts.most_common()


def _gene_table(
    genes: list[dict],
    title: str,
    *,
    value_key: str = "%COVERAGE",
    value_label: str = "%Coverage",
    limit: int = 12,
) -> str:
    if not genes:
        return f'<h3>{html.escape(title)}</h3><p class="muted">未检出</p>'

    def rows(items: list[dict]) -> str:
        return "".join(
            f"<tr><td><code>{html.escape(str(g.get('GENE', '?')))}</code></td>"
            f'<td class="mono">{html.escape(str(g.get("%IDENTITY", "?")))}</td>'
            f'<td class="mono">{html.escape(str(g.get(value_key, "?")))}</td>'
            f"<td>{html.escape(str(g.get('RESISTANCE', '') or '—'))}</td></tr>"
            for g in items
        )

    head = (
        "<table><tr><th>Gene</th><th>%Identity</th>"
        f"<th>{html.escape(value_label)}</th><th>类别 / 备注</th></tr>"
    )
    visible = rows(genes[:limit])
    more = ""
    if len(genes) > limit:
        more = (
            f'<details class="gene-details"><summary>查看全部 {len(genes)} 条</summary>'
            f"{head}{rows(genes)}</table></details>"
        )
    return (
        f'<h3>{html.escape(title)} <span class="muted">({len(genes)} genes)</span></h3>'
        f"{head}{visible}</table>{more}"
    )


def _stat_strip(items: list[tuple[str, str, str]]) -> str:
    return '<div class="stat-strip">' + "".join(
        '<div class="stat-strip__item">'
        f'<span class="stat-strip__label">{html.escape(label)}</span>'
        f'<strong class="stat-strip__value">{html.escape(value)}</strong>'
        f'<span class="stat-strip__hint">{html.escape(hint)}</span>'
        "</div>"
        for label, value, hint in items
    ) + "</div>"


_QUAST_THRESHOLD_RE = re.compile(r">= (\d+) bp\)")


def _quast_metrics(text: str) -> dict[str, str]:
    """QUAST 报告文本 → {指标: 值}。

    同时接受两种布局：``report.tsv``（纵向，一行一指标）与
    ``transposed_report.tsv``（横向，首行指标名 + 单行值），分别对应
    collect_summary 嵌入的历史文本与测试夹具。
    """
    lines = [line for line in text.strip().splitlines() if line.strip()]
    first = lines[0].split("\t") if lines else []
    # 转置布局：首行 "Assembly" + ≥2 个指标名，且数据行列数与表头一致；
    # 纵向 report.tsv 首行是 "Assembly\t<样本名>"（恒 2 列），逐行解析。
    if len(lines) >= 2 and first[0] == "Assembly" and len(first) >= 3 and len(lines[1].split("\t")) == len(first):
        values = lines[1].split("\t")[1:]
        return dict(zip(first[1:], values, strict=False))
    out: dict[str, str] = {}
    for line in lines:
        cells = line.split("\t")
        if len(cells) == 2 and cells[0] != "Assembly":
            out[cells[0].strip()] = cells[1].strip()
    return out


def _fmt_bp(value: object) -> str:
    """碱基数 → 人类可读长度（4703412 → 4.70 Mb；170133 → 170.1 kb）。"""
    try:
        n = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} Mb"
    if n >= 1_000:
        return f"{n / 1_000:.1f} kb"
    return f"{n:g} bp"


def _quast_threshold_rows(
    metrics: dict[str, str], prefix: str
) -> list[tuple[int, str, float]]:
    """抽取 "# contigs (>= X bp)" / "Total length (>= X bp)" 系列并按阈值升序。"""
    rows: list[tuple[int, str, float]] = []
    for name, value in metrics.items():
        match = _QUAST_THRESHOLD_RE.search(name)
        if not match or not name.startswith(prefix):
            continue
        rows.append((int(match.group(1)), f"≥ {int(match.group(1)):,} bp", _num(value)))
    rows.sort(key=lambda row: row[0])
    return rows


def _quast_bars(rows: list[tuple[str, float, str]], scale: float) -> str:
    """纯 CSS 水平条（复用报告既有 bar-row 体系；CSP 禁脚本，不用 SVG/JS）。

    ``rows`` 为 (标签, 数值, 值标签)；条宽按 ``scale`` 归一。
    """
    pieces = []
    for label, value, shown in rows:
        width = max(1.0, (value / scale * 100) if scale > 0 else 100.0)
        pieces.append(
            '<div class="bar-row">'
            f'<span class="bar-label">{html.escape(label)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{width:.1f}%"></span></span>'
            f'<span class="bar-value mono quast-bar-value">{html.escape(shown)}</span>'
            "</div>"
        )
    return '<div class="bars quast-bars">' + "".join(pieces) + "</div>"


def _extract_species(summary: dict) -> str:
    # Handles both shapes seen in the wild: ``steps.species.species`` (current
    # pipeline output) and ``steps.species.verdict`` (legacy/ingest path).
    sp = summary.get("steps", {}).get("species", {})
    if isinstance(sp, dict):
        return str(sp.get("species") or sp.get("verdict") or "")
    if isinstance(sp, str):
        return sp
    return ""


def _load_reference_profiles(scheme: str) -> list[CgmlstProfile]:
    # Returns [] when the library is absent or unreadable so the caller can
    # render profile-only stats without crashing the report (graceful
    # degradation per plan todo 9). 按 **scheme** 命名目录（单一实现）。
    from bacmap.core.analysis.cgmlst_reference import load_reference_profiles as _load_ref

    profiles = _load_ref(scheme, ref_dir=REF_DIR)
    return profiles or []


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
    if not species or profile.n_total == 0 or not profile.scheme:
        return None
    reference = _load_reference_profiles(profile.scheme)
    if not reference:
        return None
    # thresholds key = 三字母码（load_thresholds_from_config 经 species_code 归一）；
    # project_sample 仍收原始 species 串（S. sonnei caveat 的子串匹配）。
    try:
        thresholds = load_thresholds_from_config(CONFIG_PATH, species)
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
    return f'<div class="cgmlst-caveats"><strong>Caveats:</strong><ul>{items}</ul></div>'


def _render_cgmlst_section(sample_id: str, summary: dict) -> str:
    # Returns "" when the cgMLST profile is absent so the section is omitted
    # cleanly (plan todo 9 acceptance). JSON is the canonical format
    # (typing/cgmlst.json); legacy runs fall back to typing/cgmlst.tsv.
    cgmlst_path = RESULTS_DIR / sample_id / "typing" / "cgmlst.json"
    if not cgmlst_path.is_file():
        cgmlst_path = RESULTS_DIR / sample_id / "typing" / "cgmlst.tsv"
    if not cgmlst_path.is_file():
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
        if species and not _load_reference_profiles(profile.scheme):
            caveats.append(
                f"no reference library at data/reference/cgmlst/{profile.scheme}/; "
                "projection skipped"
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
    """AI 解读 + NLI 自检（有持久化解读文本或人审标记时展示）。"""
    from bacmap.core.verify.nli_reflector import latest_review_flag

    flag = latest_review_flag(_NLI_DB_PATH, sample_id)
    if not flag:
        return ""

    text = str(flag.get("interpretation_text") or "").strip()
    needs_review = bool(flag.get("needs_human_review"))
    if not text and not needs_review:
        return ""

    paragraphs = "".join(
        f"<p>{html.escape(chunk.strip())}</p>"
        for chunk in text.split("\n\n")
        if chunk.strip()
    )
    claims = flag.get("contradicted_claims", [])
    claim_rows = "".join(
        f"<tr><td>{html.escape(str(c.get('claim_type', '')))}</td>"
        f"<td>{html.escape(str(c.get('value', '')))}"
        f"{'（否定式）' if c.get('negated') else ''}</td>"
        f"<td>{html.escape(str(c.get('evidence', '')))}</td></tr>"
        for c in claims
    )
    verdict = "需要人工审核" if needs_review else "已通过 NLI 自检"
    verdict_cls = "badge--fail" if needs_review else "badge--ok"
    return f"""
<h2>AI 解读与 NLI 自检</h2>
<p><span class="badge {verdict_cls}">{verdict}</span></p>
<div class="ai-text">{paragraphs}</div>
<table>
<tr><th>指标</th><th>值</th></tr>
{_row("矛盾率", f"{flag.get('contradiction_rate', 0):.2f}（阈值 {flag.get('threshold', '—')}）")}
{_row("可验证 claims", flag.get("verifiable_count", "—"))}
{_row("佐证 claims", flag.get("corroborated_count", "—"))}
{_row("审计时间", flag.get("timestamp", "—"))}
</table>
{f'<p class="muted">以下 AI 解读中的 claims 与管线事实矛盾，请人工核对：</p><table><tr><th>Claim 类型</th><th>内容</th><th>事实依据</th></tr>{claim_rows}</table>' if claims else ''}
"""


def _render_amr_section(genes: list[dict]) -> str:
    classes = _class_counts(genes)
    top = sorted(
        genes, key=lambda g: _num(g.get("%IDENTITY", 0)), reverse=True
    )[:10]
    top_rows = [(str(g.get("GENE", "?")), _num(g.get("%IDENTITY", 0))) for g in top]
    return f"""
<h2>耐药基因（CARD）</h2>
<div class="chart-grid">
  <div class="chart-card"><h3>耐药类别分布</h3>{_bar_chart(classes)}</div>
  <div class="chart-card"><h3>高置信基因（%Identity）</h3>{_bar_chart(top_rows, "%")}</div>
</div>
{_gene_table(genes, "CARD AMR Genes", value_key="%COVERAGE", value_label="%Coverage")}
"""


def _render_vf_section(genes: list[dict]) -> str:
    top = sorted(
        genes, key=lambda g: _num(g.get("%IDENTITY", 0)), reverse=True
    )[:10]
    top_rows = [(str(g.get("GENE", "?")), _num(g.get("%IDENTITY", 0))) for g in top]
    return f"""
<h2>毒力基因（VFDB）</h2>
<div class="chart-grid">
  <div class="chart-card"><h3>高置信毒力基因（%Identity）</h3>{_bar_chart(top_rows, "%")}</div>
</div>
{_gene_table(genes, "VFDB Virulence Genes", value_key="%COVERAGE", value_label="%Coverage")}
"""


def _render_plasmid_section(genes: list[dict]) -> str:
    return f"""
<h2>质粒复制子（PlasmidFinder）</h2>
{_gene_table(genes, "PlasmidFinder", value_key="%COVERAGE", value_label="%Coverage")}
"""


def _nx_svg(points: list[dict], *, width: int = 560, height: int = 180) -> str:
    """Nx 曲线（纯内联 SVG；报告 CSP 禁脚本，SVG 不进图片外链）。"""
    values: list[tuple[float, float]] = []
    for point in points:
        try:
            values.append((float(point.get("x", 0)), float(point.get("length", 0))))
        except (TypeError, ValueError):
            continue
    if not values:
        return ""
    max_len = max(value for _x, value in values) or 1
    pad_l, pad_r, pad_t, pad_b = 48, 14, 14, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def px(x: float) -> float:
        return pad_l + plot_w * x / 100

    def py(y: float) -> float:
        return pad_t + plot_h * (1 - y / max_len)

    line = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in values)
    area = f"{px(0):.1f},{py(0):.1f} " + line + f" {px(100):.1f},{py(0):.1f}"
    n50 = next((y for x, y in values if x == 50), 0)
    marker = ""
    if n50:
        marker = (
            f'<circle cx="{px(50):.1f}" cy="{py(n50):.1f}" r="3.5"'
            ' fill="var(--accent)" stroke="var(--panel)" stroke-width="1.5"/>'
            f'<text x="{px(50) + 6:.1f}" y="{py(n50) - 6:.1f}"'
            ' font-size="10" fill="var(--text-2)">N50 '
            f"{html.escape(_fmt_bp(n50))}</text>"
        )
    return (
        f'<svg class="nx-curve" viewBox="0 0 {width} {height}" role="img"'
        ' aria-label="Nx 曲线（累计长度百分比与 contig 长度）"'
        ' style="width:100%;height:auto;display:block">'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}"'
        ' stroke="var(--border)" stroke-width="1"/>'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}"'
        f' y2="{pad_t + plot_h}" stroke="var(--border)" stroke-width="1"/>'
        f'<polygon points="{area}" fill="var(--accent)" opacity="0.10"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--accent)"'
        ' stroke-width="2" stroke-linejoin="round"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + 8}" text-anchor="end" font-size="10"'
        f' fill="var(--text-3)">{html.escape(_fmt_bp(max_len))}</text>'
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" text-anchor="end" font-size="10"'
        ' fill="var(--text-3)">0</text>'
        f'<text x="{pad_l}" y="{height - 8}" text-anchor="middle" font-size="10"'
        ' fill="var(--text-3)">0%</text>'
        f'<text x="{px(50):.1f}" y="{height - 8}" text-anchor="middle" font-size="10"'
        ' fill="var(--text-3)">50%</text>'
        f'<text x="{px(100):.1f}" y="{height - 8}" text-anchor="middle" font-size="10"'
        ' fill="var(--text-3)">100%</text>'
        f"{marker}</svg>"
    )


def _render_quast_section(text: str, contig_stats: dict | None = None) -> str:
    """QUAST 组装质控的可视化渲染（v1.10.25：替代原始 TSV 文本块）。

    数据源是 ``steps.assembly_quast`` 内嵌的 QUAST 汇总指标（pipeline 固定
    ``--no-html``，QUAST 自带的 icarus 可视化不落盘；报告 CSP 禁脚本，故用
    纯 CSS 条形图 + 指标卡），原始文本保留在折叠块供溯源。
    """
    metrics = _quast_metrics(text)
    if not metrics and not (isinstance(contig_stats, dict) and contig_stats):
        return ""
    total = _num(metrics.get("Total length"))
    contigs = _num(metrics.get("# contigs"))
    largest = _num(metrics.get("Largest contig"))
    n50, n90 = _num(metrics.get("N50")), _num(metrics.get("N90"))
    l50, l90 = metrics.get("L50", "—"), metrics.get("L90", "—")
    count_rows = _quast_threshold_rows(metrics, "# contigs")
    len_rows = dict(
        (threshold, _num(value))
        for threshold, _label, value in _quast_threshold_rows(metrics, "Total length")
    )

    hint_1kb = next(
        (f"≥{label[1:].split()[0].replace(',', '')}: {value:g}" for t, label, value in count_rows if t == 1000),
        "",
    )
    items: list[tuple[str, str, str]] = [
        ("总长度", _fmt_bp(metrics.get("Total length")), "组装碱基总量"),
        ("Contigs", f"{contigs:g}", (f"{hint_1kb} " if hint_1kb else "") + "条序列"),
        ("最大 contig", _fmt_bp(largest), f"占总长 {largest / total * 100:.1f}%" if total > 0 else "—"),
        ("N50", _fmt_bp(n50), f"{l50} 条 contig 覆盖 50%"),
        ("N90", _fmt_bp(n90), f"{l90} 条 contig 覆盖 90%"),
        ("auN", _fmt_bp(metrics.get("auN")), "面积加权连续性"),
        ("GC", f"{metrics.get('GC (%)', '—')}%", "鸟嘌呤 + 胞嘧啶占比"),
        ("N's / 100 kbp", metrics.get("# N's per 100 kbp", "—"), "未知碱基密度"),
    ]

    continuity_rows = [
        (label, value, f"{_fmt_bp(value)} · {value / total * 100:.1f}%" if total > 0 else _fmt_bp(value))
        for label, key in (
            ("最大 contig", "Largest contig"), ("auN", "auN"), ("N50", "N50"), ("N90", "N90")
        )
        for value in [_num(metrics.get(key))]
        if value > 0
    ]
    continuity = _quast_bars(continuity_rows, largest)

    max_count = max((value for _t, _l, value in count_rows), default=0)
    profile_rows = []
    for threshold, label, count in count_rows:
        shown = f"{count:g} 条"
        length_at = len_rows.get(threshold)
        if total > 0 and length_at:
            shown += f" · {length_at / total * 100:.1f}% 长度"
        profile_rows.append((label, count, shown))
    profile = _quast_bars(profile_rows, max_count)

    # v1.10.28：逐 contig 分布（seqkit）——长度直方图、Nx 曲线、GC 分布。
    stats = contig_stats if isinstance(contig_stats, dict) else {}
    extra = ""
    length_bins = stats.get("length_bins")
    if isinstance(length_bins, list):
        rows = [
            (
                str(bucket.get("label", "")),
                float(bucket.get("count", 0) or 0),
                f"{int(bucket.get('count', 0) or 0)} 条 · {_fmt_bp(bucket.get('bp'))}",
            )
            for bucket in length_bins
            if isinstance(bucket, dict) and int(bucket.get("count", 0) or 0) > 0
        ]
        if rows:
            extra += (
                '<div class="chart-card"><h3>Contig 长度分布</h3>'
                '<p class="muted" style="margin:0 0 10px;font-size:11px;">'
                "按 contig 长度分箱（seqkit 含 &lt;500 bp，故与 QUAST 的 ≥500 bp 计数略有差异）；数量集中在短箱说明组装碎片化。</p>"
                + _quast_bars(rows, max(row[1] for row in rows))
                + "</div>"
            )
    gc_bins = stats.get("gc_bins")
    if isinstance(gc_bins, list):
        rows = [
            (
                str(bucket.get("label", "")),
                float(bucket.get("count", 0) or 0),
                f"{int(bucket.get('count', 0) or 0)} 条 · {_fmt_bp(bucket.get('bp'))}",
            )
            for bucket in gc_bins
            if isinstance(bucket, dict) and int(bucket.get("count", 0) or 0) > 0
        ]
        if rows:
            extra += (
                '<div class="chart-card"><h3>GC 分布（按 contig）</h3>'
                '<p class="muted" style="margin:0 0 10px;font-size:11px;">'
                "单 contig GC 偏离整体（污染/拼装异常）会在尾部分箱显现。</p>"
                + _quast_bars(rows, max(row[1] for row in rows))
                + "</div>"
            )
    nx = stats.get("nx")
    if isinstance(nx, list) and nx:
        extra += (
            '<div class="chart-card"><h3>Nx 曲线（累计长度）</h3>'
            '<p class="muted" style="margin:0 0 10px;font-size:11px;">'
            "横轴为累计长度百分比，纵轴为该比例下的 contig 长度；曲线越陡、N50 越高越好。</p>"
            + _nx_svg(nx)
            + "</div>"
        )
    top = stats.get("top_contigs")
    if isinstance(top, list) and top:
        top_rows = "".join(
            "<tr><td><code>"
            + html.escape(str(item.get("name", "")))
            + "</code></td><td>"
            + html.escape(_fmt_bp(item.get("length")))
            + "</td><td>"
            + (f"{item.get('gc')}%" if item.get("gc") is not None else "—")
            + "</td></tr>"
            for item in top
            if isinstance(item, dict)
        )
        extra += (
            "<h3>最长 contig</h3>"
            "<table><tr><th>Contig</th><th>长度</th><th>GC</th></tr>"
            + top_rows
            + "</table>"
        )

    return (
        "<h2>组装质控</h2>"
        + _stat_strip(items)
        + '<div class="chart-grid">'
        + '<div class="chart-card"><h3>组装连续性（相对总长度）</h3>'
        + "<p class=\"muted\" style=\"margin:0 0 10px;font-size:11px;\">条越长连续性越好；N50/N90 越接近最大 contig，组装越接近完成图。</p>"
        + continuity
        + "</div>"
        + '<div class="chart-card"><h3>片段化剖面（按长度阈值）</h3>'
        + "<p class=\"muted\" style=\"margin:0 0 10px;font-size:11px;\">各长度阈值下的 contig 数与长度占比；阈值升高时数量骤降说明序列集中在少数长 contig。</p>"
        + profile
        + "</div>"
        + "</div>"
        + '<div class="chart-grid">'
        + extra
        + "</div>"
        + '<details class="gene-details"><summary>原始 QUAST 汇总数据</summary>'
        + f'<pre class="quast">{html.escape(text)}</pre></details>'
    )


def _render_assembly_qc_section(summary: dict, sample_id: str = "") -> str:
    """组装质控（QUAST 汇总 + seqkit 逐 contig）。独立板块，不与注释合并。"""
    steps = summary.get("steps", {})
    quast = steps.get("assembly_quast", "")
    contig_stats = steps.get("assembly_contig_stats", {})
    from bacmap.core.analysis.assembly_qc import is_usable as _assembly_stats_usable
    from bacmap.core.analysis.assembly_qc import load as load_assembly_qc

    if not _assembly_stats_usable(contig_stats) and sample_id:
        # 旧 summary 无逐 contig 统计，或 GC 被误乘 100：只读回退到磁盘重算。
        contig_stats = load_assembly_qc(RESULTS_DIR / sample_id)
    if not quast and not contig_stats:
        return ""
    return _render_quast_section(str(quast), contig_stats)




def _polar(cx: float, cy: float, radius: float, angle_deg: float) -> tuple[float, float]:
    rad = math.radians(angle_deg)
    return cx + radius * math.cos(rad), cy + radius * math.sin(rad)


def _arc_path(cx: float, cy: float, radius: float, a0: float, a1: float) -> str:
    x0, y0 = _polar(cx, cy, radius, a0)
    x1, y1 = _polar(cx, cy, radius, a1)
    large = 1 if (a1 - a0) > 180 else 0
    return f"M {x0:.2f} {y0:.2f} A {radius} {radius} 0 {large} 1 {x1:.2f} {y1:.2f}"


def _render_pai_section(sample_id: str, summary: dict) -> str:
    """VPAI 结构环（纯内联 SVG）：locus 弧 + 基因存在性刻度 + 位点表。

    数据来自 gspec ``vpa_pai_screen.json``（位点/基因坐标位于 PAI 参考序列，
    不是基因组坐标，因此这里表现的是 PAI 内容结构而非染色体位置）。
    """
    path = RESULTS_DIR / sample_id / "gspec" / "vpa_pai_screen.json"
    loci: list[dict] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        files = document.get("files")
        entry = files[0] if isinstance(files, list) and files else {}
        if isinstance(entry, dict) and isinstance(entry.get("loci"), list):
            loci = [locus for locus in entry["loci"] if isinstance(locus, dict)]
    except (OSError, ValueError):
        loci = []
    if not loci:
        return ""

    size = 520
    cx = cy = size / 2
    r_outer = 198
    r_gene = 150
    gap = 3.0
    weights = [max(1, len(locus.get("genes") or [])) for locus in loci]
    total_weight = max(1, sum(weights))
    available = 360.0 - gap * len(loci)
    angle = -90.0
    arcs: list[str] = []
    ticks: list[str] = []
    labels: list[str] = []
    table_rows: list[str] = []
    total_genes = 0
    for locus, weight in zip(loci, weights, strict=True):
        span = available * weight / total_weight
        a0, a1 = angle, angle + span
        angle = a1 + gap
        mid = (a0 + a1) / 2
        coverage = float(locus.get("coverage_pct") or 0)
        identity = float(locus.get("identity_pct") or 0)
        color = "var(--ok)" if coverage >= 95 else "var(--warn)" if coverage >= 80 else "var(--fail)"
        name = str(locus.get("label") or locus.get("locus") or "PAI")
        arcs.append(
            f'<path d="{_arc_path(cx, cy, r_outer, a0, a1)}" fill="none"'
            f' stroke="{color}" stroke-width="12" stroke-linecap="butt">'
            f"<title>{html.escape(name)} · coverage {coverage:.1f}%</title></path>"
        )
        genes = [g for g in (locus.get("genes") or []) if isinstance(g, dict)]
        total_genes += len(genes)
        for index, gene in enumerate(genes):
            ga = a0 + ((index + 0.5) / max(1, len(genes))) * span
            x1, y1 = _polar(cx, cy, r_gene, ga)
            x2, y2 = _polar(cx, cy, r_gene - 17, ga)
            verdict = str(gene.get("verdict") or "absent")
            tick_color = {
                "present": "var(--ok)",
                "partial": "var(--warn)",
            }.get(verdict, "var(--fail)")
            ticks.append(
                f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"'
                f' stroke="{tick_color}" stroke-width="2.2" stroke-linecap="round">'
                f"<title>{html.escape(str(gene.get('gene_id', '')))} · {verdict}</title></line>"
            )
        lx, ly = _polar(cx, cy, r_outer + 26, mid)
        labels.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle"'
            ' font-size="11" fill="var(--text-2)">'
            f"{html.escape(name)}</text>"
        )
        present = sum(1 for gene in genes if gene.get("verdict") == "present")
        partial = sum(1 for gene in genes if gene.get("verdict") == "partial")
        missing = max(0, len(genes) - present - partial)
        table_rows.append(
            "<tr>"
            f"<td><strong>{html.escape(name)}</strong></td>"
            f'<td class="mono">{coverage:.1f}%</td>'
            f'<td class="mono">{identity:.1f}%</td>'
            f'<td class="mono">{len(genes)}</td>'
            f'<td class="mono">{present}</td>'
            f'<td class="mono">{partial}</td>'
            f'<td class="mono">{missing}</td>'
            "</tr>"
        )

    svg = (
        f'<svg class="pai-circos" viewBox="0 0 {size} {size}" role="img"'
        f' aria-label="VPAI 位点结构环（{len(loci)} 个位点，{total_genes} 个基因）"'
        ' style="width:100%;max-width:560px;height:auto;display:block;margin:0 auto">'
        f'{"".join(arcs)}{"".join(ticks)}{"".join(labels)}'
        f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="20"'
        ' font-weight="600" fill="var(--text-1)">VPAI</text>'
        f'<text x="{cx}" y="{cy + 18}" text-anchor="middle" font-size="11"'
        f' fill="var(--text-3)">{len(loci)} 个位点 · {total_genes} 个基因</text>'
        "</svg>"
    )
    return (
        "<h2>PAI 结构（VPAI）</h2>"
        '<p class="muted" style="margin:0 0 10px;font-size:11px;">'
        "外环为 PAI 位点（颜色=覆盖率），内圈刻度为基因存在性；弧长按基因数，"
        "不代表染色体坐标。</p>"
        + svg
        + '<div class="pai-legend">'
        '<span><i style="background:var(--ok)"></i>present</span>'
        '<span><i style="background:var(--warn)"></i>partial</span>'
        '<span><i style="background:var(--fail)"></i>absent</span>'
        "</div>"
        + "<h3>PAI 位点</h3>"
        + "<table><tr><th>Locus</th><th>Coverage</th><th>Identity</th>"
        "<th>Genes</th><th>Present</th><th>Partial</th><th>Missing</th></tr>"
        + "".join(table_rows)
        + "</table>"
    )


def _render_report_nav(sample_id: str, items: list[tuple[str, str]]) -> str:
    links = "".join(
        f'<a href="#{html.escape(anchor)}">{html.escape(label)}</a>'
        for anchor, label in items
    )
    return (
        '<aside class="report-nav" aria-label="报告目录">'
        '<div class="report-nav__brand">bacmap <span>report</span></div>'
        f'<div class="report-nav__sample mono">{html.escape(sample_id)}</div>'
        f'<nav class="report-nav__links">{links}</nav>'
        f'<a class="report-nav__back" href="/console/samples/{html.escape(sample_id)}">'
        "← 返回控制台</a>"
        "</aside>"
    )


def _render_annotation_section(summary: dict) -> str:
    """基因组注释（Bakta / eggNOG-mapper）。独立板块。"""
    steps = summary.get("steps", {})
    ann = steps.get("annotation", {})
    if not (isinstance(ann, dict) and ann):
        return ""

    status = ann.get("status", "ok")
    rate_raw = float(ann.get("annotation_rate", 0) or 0)
    rate_pct = rate_raw * 100 if rate_raw <= 1 else rate_raw
    parts: list[str] = ["<h2>基因组注释</h2>"]
    parts.append(
        "<table>"
        + _row("注释状态", status)
        + _row("CDS 总数", ann.get("total_CDS", "—"))
        + _row("已注释 CDS", ann.get("annotated_CDS", "—"))
        + _row("注释率", f"{rate_pct:.1f}%")
        + "</table>"
    )
    bakta = ann.get("bakta", {})
    if isinstance(bakta, dict) and bakta:
        rows = "".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
            for k, v in bakta.items()
        )
        parts.append(f"<h3>Bakta 特征计数</h3><table><tr><th>类型</th><th>数量</th></tr>{rows}</table>")
        parts.append(
            '<div class="chart-card"><h3>Bakta 特征分布</h3>'
            + _bar_chart([(str(k), _num(v)) for k, v in bakta.items()])
            + "</div>"
        )
    egg = ann.get("eggnog", {})
    if isinstance(egg, dict) and egg:
        cog = egg.get("cog_category_counts", {})
        cog_text = ", ".join(f"{k}:{v}" for k, v in cog.items()) if isinstance(cog, dict) else "—"
        cog_bars = (
            _bar_chart([(str(k), _num(v)) for k, v in cog.items()])
            if isinstance(cog, dict)
            else ""
        )
        parts.append(
            "<table>"
            + _row("eggNOG 查询", egg.get("queries", "—"))
            + _row("eggNOG 已注释", egg.get("annotated", "—"))
            + _row("COG 分类", cog_text or "—")
            + _row("GO terms", egg.get("go_term_count", "—"))
            + _row("KEGG KO", egg.get("kegg_ko_count", "—"))
            + _row("KEGG Pathway", egg.get("kegg_pathway_count", "—"))
            + _row("CAZy", egg.get("cazy_count", "—"))
            + _row("Pfam", egg.get("pfam_count", "—"))
            + "</table>"
        )
        if cog_bars:
            parts.append('<div class="chart-card"><h3>COG 功能分类</h3>' + cog_bars + "</div>")
    top = ann.get("top_genes", [])
    if isinstance(top, list) and top:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(g.get('gene', '')))}</td>"
            f"<td>{html.escape(str(g.get('product', '')))}</td>"
            f"<td>{html.escape(str(g.get('source', '')))}</td>"
            "</tr>"
            for g in top
            if isinstance(g, dict)
        )
        parts.append(
            "<h3>重点基因（前 20）</h3>"
            "<table><tr><th>基因</th><th>产物</th><th>来源</th></tr>"
            f"{rows}</table>"
        )
    return "\n".join(parts)


def generate_html(sample_id: str, summary: dict, verification, output_path: Path):
    steps = summary.get("steps", {})

    # gside 版 summary 用 "species" 键（_extract_species 双键兼容旧 fixtures 的 verdict）。
    verdict = _extract_species(summary) or "N/A"
    species_display = verdict.replace("_", " ") if verdict else "N/A"
    species_confirmed = bool(verdict) and verdict != "N/A" and not verdict.startswith("not_")

    mlst_info = parse_mlst(steps.get("mlst", ""))
    st = mlst_info.get("st", "N/A")
    alleles = mlst_info.get("alleles", {})

    sero = steps.get("serotype", {})
    if isinstance(sero, dict):
        serovar = str(sero.get("value") or sero.get("sistr") or "N/A")
    else:
        serovar = "N/A"
    serogroup = sero.get("serogroup", "") if isinstance(sero, dict) else ""
    o_antigen = sero.get("o_antigen", "") if isinstance(sero, dict) else ""
    h1 = sero.get("h1", "") if isinstance(sero, dict) else ""
    h2 = sero.get("h2", "") if isinstance(sero, dict) else ""

    # 抗原式按物种：沙门菌 O:H1:H2、副溶血弧菌 O:K（OL/KL 位点）、大肠 O:H；
    # 无抗原分型的物种（李斯特血清群、志贺血清型等）不展示这一行。
    sample_dir = RESULTS_DIR / sample_id

    def _meaningful(value: str) -> bool:
        return str(value or "").strip() not in {"", "N/A", "n/a", "-", "None", "none"}

    def _phase(value: str) -> str:
        # H 相里的 "-" 是合法的单相标记（如 1,4,[5],12:i:-）
        text = str(value or "").strip()
        return "" if text in {"", "N/A", "n/a", "None", "none"} else text

    antigen_label = "抗原式"
    antigen_value = str(sero.get("antigen_formula") or "") if isinstance(sero, dict) else ""
    antigen_kind = str(sero.get("antigen_kind") or "") if isinstance(sero, dict) else ""
    if _meaningful(antigen_value):
        antigen_label = {
            "O:K": "抗原式（O:K）",
            "O:H1:H2": "抗原式（O:H1:H2）",
            "O:H": "抗原式（O:H）",
        }.get(antigen_kind, "抗原式")
    else:
        antigen_value = ""
        vpa_sero = steps.get("vpa_serotype")
        if isinstance(vpa_sero, dict) and _meaningful(
            str(vpa_sero.get("predicted_serotype") or "")
        ):
            # 旧 summary（v1.10.28 前）没有位点 ID：先从原始 gspec screen 取
            # OL/KL 位点，取不到再退回 O10:K4 表型。
            antigen_label = "抗原式（O:K）"
            antigen_value = (
                _vpa_formula_from_screen(sample_dir)
                or str(vpa_sero["predicted_serotype"])
            )
            if not _meaningful(serovar):
                # 更旧的 summary 连 steps.serotype.value 都还是 N/A。
                serovar = str(vpa_sero["predicted_serotype"])
        elif "Salmonella" in verdict:
            parts = [str(p) for p in (o_antigen, h1, h2) if _meaningful(str(p))]
            if len(parts) == 3:
                antigen_label = "抗原式（O:H1:H2）"
                antigen_value = ":".join(parts)
        else:
            dec = steps.get("dec") if isinstance(steps.get("dec"), dict) else {}
            ecoh_raw = dec.get("ecoh_serotype") if isinstance(dec, dict) else None
            ecoh = ecoh_raw if isinstance(ecoh_raw, dict) else {}
            o_type = str(ecoh.get("o_type") or "")
            h_type = str(ecoh.get("h_type") or "")
            if _meaningful(o_type) and _meaningful(h_type):
                antigen_label = "抗原式（O:H）"
                antigen_value = f"{o_type}:{h_type}"
    antigen_row = _row(antigen_label, antigen_value) if antigen_value else ""
    serogroup_row = _row("血清群", serogroup) if _meaningful(str(serogroup or "")) else ""

    # v1.10.19：gspec screen 结果 JSON 优先（gspec/<kind>.json），
    # 旧运行目录回退 TSV 布局（amr/abricate_<kind>.tsv）。
    from bacmap.core.utils import load_screen_hits

    card_genes = load_screen_hits(sample_dir, "card")
    vfdb_genes = load_screen_hits(sample_dir, "vfdb")
    plasmid_genes = load_screen_hits(sample_dir, "plasmidfinder")

    asm_stats = steps.get("assembly", "")
    asm_parts = asm_stats.strip().split("\n")[-1].split("\t") if asm_stats else []
    # stats 输出列：#file(0) format(1) type(2) num_seqs(3) sum_len(4) …
    num_contigs = asm_parts[3] if len(asm_parts) > 3 else "?"
    total_len = asm_parts[4] if len(asm_parts) > 4 else "?"

    v_review = '<span class="warn">需要人工审核</span>' if verification.needs_human_review else ""

    check_rows = "".join(
        f'<tr><td>{c.name}</td><td class="{"ok" if c.passed else "fail"}">'
        f"{'PASS' if c.passed else 'FAIL'} · {c.message}</td></tr>"
        for c in verification.checks
    )

    # parse_mlst 会把 gmlst TSV 的元列（file/scheme）一并放进 alleles —— 展示前剔除。
    mlst_alleles = {k: v for k, v in alleles.items() if k not in ("file", "scheme")}
    allele_str = (
        " ".join(f"{k}={v}" for k, v in mlst_alleles.items()) if mlst_alleles else "N/A"
    )

    cgmlst_section = _render_cgmlst_section(sample_id, summary)
    assembly_section = _render_assembly_qc_section(summary, sample_id)
    annotation_section = _render_annotation_section(summary)
    amr_section = _render_amr_section(card_genes)
    vf_section = _render_vf_section(vfdb_genes)
    plasmid_section = _render_plasmid_section(plasmid_genes)
    pai_section = _render_pai_section(sample_id, summary)
    ann_meta = steps.get("annotation") if isinstance(steps.get("annotation"), dict) else {}
    ann_status = str(ann_meta.get("status") or "未运行") if ann_meta else "未运行"
    summary_strip = _stat_strip(
        [
            ("AMR", str(len(card_genes)), "CARD 耐药基因"),
            ("VFDB", str(len(vfdb_genes)), "毒力基因"),
            ("PLASMID", str(len(plasmid_genes)), "复制子"),
            ("ANNOTATION", ann_status, "Bakta / eggNOG"),
        ]
    )

    assembly_block = (
        f'<section class="card" id="assembly">{assembly_section}</section>'
        if assembly_section
        else ""
    )
    annotation_block = (
        f'<section class="card" id="annotation">{annotation_section}</section>'
        if annotation_section
        else ""
    )
    nli_section = _render_nli_section(sample_id)
    nli_block = (
        f'<section class="card" id="interpretation">{nli_section}</section>'
        if nli_section
        else ""
    )
    cgmlst_block = (
        f'<section class="card" id="cgmlst">{cgmlst_section}</section>'
        if cgmlst_section
        else ""
    )
    pai_block = (
        f'<section class="card" id="pai">{pai_section}</section>' if pai_section else ""
    )
    toc_items: list[tuple[str, str]] = [
        ("basic", "基本信息"),
        ("verifier", "Verifier 校验"),
    ]
    if assembly_section:
        toc_items.append(("assembly", "组装质控"))
    if annotation_section:
        toc_items.append(("annotation", "基因组注释"))
    if amr_section:
        toc_items.append(("amr", "耐药基因"))
    if vf_section:
        toc_items.append(("virulence", "毒力基因"))
    if plasmid_section:
        toc_items.append(("plasmid", "质粒"))
    if pai_section:
        toc_items.append(("pai", "PAI 结构"))
    if cgmlst_section:
        toc_items.append(("cgmlst", "cgMLST"))
    if nli_section:
        toc_items.append(("interpretation", "AI 解读"))
    toc_items.append(("evidence", "证据链"))
    report_nav = _render_report_nav(sample_id, toc_items)
    toc_links = "".join(
        f'<a href="#{anchor}">{label}</a>' for anchor, label in toc_items
    )
    status_label = (
        "ALL PASSED"
        if verification.passed
        else f"{verification.failed_count} FAILED"
    )
    status_class = "badge--ok" if verification.passed else "badge--fail"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="bacmap-report" content="12">
<title>{sample_id} · 分析报告 · bacmap</title>
<style>
  :root {{
    --bg: #08090a;
    --panel: #0f1011;
    --surface: #191a1b;
    --text-1: #f7f8f8;
    --text-2: #d0d6e0;
    --text-3: #8a8f98;
    --text-4: #62666d;
    --accent: #5e6ad2;
    --link: #828fff;
    --border: rgba(255, 255, 255, 0.08);
    --border-subtle: rgba(255, 255, 255, 0.05);
    --code-bg: rgba(0, 0, 0, 0.24);
    --ok: #5ad191;
    --fail: #ff8589;
    --warn: #eccf7a;
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", Roboto, sans-serif;
    --font-mono: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas,
      "Noto Sans Mono CJK SC", monospace;
  }}
  :root[data-report-theme="light"] {{
    --bg: #f9fafb;
    --panel: #f2f4f7;
    --surface: #ffffff;
    --text-1: #101828;
    --text-2: #344054;
    --text-3: #475467;
    --text-4: #667085;
    --accent: #5e6ad2;
    --link: #4655c4;
    --border: #e4e7ec;
    --border-subtle: #eef0f3;
    --code-bg: #f2f4f7;
    --ok: #027a48;
    --fail: #b42318;
    --warn: #b54708;
  }}
  :root[data-report-theme="gray"] {{
    --bg: #deded8;
    --panel: #f1f1eb;
    --surface: #f7f7f2;
    --text-1: #0a0a0a;
    --text-2: #1c1c1a;
    --text-3: #3f3f3b;
    --text-4: #5a5a54;
    --accent: #111111;
    --link: #1a1a1a;
    --border: #111111;
    --border-subtle: rgba(10, 10, 10, 0.16);
    --code-bg: #e4e4dd;
    --ok: #1f5c3a;
    --fail: #a11b1b;
    --warn: #7a4a00;
  }}
  * {{ box-sizing: border-box; }}
  html {{ color-scheme: dark; }}
  html[data-report-theme="light"] {{ color-scheme: light; }}
  html[data-report-theme="gray"] {{ color-scheme: light; }}
  body {{
    margin: 0;
    min-height: 100dvh;
    background: var(--bg);
    background-image: radial-gradient(60% 240px at 50% 0, rgba(94, 106, 210, 0.1), transparent 70%);
    background-repeat: no-repeat;
    color: var(--text-2);
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.7;
    -webkit-font-smoothing: antialiased;
  }}
  html[data-report-theme="light"] body {{
    background-image: radial-gradient(60% 240px at 50% 0, rgba(94, 106, 210, 0.06), transparent 70%);
  }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; text-underline-offset: 3px; }}
  code, pre {{
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--code-bg);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
  }}
  code {{ padding: 1px 5px; }}
  pre {{ padding: 12px; overflow-x: auto; white-space: pre-wrap; overflow-wrap: anywhere; }}
  .page {{ width: 100%; max-width: none; margin: 0; padding: 0 0 48px; }}
  .report-layout {{ display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 24px; max-width: 1440px; margin: 0 auto; padding: 24px; }}
  .report-nav {{ position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow: auto; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); }}
  .report-nav__brand {{ color: var(--text-1); font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }}
  .report-nav__brand span {{ color: var(--text-3); font-size: 10px; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; }}
  .report-nav__sample {{ margin: 4px 0 12px; color: var(--text-3); font-size: 11px; overflow-wrap: anywhere; }}
  .report-nav__links a {{ display: block; padding: 5px 8px; border-left: 2px solid transparent; color: var(--text-3); font-size: 12px; }}
  .report-nav__links a:hover {{ background: var(--code-bg); color: var(--text-1); text-decoration: none; }}
  .report-nav__back {{ display: block; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border-subtle); color: var(--link); font-size: 12px; }}
  .report-toc {{ display: none; }}
  section[id] {{ scroll-margin-top: 18px; }}
  .pagehead__actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
  .pagehead__actions a {{ display: inline-flex; align-items: center; height: 28px; padding: 0 10px; border: 1px solid var(--border); border-radius: 6px; color: var(--text-2); font-size: 11.5px; }}
  .pagehead__actions a:hover {{ border-color: var(--text-3); color: var(--text-1); text-decoration: none; }}
  .pai-legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 4px; color: var(--text-3); font-size: 11px; }}
  .pai-legend i {{ display: inline-block; width: 9px; height: 9px; margin-right: 5px; border-radius: 2px; vertical-align: middle; }}
  .pagehead {{ margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }}
  .eyebrow {{ color: var(--link); font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }}
  h1 {{ margin: 8px 0 6px; color: var(--text-1); font-size: 28px; font-weight: 650; letter-spacing: -0.01em; line-height: 1.2; }}
  .meta {{ color: var(--text-3); font-size: 12.5px; }}
  .meta .mono {{ color: var(--text-2); }}
  .badge {{
    display: inline-flex; align-items: center; gap: 6px;
    height: 24px; padding: 0 10px; margin-top: 12px;
    border: 1px solid transparent; border-radius: 999px;
    font-size: 11.5px; font-weight: 600;
  }}
  .badge::before {{ content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}
  .badge--ok {{ color: var(--ok); background: rgba(47, 190, 119, 0.12); border-color: rgba(47, 190, 119, 0.3); }}
  .badge--fail {{ color: var(--fail); background: rgba(229, 72, 77, 0.12); border-color: rgba(229, 72, 77, 0.3); }}
  .card {{
    margin-bottom: 18px; padding: 22px 24px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  }}
  .card h2 {{
    margin: 0 0 14px; padding-bottom: 10px;
    color: var(--text-1); font-size: 16px; font-weight: 600;
    border-bottom: 1px solid var(--border-subtle);
  }}
  .card h3 {{ margin: 18px 0 8px; color: var(--text-1); font-size: 13.5px; font-weight: 600; }}
  .card h3:first-child {{ margin-top: 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 4px 0 6px; }}
  th {{
    padding: 8px 10px; border-bottom: 1px solid var(--border-subtle);
    color: var(--text-3); font-size: 11px; font-weight: 600;
    letter-spacing: 0.05em; text-align: left; text-transform: uppercase;
  }}
  td {{ padding: 9px 10px; border-bottom: 1px solid var(--border-subtle); color: var(--text-2); font-size: 13px; vertical-align: top; }}
  tr:last-child td {{ border-bottom: 0; }}
  td.label {{ width: 220px; color: var(--text-3); font-weight: 500; }}
  .ok {{ color: var(--ok); }}
  .fail {{ color: var(--fail); }}
  .warn {{ color: var(--warn); font-weight: 600; }}
  .muted {{ color: var(--text-3); }}
  .mono {{ font-family: var(--font-mono); font-variant-numeric: tabular-nums; }}
  .evidence {{ background: var(--panel); border-color: var(--border-subtle); }}
  .evidence p {{ margin: 5px 0; color: var(--text-3); font-size: 12px; overflow-wrap: anywhere; }}
  .evidence strong {{ color: var(--text-2); }}
  .quast {{ max-height: 320px; }}
  .cgmlst-verdict-badge {{
    display: inline-block; margin: 6px 0; padding: 5px 12px;
    border-radius: 999px; font-size: 12px; font-weight: 600;
  }}
  .cgmlst-verdict-outbreak {{ background: rgba(229, 72, 77, 0.12); color: var(--fail); }}
  .cgmlst-verdict-related {{ background: rgba(232, 182, 74, 0.12); color: var(--warn); }}
  .cgmlst-verdict-unrelated {{ background: rgba(47, 190, 119, 0.12); color: var(--ok); }}
  .cgmlst-verdict-undetermined {{ background: rgba(138, 143, 152, 0.12); color: var(--text-3); }}
  .cgmlst-nearest td.dist {{ text-align: right; font-family: var(--font-mono); }}
  .cgmlst-caveats {{
    margin: 8px 0; padding: 10px 12px;
    background: rgba(232, 182, 74, 0.08); border-left: 3px solid var(--warn);
    border-radius: 0 6px 6px 0; color: var(--warn); font-size: 12px;
  }}
  .cgmlst-caveats ul {{ margin: 4px 0 0; }}
  .stat-strip {{
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
    margin-bottom: 18px; overflow: hidden;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  }}
  .stat-strip__item {{ padding: 14px 16px; border-right: 1px solid var(--border-subtle); }}
  .stat-strip__item:last-child {{ border-right: 0; }}
  .stat-strip__label {{ display: block; color: var(--text-3); font: 10px/1.4 var(--font-mono); letter-spacing: .08em; text-transform: uppercase; }}
  .stat-strip__value {{ display: block; margin-top: 4px; color: var(--text-1); font: 700 26px/1 var(--font-sans); letter-spacing: -.03em; }}
  .stat-strip__hint {{ display: block; margin-top: 5px; color: var(--text-3); font-size: 11px; }}
  .chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin: 10px 0 16px; }}
  .chart-card {{ padding: 14px 16px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface); }}
  .chart-card h3 {{ margin: 0 0 10px; }}
  .bars {{ display: grid; gap: 7px; }}
  .bar-row {{ display: grid; grid-template-columns: minmax(86px, 150px) minmax(0, 1fr) 52px; align-items: center; gap: 9px; font-size: 11px; }}
  .quast-bars .bar-row {{ grid-template-columns: 104px minmax(0, 1fr) 118px; }}
  .quast-bar-value {{ white-space: nowrap; }}
  .bar-label {{ overflow: hidden; color: var(--text-2); text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ height: 7px; overflow: hidden; border-radius: 999px; background: var(--code-bg); }}
  .bar-fill {{ display: block; height: 100%; border-radius: inherit; background: var(--accent); }}
  .bar-value {{ color: var(--text-3); text-align: right; }}
  .gene-details {{ margin: 10px 0 4px; padding-top: 8px; border-top: 1px solid var(--border-subtle); }}
  .gene-details summary {{ cursor: pointer; color: var(--link); font-size: 12px; }}
  .ai-text p {{ margin: 8px 0; white-space: pre-line; }}
  @media (max-width: 720px) {{
    .page {{ padding: 24px 14px 40px; }}
    h1 {{ font-size: 22px; }}
    .card {{ padding: 16px; }}
    td.label {{ width: 130px; }}
    .stat-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .stat-strip__item:nth-child(2) {{ border-right: 0; }}
    .chart-grid {{ grid-template-columns: 1fr; }}
  }}
  html[data-report-theme="gray"] body {{
    background-image:
      linear-gradient(to right, rgba(10, 10, 10, 0.055) 1px, transparent 1px),
      linear-gradient(to bottom, rgba(10, 10, 10, 0.055) 1px, transparent 1px);
    background-size: 48px 48px;
  }}
  html[data-report-theme="gray"] .pagehead {{ border-top: 4px solid #111; padding-top: 18px; }}
  html[data-report-theme="gray"] h1 {{
    text-transform: uppercase;
    letter-spacing: -0.055em;
    font-weight: 800;
  }}
  html[data-report-theme="gray"] .card {{
    border-radius: 0;
    box-shadow: 3px 3px 0 rgba(10, 10, 10, 0.13);
  }}
  html[data-report-theme="gray"] .badge,
  html[data-report-theme="gray"] .cgmlst-verdict-badge {{ border-radius: 0; }}
  html[data-report-theme="gray"] th {{
    color: #111;
    border-bottom: 1px solid #111;
    letter-spacing: 0.1em;
  }}
  html[data-report-theme="gray"] td.label {{ color: #3f3f3b; }}
  html[data-report-theme="gray"] .stat-strip,
  html[data-report-theme="gray"] .chart-card {{ border-radius: 0; }}
  html[data-report-theme="gray"] .stat-strip {{ border-color: #111; }}
  html[data-report-theme="gray"] .stat-strip__item {{ border-color: rgba(10,10,10,.16); }}
  html[data-report-theme="gray"] .stat-strip__value {{ text-transform: uppercase; }}
  html[data-report-theme="gray"] .chart-card {{ border-color: rgba(10,10,10,.22); }}
  html[data-report-theme="gray"] .bar-track {{ border-radius: 0; background: #c9c9c2; }}
  html[data-report-theme="gray"] .bar-fill {{ border-radius: 0; background: #111; }}
  @media (max-width: 1000px) {{
    .report-layout {{ display: block; padding: 12px; }}
    .report-nav {{ display: none; }}
    .report-toc {{ display: block; position: sticky; top: 0; z-index: 5; margin-bottom: 12px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); }}
    .report-toc summary {{ cursor: pointer; color: var(--text-2); font-size: 12px; }}
    .report-toc .report-nav__links {{ margin-top: 6px; }}
  }}
  @media print {{
    body {{ background: #fff; color: #222; }}
    .report-layout {{ display: block; padding: 0; }}
    .report-nav, .report-toc {{ display: none; }}
    .card {{ background: #fff; border-color: #ddd; box-shadow: none; break-inside: avoid; }}
    .card h2, h1, h3 {{ color: #111; }}
    th {{ color: #555; }}
    td {{ color: #222; }}
    .badge {{ color: #111; border-color: #999; background: #f3f3f3; }}
  }}
</style>
</head>
<body>
<div class="report-layout">
{report_nav}
<main class="page" id="top">
  <details class="report-toc">
    <summary>目录 / TOC</summary>
    <nav class="report-nav__links">{toc_links}</nav>
  </details>
  <header class="pagehead">
    <div class="eyebrow">bacmap · 全基因组分析报告</div>
    <h1>{sample_id}</h1>
    <div class="meta">
      生成时间 <span class="mono">{datetime.now().strftime("%Y-%m-%d %H:%M")}</span>
      · 物种 <span class="mono">{species_display}</span>
      · MLST <span class="mono">{st}</span>
    </div>
    <span class="badge {status_class}">Verifier: {status_label}</span>
    {v_review}
    <div class="pagehead__actions">
      <a href="?download=1">下载 HTML</a>
      <a href="/console/samples/{sample_id}">返回控制台</a>
    </div>
  </header>

  {summary_strip}

  <section class="card" id="basic">
    <h2>基本信息</h2>
    <table>
      {_row("样本编号", sample_id)}
      {_row("物种判定", species_display, species_confirmed)}
      {_row("MLST ST", st)}
      {_row("MLST Alleles", allele_str)}
      {_row("血清型", serovar)}
      {serogroup_row}
      {antigen_row}
      {_row("Contigs 数", num_contigs)}
      {_row("组装总长度", f"{total_len} bp")}
    </table>
  </section>

  <section class="card" id="verifier">
    <h2>Deterministic Verifier 校验</h2>
    <table>
      <tr><th>检查项</th><th>结果</th></tr>
      {check_rows}
    </table>
  </section>

  {assembly_block}
  {annotation_block}
  {nli_block}

  <section class="card" id="amr">
    {amr_section}
  </section>

  <section class="card" id="virulence">
    {vf_section}
  </section>

  <section class="card" id="plasmid">
    {plasmid_section}
  </section>

  {pai_block}
  {cgmlst_block}

  <section class="card evidence" id="evidence">
    <h2>三元证据链</h2>
    <p><strong>strain_id:</strong> <span class="mono">{sample_id}</span></p>
    <p><strong>pipeline_version:</strong> <span class="mono">{summary.get("pipeline_version", "salmonella-workflow-v0.1")}</span></p>
    <p><strong>tool_versions:</strong> fastp, Shovill 1.1.0, blastn 2.17.0+, gspec, gmlst, Bakta 1.12, eggNOG-mapper, QUAST, AMRFinderPlus 4.2.7</p>
    <p><strong>database_versions:</strong> CARD, VFDB, PlasmidFinder, PubMLST salmonella_2</p>
  </section>
</main>
</div>
</body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 原子替换：Web 首次访问会原地重渲染旧报告，避免读到半写的 HTML。
    tmp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(html, encoding="utf-8")
    tmp_path.replace(output_path)


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
                proc = subprocess.run(
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
        "--results-dir",
        type=str,
        default=None,
        help="本次运行的物理结果目录（run 级隔离；默认 BACMAP_HOME/results）",
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

    global RESULTS_DIR
    if args.results_dir:
        RESULTS_DIR = Path(args.results_dir).resolve()

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
