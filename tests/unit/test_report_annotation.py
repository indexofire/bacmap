"""报告中的 QUAST / Bakta / eggNOG 注释章节测试（v1.10.14）。"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

import generate_report as gr  # noqa: E402


def test_annotation_section_renders_quast_and_top_genes():
    summary = {
        "steps": {
            "assembly_quast": "Assembly\tcontigs\tN50\ncontigs.fasta\t12\t5000",
            "annotation": {
                "status": "ok",
                "total_CDS": 100,
                "annotated_CDS": 80,
                "annotation_rate": 0.8,
                "bakta": {"cds": 100, "rrna": 3, "trna": 20},
                "eggnog": {
                    "queries": 100,
                    "annotated": 75,
                    "cog_category_counts": {"J": 10, "V": 2},
                    "go_term_count": 4,
                    "kegg_ko_count": 8,
                    "kegg_pathway_count": 3,
                    "cazy_count": 1,
                    "pfam_count": 12,
                },
                "top_genes": [
                    {"gene": "gyrA", "product": "DNA gyrase subunit A", "source": "bakta"}
                ],
            },
        }
    }
    html_text = gr._render_annotation_section(summary)
    assert "QUAST" in html_text
    assert "Bakta" in html_text
    assert "80.0%" in html_text
    assert "J:10" in html_text
    assert "gyrA" in html_text


def test_annotation_section_empty_when_no_data():
    assert gr._render_annotation_section({"steps": {}}) == ""
