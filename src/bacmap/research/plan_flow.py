"""计划任务流程图（PLAN #3）：确定性 SVG 渲染，离线无依赖。

把计划中的任务列表渲染为可视化流程图：任务框（类型 + 摘要）→ 箭头 → 门/状态。
同一计划恒得同一 SVG（纯函数，无随机/时间因素）。
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

_COLORS = {
    "analyze": "#4c72b0",
    "curate": "#55a868",
    "mine": "#c44e52",
    "write": "#dd8452",
    "research": "#8172b3",
    "record": "#937860",
}


def _task_summary(task: Any) -> str:
    """任务的一行摘要（显示在框内）。"""
    ttype = getattr(task, "task_type", str(type(task).__name__))
    if ttype == "analyze":
        samples = getattr(task, "samples", None) or []
        if samples:
            return f"analyze {len(samples)} samples"
        fasta = getattr(task, "fasta_dir", None)
        fastq = getattr(task, "fastq_dir", None)
        if fasta:
            return f"analyze fasta: {Path(fasta).name}"
        return f"analyze fastq: {Path(fastq or '').name}"
    if ttype == "mine":
        objective = getattr(task, "objective", "")
        return f"mine: {objective[:40]}"
    if ttype == "write":
        return f"write: {getattr(task, 'objective', '')[:40]}"
    if ttype == "research":
        analysis = getattr(task, "analysis", "")
        method = getattr(task, "method", "")
        if analysis == "advstats":
            return f"research advstats: {method}"
        return f"research {analysis}"
    if ttype == "curate":
        return f"curate: {getattr(task, 'scope', '')}"
    return ttype


def _task_color(task: Any) -> str:
    return _COLORS.get(getattr(task, "task_type", ""), "#999999")


def render_plan_svg(tasks: list[Any], plan_id: str = "", state: str = "") -> str:
    """把计划任务渲染为确定性 SVG 流程图。"""
    if not tasks:
        tasks = []
    n = len(tasks)
    box_w, box_h, gap = 220, 56, 40
    width = max(760, n * (box_w + gap) + gap)
    height = 160
    top = 50

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="28" font-family="system-ui,sans-serif" font-size="14" '
        f'font-weight="600">Plan {escape(plan_id)}'
        + (f" · {escape(state)}" if state else "")
        + "</text>",
    ]

    for i, task in enumerate(tasks):
        x = gap + i * (box_w + gap)
        y = top
        color = _task_color(task)
        ttype = getattr(task, "task_type", "?")
        summary = _task_summary(task)

        # 任务框
        parts.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="6" '
            f'fill="#f8f9fa" stroke="{color}" stroke-width="2"/>'
        )
        # 类型标签
        parts.append(
            f'<text x="{x + box_w / 2}" y="{y + 22}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="12" font-weight="600" '
            f'fill="{color}">{escape(ttype)}</text>'
        )
        # 摘要
        parts.append(
            f'<text x="{x + box_w / 2}" y="{y + 42}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="11" fill="#333">'
            f"{escape(summary[:35])}</text>"
        )
        # 箭头
        if i + 1 < n:
            x2 = x + box_w
            parts.append(
                f'<line x1="{x2}" y1="{y + box_h / 2}" x2="{x2 + gap}" '
                f'y2="{y + box_h / 2}" stroke="#666" stroke-width="1.5" '
                f'marker-end="url(#arrow)"/>'
            )

    # 箭头 marker 定义
    parts.insert(1, (
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#666666"/></marker></defs>'
    ))

    # 结尾状态节点
    if n:
        x_end = gap + n * (box_w + gap) - gap
        parts.append(
            f'<circle cx="{x_end}" cy="{top + box_h / 2}" r="16" '
            f'fill="{"#d4edda" if state == "submitted" else "#fff3cd"}" '
            f'stroke="#666" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x_end}" y="{top + box_h / 2 + 4}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="10" fill="#333">'
            f'{"✓" if state == "submitted" else "…"}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
