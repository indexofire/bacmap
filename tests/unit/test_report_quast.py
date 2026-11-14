"""QUAST 组装质控可视化（v1.10.28）：Nx 曲线、长度/GC 分布。"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

import generate_report as gr  # noqa: E402

_QUAST = (
    "Assembly\tS1\n"
    "# contigs (>= 0 bp)\t10\n"
    "# contigs (>= 1000 bp)\t5\n"
    "Total length (>= 0 bp)\t1000000\n"
    "Total length (>= 1000 bp)\t990000\n"
    "# contigs\t8\n"
    "Largest contig\t400000\n"
    "Total length\t1000000\n"
    "GC (%)\t50.2\n"
    "N50\t250000\n"
    "N90\t50000\n"
    "auN\t280000\n"
    "L50\t3\n"
    "L90\t7\n"
    "# N's per 100 kbp\t1.2\n"
)


def _stats() -> dict:
    return {
        "count": 8,
        "total_length": 1000000,
        "largest": 400000,
        "n50": 250000,
        "l50": 3,
        "gc_mean": 50.1,
        "length_bins": [
            {"label": "10–25 kb", "count": 2, "bp": 30000},
            {"label": "≥ 1 Mb", "count": 0, "bp": 0},
        ],
        "gc_bins": [
            {"label": "45–50%", "count": 1, "bp": 100000},
            {"label": "50–55%", "count": 3, "bp": 400000},
        ],
        "nx": [
            {"x": 0, "length": 400000},
            {"x": 50, "length": 250000},
            {"x": 100, "length": 20000},
        ],
        "top_contigs": [
            {"name": "contig00001", "length": 400000, "gc": 50.4},
            {"name": "contig00002", "length": 200000, "gc": 49.8},
        ],
    }


def test_quast_section_renders_distributions_and_nx_curve():
    html = gr._render_quast_section(_QUAST, _stats())
    assert "Contig 长度分布" in html
    assert "GC 分布" in html
    assert "Nx 曲线" in html
    assert "<svg" in html and "N50" in html
    assert "最长 contig" in html
    assert "contig00001" in html
    # 空分箱不画
    assert "≥ 1 Mb" not in html


def test_quast_section_still_works_without_contig_stats():
    html = gr._render_quast_section(_QUAST)
    assert "组装连续性" in html
    assert "片段化剖面" in html
    assert "Contig 长度分布" not in html
