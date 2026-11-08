"""P1 展示层：确定性 SVG + Markdown 报告/论文草案。

所有 builtin renderer 只消费 ``FigureSpec``（数据、统计量、来源 ID 全部来自契约），
绝不回读数据库或接受外部数字；这保证渲染可从 spec 完全复现。
"""

from __future__ import annotations

import math
from html import escape

from bacmap.research.figures import FigureSpec, build_association_spec
from bacmap.research.models import AnalysisSession, StatResult


def _fmt(value: float | None, digits: int = 3) -> str:
    return "NA" if value is None else f"{value:.{digits}g}"


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "NA"
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def _fmt_num(value: float | None) -> str:
    """Publication-friendly numbers: never scientific notation, never a bare "0"
    for a small nonzero estimate."""
    if value is None:
        return "NA"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return f"{value:.0f}"
    if magnitude >= 0.01 or magnitude == 0:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if magnitude >= 0.0001:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return "<0.0001" if value > 0 else ">-0.0001"


def _svg_header(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
    ]


def _render_association_svg(spec: FigureSpec) -> str:
    """2×2 关联的水平条形图（无外部依赖，可离线打开）。"""
    data = spec.data
    table: dict[str, int] = dict(data.get("table", {}))
    rows = [
        ("gene+ / resistant", table.get("gene_pos_resistant", 0), "#c44e52"),
        ("gene+ / susceptible", table.get("gene_pos_susceptible", 0), "#dd8452"),
        ("gene- / resistant", table.get("gene_neg_resistant", 0), "#4c72b0"),
        ("gene- / susceptible", table.get("gene_neg_susceptible", 0), "#55a868"),
    ]
    total = max(1, sum(v for _, v, _ in rows))
    width, left, bar_h, gap, top = 760, 210, 38, 32, 80
    height = top + len(rows) * (bar_h + gap) + 50
    parts = _svg_header(width, height)
    parts.append(
        f'<text x="24" y="34" font-family="system-ui,sans-serif" font-size="18" '
        f'font-weight="600">{escape(spec.title)}</text>'
    )
    parts.append(
        '<text x="24" y="56" font-family="system-ui,sans-serif" font-size="12" fill="#666">'
        f'run {escape(spec.source.run_id)} · n={data.get("n", 0)} · '
        f'{escape(str(data.get("label", "")))}</text>'
    )
    max_w = width - left - 40
    for i, (label, value, color) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(2, int(max_w * value / total))
        parts.append(
            f'<text x="24" y="{y + 24}" font-family="system-ui,sans-serif" font-size="13">'
            f"{escape(label)}</text>"
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{w}" height="{bar_h}" rx="3" fill="{color}"/>'
        )
        parts.append(
            f'<text x="{left + w + 10}" y="{y + 24}" font-family="system-ui,sans-serif" '
            f'font-size="13" fill="#333">{value}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_figure_svg(session: AnalysisSession, stat: StatResult) -> str:
    """兼容入口（session + stat）：构造 P1 spec 后渲染；新代码走 spec 版入口。"""
    return _render_association_svg(build_association_spec(session, stat))


def render_association_svg(spec: FigureSpec) -> str:
    """Builtin renderer for ``association_bar``; consumes the spec only."""
    return _render_association_svg(spec)


_TICKS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0,
          100.0, 200.0, 500.0, 1000.0)


