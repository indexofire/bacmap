"""报告抗原式按物种渲染（v1.10.28）。

旧模板固定输出 ``o_antigen:h1:h2``，副溶血弧菌没有 H1/H2 → ``O10::``。
现在：沙门 O:H1:H2、副溶血 O:K（OL/KL 位点）、大肠 O:H，无分型的物种不显示。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bacmap.core.verify.deterministic_verifier import DeterministicVerifier

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

import generate_report as gr  # noqa: E402


def _render(tmp_path: Path, steps: dict) -> str:
    summary = {"steps": steps}
    out = tmp_path / "S1_report.html"
    gr.generate_html("S1", summary, DeterministicVerifier().verify_all(summary), out)
    return out.read_text(encoding="utf-8")


def test_vpa_uses_o_k_locus_formula(tmp_path):
    html = _render(
        tmp_path,
        {
            "species": {"species": "Vibrio_parahaemolyticus"},
            "serotype": {
                "value": "O10:K4",
                "o_antigen": "O10",
                "k_antigen": "K4",
                "h1": "N/A",
                "h2": "N/A",
                "antigen_formula": "OL10:KL4",
                "antigen_kind": "O:K",
            },
            "vpa_serotype": {"predicted_serotype": "O10:K4"},
        },
    )
    assert "OL10:KL4" in html
    assert "抗原式（O:K）" in html
    assert "O10:N/A:N/A" not in html
    assert "抗原式（O:H1:H2）" not in html
    # VPA 没有血清群，不显示占位行
    assert "血清群" not in html


def test_old_vpa_summary_falls_back_to_phenotype(tmp_path):
    """v1.10.28 前的 summary 没有位点 ID：退回 O10:K4，而不是 O10::。"""
    html = _render(
        tmp_path,
        {
            "species": {"species": "Vibrio_parahaemolyticus"},
            "serotype": {"value": "N/A", "o_antigen": "O10", "h1": "N/A", "h2": "N/A"},
            "vpa_serotype": {"predicted_serotype": "O10:K4"},
        },
    )
    assert "O10:K4" in html
    assert '<td class="label">血清型</td><td class="ok">O10:K4</td>' in html
    assert ":N/A" not in html


def test_old_summary_reads_loci_from_raw_screen(tmp_path, monkeypatch):
    """旧 summary 没有位点 ID 时，从 run 内 gspec 原始 JSON 取 OL/KL。"""
    sample_dir = tmp_path / "results" / "S1"
    (sample_dir / "gspec").mkdir(parents=True)
    (sample_dir / "gspec" / "vpa_ok_screen.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "phenotypes": {
                            "o_group": {"winner_locus": "OL10V1"},
                            "k_group": {"winner_locus": "KL4"},
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gr, "RESULTS_DIR", tmp_path / "results")
    html = _render(
        tmp_path,
        {
            "species": {"species": "Vibrio_parahaemolyticus"},
            "serotype": {"value": "N/A"},
            "vpa_serotype": {"predicted_serotype": "O10:K4"},
        },
    )
    assert "OL10:KL4" in html
    assert "抗原式（O:K）" in html


def test_salmonella_keeps_o_h1_h2_formula(tmp_path):
    html = _render(
        tmp_path,
        {
            "species": {"species": "Salmonella"},
            "serotype": {
                "value": "Typhimurium",
                "o_antigen": "O4",
                "h1": "i",
                "h2": "1,2",
            },
        },
    )
    assert "抗原式（O:H1:H2）" in html
    assert "O4:i:1,2" in html


def test_ecoli_uses_o_h_formula(tmp_path):
    html = _render(
        tmp_path,
        {
            "species": {"species": "Escherichia_coli"},
            "serotype": {"value": "O157:H7"},
            "dec": {"ecoh_serotype": {"o_type": "O157", "h_type": "H7"}},
        },
    )
    assert "抗原式（O:H）" in html
    assert "O157:H7" in html
    assert "抗原式（O:H1:H2）" not in html


def test_species_without_antigen_scheme_omits_the_row(tmp_path):
    html = _render(
        tmp_path,
        {
            "species": {"species": "Listeria_monocytogenes"},
            "serotype": {"value": "N/A", "serogroup": "IIa"},
        },
    )
    assert "血清群" in html
    assert "IIa" in html
    assert "抗原式" not in html
    assert "N/A:N/A:N/A" not in html
