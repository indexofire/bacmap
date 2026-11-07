"""Persisted analysis results linked to a Study."""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.research.analyses import ResearchAnalysisService
from bacmap.research.service import ResearchObjectService
from bacmap.research.store import ResearchObjectStore


@pytest.fixture
def study(tmp_path: Path):
    svc = ResearchObjectService(tmp_path)
    return svc.create_study("Analysis question", "KPN", 2, "t"), tmp_path


def test_save_list_get_and_hash(study, tmp_path: Path):
    item, home = study
    data = tmp_path / "cohort.csv"
    data.write_text("x,y\n1,2\n", encoding="utf-8")
    svc = ResearchAnalysisService(home)
    record = svc.save(
        item.study_id,
        "logistic",
        {"n": 10, "odds_ratio": 2.0},
        title="logistic test",
        params={"outcome": "y"},
        input_paths=[str(data)],
        actor="web",
    )
    assert record.analysis_id.startswith("ana-")
    assert len(record.result_sha256) == 64
    assert record.input_sha256[str(data)]
    items = svc.list_analyses(item.study_id)
    assert [entry.analysis_id for entry in items] == [record.analysis_id]
    assert svc.get_analysis(record.analysis_id).result["odds_ratio"] == 2.0


def test_analysis_links_to_study(study):
    item, home = study
    record = ResearchAnalysisService(home).save(
        item.study_id, "iptw", {"effect": 0.2}, actor="web"
    )
    with ResearchObjectStore(home) as store:
        edges = store.list_edges_for_id(item.study_id)
    assert any(
        edge.src_id == record.analysis_id and edge.edge_type == "ANALYSIS_OF"
        for edge in edges
    )


def test_unknown_study(study):
    _, home = study
    with pytest.raises(ValueError, match="no such study"):
        ResearchAnalysisService(home).save("study-nope", "logistic", {})
