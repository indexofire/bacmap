"""报告中的 QUAST / Bakta / eggNOG 注释章节测试（v1.10.14）。"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

import generate_report as gr  # noqa: E402


def test_report_template_is_dark_and_versioned(tmp_path):
    """v0.2.0：报告使用暗色 token，并带版本标记供 Web 自动升级旧报告。"""
    from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

    summary = {"steps": {}}
    out = tmp_path / "S1_report.html"
    gr.generate_html("S1", summary, DeterministicVerifier().verify_all(summary), out)
    text = out.read_text(encoding="utf-8")
    assert 'name="bacmap-report" content="7"' in text
    assert "--bg: #08090a" in text
    assert "max-width: 900px" not in text  # 旧浅色模板已淘汰


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


def test_nli_section_renders_persisted_ai_text(monkeypatch):
    monkeypatch.setattr(
        "bacmap.core.verify.nli_reflector.latest_review_flag",
        lambda _db, _sample: {
            "interpretation_text": "检出 blaTEM-1，提示氨苄西林耐药。",
            "needs_human_review": False,
            "contradiction_rate": 0.0,
            "threshold": 0.3,
            "verifiable_count": 1,
            "corroborated_count": 1,
            "timestamp": "2026-11-10T00:00:00",
            "contradicted_claims": [],
        },
    )
    html_text = gr._render_nli_section("S1")
    assert "AI 解读与 NLI 自检" in html_text
    assert "已通过 NLI 自检" in html_text
    assert "blaTEM-1" in html_text


def test_annotation_section_quast_only_when_annotation_disabled():
    html_text = gr._render_annotation_section(
        {"steps": {"assembly_quast": "Assembly\tcontigs\ncontigs.fasta\t12"}}
    )
    assert "QUAST" in html_text
    assert "Bakta" not in html_text


def test_annotation_section_empty_when_no_data():
    assert gr._render_annotation_section({"steps": {}}) == ""