def render_forest_svg(spec: FigureSpec) -> str:
    """Builtin renderer for ``forest``: effect estimates with 95% CI on a log axis."""
    effects: list[dict] = list(spec.data.get("effects") or [])
    width = 760
    label_x, plot_l, plot_r = 200, 230, 540
    stat_x, p_x = 556, 690
    row_h, top = 36, 96
    height = top + max(1, len(effects)) * row_h + 64

    values: list[float] = []
    for effect in effects:
        for key in ("odds_ratio", "ci_low", "ci_high"):
            value = effect.get(key)
            if isinstance(value, (int, float)) and value > 0:
                values.append(float(value))
    if values:
        xmin = min(min(values), 1.0) / 1.15
        xmax = max(max(values), 1.0) * 1.15
    else:  # no positive estimate; keep a readable axis around the no-effect line
        xmin, xmax = 0.5, 2.0
    span = math.log(xmax) - math.log(xmin)

    def x_of(value: float) -> float:
        if span <= 0:
            return (plot_l + plot_r) / 2
        return plot_l + (math.log(value) - math.log(xmin)) / span * (plot_r - plot_l)

    ticks = [t for t in _TICKS if xmin <= t <= xmax]
    if len(ticks) < 2:
        ticks = [t for t in (xmin, 1.0, xmax) if xmin <= t <= xmax]

    parts = _svg_header(width, height)
    parts.append(
        f'<text x="24" y="34" font-family="system-ui,sans-serif" font-size="18" '
        f'font-weight="600">{escape(spec.title)}</text>'
    )
    parts.append(
        '<text x="24" y="56" font-family="system-ui,sans-serif" font-size="12" fill="#666">'
        f'run {escape(spec.source.run_id)} · n={spec.data.get("n", 0)} · '
        f'log scale · no-effect line at OR = 1</text>'
    )
    parts.append(
        f'<text x="{label_x}" y="{top - 14}" text-anchor="end" '
        f'font-family="system-ui,sans-serif" font-size="11" fill="#666">Comparison</text>'
    )
    parts.append(
        f'<text x="{stat_x}" y="{top - 14}" font-family="system-ui,sans-serif" '
        f'font-size="11" fill="#666">OR (95% CI)</text>'
    )
    parts.append(
        f'<text x="{p_x}" y="{top - 14}" font-family="system-ui,sans-serif" '
        f'font-size="11" fill="#666">p</text>'
    )

    axis_y = top + max(1, len(effects)) * row_h + 8
    for i, effect in enumerate(effects):
        y = top + i * row_h + row_h / 2
        label = str(effect.get("label", f"effect {i + 1}"))
        odds_ratio = effect.get("odds_ratio")
        ci_low = effect.get("ci_low")
        ci_high = effect.get("ci_high")
        p_value = effect.get("p_value")
        parts.append(
            f'<text x="{label_x}" y="{y + 4}" text-anchor="end" '
            f'font-family="system-ui,sans-serif" font-size="12">{escape(label)}</text>'
        )
        if isinstance(ci_low, (int, float)) and isinstance(ci_high, (int, float)) \
                and 0 < ci_low <= ci_high:
            x1, x2 = x_of(float(ci_low)), x_of(float(ci_high))
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" '
                f'stroke="#333333" stroke-width="1.5"/>'
            )
            for x in (x1, x2):
                parts.append(
                    f'<line x1="{x:.1f}" y1="{y - 5:.1f}" x2="{x:.1f}" y2="{y + 5:.1f}" '
                    f'stroke="#333333" stroke-width="1.5"/>'
                )
        if isinstance(odds_ratio, (int, float)) and odds_ratio > 0:
            cx = x_of(float(odds_ratio))
            parts.append(
                f'<rect x="{cx - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" '
                f'fill="#4c72b0"/>'
            )
        parts.append(
            f'<text x="{stat_x}" y="{y + 4}" font-family="system-ui,sans-serif" '
            f'font-size="12">{_fmt_num(odds_ratio)} '
            f'({_fmt_num(ci_low)}–{_fmt_num(ci_high)})</text>'
        )
        parts.append(
            f'<text x="{p_x}" y="{y + 4}" font-family="system-ui,sans-serif" '
            f'font-size="12">{_fmt_p(p_value)}</text>'
        )

    if xmin <= 1.0 <= xmax:
        x1 = x_of(1.0)
        parts.append(
            f'<line x1="{x1:.1f}" y1="{top - 4}" x2="{x1:.1f}" y2="{axis_y:.1f}" '
            f'stroke="#999999" stroke-width="1" stroke-dasharray="4 3"/>'
        )
    parts.append(
        f'<line x1="{plot_l}" y1="{axis_y}" x2="{plot_r}" y2="{axis_y}" '
        f'stroke="#666666" stroke-width="1"/>'
    )
    for tick in ticks:
        x1 = x_of(float(tick))
        parts.append(
            f'<line x1="{x1:.1f}" y1="{axis_y}" x2="{x1:.1f}" y2="{axis_y + 5}" '
            f'stroke="#666666" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x1:.1f}" y="{axis_y + 20}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="11" fill="#333">'
            f"{tick:g}</text>"
        )
    parts.append(
        '<text x="24" y="' + str(height - 12) + '" font-family="system-ui,sans-serif" '
        'font-size="11" fill="#666">'
        f'{escape(str(spec.data.get("label", "")))}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]


def render_flow_svg(spec: FigureSpec) -> str:
    """Builtin renderer for ``strobe_flow``: inclusion/exclusion flow diagram."""
    stages: list[dict] = list(spec.data.get("stages") or [])
    exclusions: list[dict] = list(spec.data.get("exclusions") or [])
    width = 760
    box_x, box_w, box_h, gap, top = 110, 330, 58, 46, 96
    ex_x, ex_w, ex_h = 480, 250, 50
    height = top + max(1, len(stages)) * box_h + (max(1, len(stages)) - 1) * gap + 40

    def stage_y(i: int) -> float:
        return top + i * (box_h + gap)

    parts = _svg_header(width, height)
    parts.append(
        f'<text x="24" y="34" font-family="system-ui,sans-serif" font-size="18" '
        f'font-weight="600">{escape(spec.title)}</text>'
    )
    parts.append(
        '<text x="24" y="56" font-family="system-ui,sans-serif" font-size="12" fill="#666">'
        f'run {escape(spec.source.run_id)} · '
        f'{escape(str(spec.data.get("label", "")))}</text>'
    )
    cohort_note = str(spec.data.get("cohort_note") or "")
    if cohort_note:
        parts.append(
            '<text x="24" y="74" font-family="system-ui,sans-serif" font-size="12" '
            f'fill="#666">{escape(cohort_note)}</text>'
        )
    parts.append(
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#666666"/></marker></defs>'
    )

    for i, stage in enumerate(stages):
        y = stage_y(i)
        cx = box_x + box_w / 2
        parts.append(
            f'<rect x="{box_x}" y="{y:.1f}" width="{box_w}" height="{box_h}" rx="6" '
            f'fill="#f7f7f7" stroke="#666666" stroke-width="1.2"/>'
        )
        parts.append(
            f'<text x="{cx}" y="{y + 24:.1f}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="12">'
            f"{escape(str(stage.get('label', '')))}</text>"
        )
        parts.append(
            f'<text x="{cx}" y="{y + 44:.1f}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="15" font-weight="600">n = '
            f"{int(stage.get('n', 0))}</text>"
        )
        if i + 1 < len(stages):
            parts.append(
                f'<line x1="{cx}" y1="{y + box_h:.1f}" x2="{cx}" '
                f'y2="{stage_y(i + 1):.1f}" stroke="#666666" stroke-width="1.2" '
                f'marker-end="url(#arrow)"/>'
            )

    for exclusion in exclusions:
        after = int(exclusion.get("after", 0))
        # An exclusion branches off between two consecutive stages; there is
        # nothing to exclude after the final (analysed) stage.
        if not 0 <= after < max(0, len(stages) - 1):
            continue
        y_center = stage_y(after) + box_h + gap / 2
        parts.append(
            f'<line x1="{box_x + box_w}" y1="{y_center:.1f}" x2="{ex_x}" '
            f'y2="{y_center:.1f}" stroke="#c44e52" stroke-width="1.2" '
            f'marker-end="url(#arrow)"/>'
        )
        parts.append(
            f'<rect x="{ex_x}" y="{y_center - ex_h / 2:.1f}" width="{ex_w}" '
            f'height="{ex_h}" rx="6" fill="#fdf3f3" stroke="#c44e52" '
            f'stroke-width="1.1"/>'
        )
        label_lines = _wrap(str(exclusion.get("label", "")), 34)
        for j, line in enumerate(label_lines):
            parts.append(
                f'<text x="{ex_x + ex_w / 2}" y="{y_center - 6 + j * 14:.1f}" '
                f'text-anchor="middle" font-family="system-ui,sans-serif" '
                f'font-size="11">{escape(line)}</text>'
            )
        parts.append(
            f'<text x="{ex_x + ex_w / 2}" y="{y_center + ex_h / 2 - 8:.1f}" '
            f'text-anchor="middle" font-family="system-ui,sans-serif" '
            f'font-size="12" font-weight="600">n = {int(exclusion.get("n", 0))}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _stat_section(session: AnalysisSession, stat: StatResult) -> str:
    table = stat.table
    return f"""## Statistical result

| Group | Count |
|---|---:|
| gene+ / resistant | {table.get("gene_pos_resistant", 0)} |
| gene+ / susceptible | {table.get("gene_pos_susceptible", 0)} |
| gene- / resistant | {table.get("gene_neg_resistant", 0)} |
| gene- / susceptible | {table.get("gene_neg_susceptible", 0)} |

- n = {stat.n}
- odds ratio = {_fmt(stat.odds_ratio)} (95% CI {_fmt(stat.ci_low)}–{_fmt(stat.ci_high)})
- Fisher exact p = {_fmt(stat.p_value)}
- diagnostics: {"; ".join(stat.diagnostics) if stat.diagnostics else "none"}
"""


def render_report_markdown(session: AnalysisSession, stat: StatResult) -> str:
    return f"""# AMR association report — {escape(session.gene)} × {escape(session.test_name)}

> **{escape(session.label or session.status.value)}**. Generated deterministically from existing
> evidence; this is not a publication-ready claim.

## Study input

- run: `{escape(session.run_id)}`
- gene: `{escape(session.gene)}`
- phenotype test: `{escape(session.test_name)}`
- profile: `{escape(session.profile.value)}`
- data class: D{session.data_class}
- session: `{escape(session.session_id)}`

{_stat_section(session, stat)}

## Interpretation

The table is a descriptive association between gene presence and the recorded phenotype. It does
not establish causality, mechanism, or transferability. Lineage structure, co-carried genes,
sampling bias and phenotype measurement error are not controlled in this P1 slice.

## Reproducibility

The numbers above are reproducible from the named run and the local `gom.sqlite` and
`data/bacmap.sqlite`; see the session ledger for creation details.

![association figure](figure.svg)
"""


def render_manuscript_markdown(session: AnalysisSession, stat: StatResult) -> str:
    return f"""# Association between {escape(session.gene)} and {escape(session.test_name)}
## in a local run

> **TEST / UNVERIFIED** — generated by the P1 Research Workbench. Do not submit as a scientific
> manuscript without cohort freezing, lineage-aware statistics, sensitivity analysis and human
> review.

## Abstract

We examined whether `{escape(session.gene)}` is associated with `{escape(session.test_name)}` among
the strains analysed in run `{escape(session.run_id)}`. This is an exploratory, descriptive
analysis of existing local evidence.

## Methods

Gene presence was taken from the local AMR index (`strain_amr_genes`); phenotype was taken from
local lab results for the named test. Strains without a usable interpretation were excluded.
A two-sided Fisher exact test and a Woolf odds-ratio confidence interval were used. A
Haldane-Anscombe correction was applied when a 2×2 cell was zero.

## Results

{_stat_section(session, stat)}

## Limitations

- Single run; no independent cohort or external validation.
- No lineage, population-structure, co-carriage or batch adjustment.
- Phenotype interpretation and breakpoints are taken as recorded.
- The result is an association, not evidence of causality or mechanism.
- The manuscript is a draft and may not be used for publication without review.

## Data and code availability

The analysis is reproducible from run `{escape(session.run_id)}` and the local bacmap research
session `{escape(session.session_id)}`.
"""
