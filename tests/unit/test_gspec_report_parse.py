"""gspec screen JSON 主输出（v1.10.19）。

- ``parse_gspec_report``：``gspec screen -f json`` 报告 → abricate 形状行
- ``load_screen_hits``：JSON 优先、旧 TSV 布局回退（旧运行目录兼容）
"""

from __future__ import annotations

import json
from pathlib import Path

from bacmap.core.utils import load_screen_hits, parse_gspec_report

_GSPEC_JSON = {
    "schema": "gspec.report/1",
    "tool": {"name": "gspec", "version": "0.10.2"},
    "params": {"db": "card", "minid": 80.0, "mincov": 80.0},
    "files": [
        {
            "file": "/data/contigs.fasta",
            "hits": [
                {
                    "sequence": "contig_1",
                    "start": 100,
                    "end": 900,
                    "strand": "+",
                    "gene": "TEM-1",
                    "coverage": "1-800/800",
                    "coverage_pct": 100.0,
                    "identity_pct": 99.88,
                    "database": "card",
                    "product": "beta-lactamase",
                    "resistance": "penicillin_beta-lactam",
                }
            ],
        }
    ],
}

_LEGACY_TSV = (
    "#FILE\tSEQUENCE\tGENE\t%IDENTITY\t%COVERAGE\tRESISTANCE\n"
    "/data/c.fasta\tcontig_2\ttet(A)\t99.9\t98.0\ttetracycline\n"
)


class TestParseGspecReport:
    def test_maps_hits_to_abricate_columns(self):
        rows = parse_gspec_report(json.dumps(_GSPEC_JSON))
        assert len(rows) == 1
        row = rows[0]
        assert row["GENE"] == "TEM-1"
        assert row["%IDENTITY"] == "99.88"
        assert row["%COVERAGE"] == "100.0"
        assert row["RESISTANCE"] == "penicillin_beta-lactam"
        assert row["SEQUENCE"] == "contig_1"
        assert row["#FILE"] == "/data/contigs.fasta"

    def test_empty_and_invalid(self):
        assert parse_gspec_report("") == []
        assert parse_gspec_report("not json") == []
        assert parse_gspec_report('{"files": []}') == []
        assert parse_gspec_report('{"files": [{"hits": null}]}') == []


class TestLoadScreenHits:
    def test_json_primary(self, tmp_path: Path):
        (tmp_path / "gspec").mkdir()
        (tmp_path / "gspec" / "card.json").write_text(json.dumps(_GSPEC_JSON))
        (tmp_path / "amr").mkdir()
        (tmp_path / "amr" / "abricate_card.tsv").write_text(_LEGACY_TSV)
        rows = load_screen_hits(tmp_path, "card")
        assert [r["GENE"] for r in rows] == ["TEM-1"]

    def test_legacy_tsv_fallback(self, tmp_path: Path):
        (tmp_path / "amr").mkdir()
        (tmp_path / "amr" / "abricate_card.tsv").write_text(_LEGACY_TSV)
        rows = load_screen_hits(tmp_path, "card")
        assert [r["GENE"] for r in rows] == ["tet(A)"]

    def test_plasmid_legacy_layout(self, tmp_path: Path):
        (tmp_path / "plasmid").mkdir()
        (tmp_path / "plasmid" / "abricate_plasmidfinder.tsv").write_text(_LEGACY_TSV)
        rows = load_screen_hits(tmp_path, "plasmidfinder")
        assert rows[0]["GENE"] == "tet(A)"

    def test_missing_everything(self, tmp_path: Path):
        assert load_screen_hits(tmp_path, "card") == []
