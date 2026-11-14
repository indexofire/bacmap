"""VPAI 结构环（v1.10.29）：gspec 原始 PAI 位点 → 内联 SVG。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

import generate_report as gr  # noqa: E402


def _screen(tmp_path: Path) -> Path:
    sample = tmp_path / "results" / "S1"
    (sample / "gspec").mkdir(parents=True)
    payload = {
        "schema": "gspec.cluster/1",
        "files": [
            {
                "best": {"locus": "VPaI-4", "type": "PAI"},
                "loci": [
                    {
                        "locus": "VPaI-4",
                        "label": "VPaI-4",
                        "coverage_pct": 100.0,
                        "identity_pct": 100.0,
                        "genes": [
                            {"gene_id": "VP2131", "verdict": "present"},
                            {"gene_id": "VP2132", "verdict": "partial"},
                            {"gene_id": "VP2133", "verdict": "absent"},
                        ],
                    },
                    {
                        "locus": "VPaI-5",
                        "label": "VPaI-5",
                        "coverage_pct": 92.0,
                        "identity_pct": 99.0,
                        "genes": [{"gene_id": "VP2900", "verdict": "present"}],
                    },
                ],
            }
        ],
    }
    (sample / "gspec" / "vpa_pai_screen.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return sample


def test_pai_section_renders_circular_map(tmp_path, monkeypatch):
    _screen(tmp_path)
    monkeypatch.setattr(gr, "RESULTS_DIR", tmp_path / "results")
    html = gr._render_pai_section("S1", {})
    assert "PAI 结构（VPAI）" in html
    assert 'class="pai-circos"' in html
    assert "VPaI-4" in html and "VPaI-5" in html
    assert html.count("<line") == 4
    assert "present" in html and "partial" in html and "absent" in html
    assert "<table>" in html


def test_pai_section_empty_without_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "RESULTS_DIR", tmp_path / "results")
    assert gr._render_pai_section("S1", {}) == ""
