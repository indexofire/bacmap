"""只读视图：summary 扫描口径（每个样本目录只认同名 summary）。"""

from __future__ import annotations

import json
from pathlib import Path

from bacmap.interfaces.views import load_summaries


class _Engine:
    def __init__(self, home: Path) -> None:
        self.home = home


def _summary(sample: str) -> dict:
    return {"sample": sample, "steps": {"species": {"verdict": "Salmonella"}}}


class TestLoadSummaries:
    def test_ignores_stale_differently_named_summary(self, tmp_path: Path):
        rep = tmp_path / "results" / "S1" / "report"
        rep.mkdir(parents=True)
        (rep / "S1_summary.json").write_text(json.dumps(_summary("S1")))
        (rep / "OLD-NAME_summary.json").write_text(json.dumps(_summary("OLD-NAME")))
        rows = load_summaries(_Engine(tmp_path))
        assert [r["_sample_id"] for r in rows] == ["S1"]

    def test_missing_results_dir_returns_empty(self, tmp_path: Path):
        assert load_summaries(_Engine(tmp_path)) == []
