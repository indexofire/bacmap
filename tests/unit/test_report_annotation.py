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
    assert 'name="bacmap-report" content="10"' in text
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
    qc_text = gr._render_assembly_qc_section(summary)
    assert "组装质控" in qc_text
    assert "QUAST" in qc_text
    html_text = gr._render_annotation_section(summary)
    assert "基因组注释" in html_text
    assert "Bakta" in html_text
    assert "80.0%" in html_text
    assert "J:10" in html_text
    assert "gyrA" in html_text
    # 两个板块不再合并
    assert "QUAST" not in html_text


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


def test_assembly_qc_section_works_without_annotation():
    html_text = gr._render_assembly_qc_section(
        {"steps": {"assembly_quast": "Assembly\tcontigs\ncontigs.fasta\t12"}}
    )
    assert "组装质控" in html_text
    assert "Bakta" not in html_text


def test_quast_section_renders_visualization_from_report_tsv():
    """v1.10.25：QUAST 汇总指标渲染为指标卡 + 连续性/片段化图表，原始文本折叠。"""
    quast = "\n".join(
        [
            "Assembly\t26SAL0505",
            "# contigs (>= 0 bp)\t71",
            "# contigs (>= 1000 bp)\t53",
            "# contigs (>= 5000 bp)\t43",
            "# contigs\t55",
            "Largest contig\t439282",
            "Total length\t4703412",
            "GC (%)\t52.14",
            "N50\t170133",
            "N90\t54917",
            "auN\t195354.3",
            "L50\t9",
            "L90\t28",
            "# N's per 100 kbp\t0.00",
        ]
    )
    html_text = gr._render_assembly_qc_section({"steps": {"assembly_quast": quast}})
    assert "组装质控" in html_text
    assert "组装连续性" in html_text and "片段化剖面" in html_text
    assert "4.70 Mb" in html_text and "170.1 kb" in html_text
    assert "9 条 contig 覆盖 50%" in html_text
    assert "≥ 5,000 bp" in html_text and "43 条" in html_text
    assert "原始 QUAST 汇总数据" in html_text


def test_quast_section_handles_transposed_layout():
    quast = (
        "Assembly\t# contigs\tTotal length\tN50\tGC (%)\n"
        "contigs.fasta\t12\t4700000\t170133\t52.14"
    )
    html_text = gr._render_assembly_qc_section({"steps": {"assembly_quast": quast}})
    assert "4.70 Mb" in html_text and "170.1 kb" in html_text
    assert "52.14%" in html_text


def test_sections_empty_when_no_data():
    assert gr._render_annotation_section({"steps": {}}) == ""
    assert gr._render_assembly_qc_section({"steps": {}}) == ""
