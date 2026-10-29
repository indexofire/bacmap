"""curate 代表运行（I3）：同一 isolate 多个 dataset 只纳入一次。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bacmap.store import baseline


def _summary(sample: str, species: str = "Vibrio parahaemolyticus") -> dict:
    return {
        "sample": sample,
        "steps": {
            "species": {"verdict": species},
            "mlst": "FILE\tSCHEME\tST\taroC\nx\tvpa\t1\t1",
            "serotype": {"sistr": ""},
            "amr": {"abricate_card": []},
            "qc": {"after_filtering": {"total_reads": 1000}},
        },
    }


def _sample_dir(home: Path, ds: str, mtime: int) -> None:
    rep = home / "results" / ds / "report"
    rep.mkdir(parents=True)
    p = rep / f"{ds}_summary.json"
    p.write_text(json.dumps(_summary(ds)))
    os.utime(p, (mtime, mtime))


def _tsv(home: Path, rows: list[tuple[str, str]]) -> None:
    tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    tsv.parent.mkdir(parents=True)
    lines = ["sample\tspecies\tR1\tR2\tassembly\tisolate\tplatform\tchecksum"]
    for ds, iso in rows:
        lines.append(f"{ds}\tVPA\t\t\t\t{iso}\tilm\t")
    tsv.write_text("\n".join(lines) + "\n")


def _meta(home: Path, isolate: str) -> None:
    from bacmap.store.strain_metadata import StrainMetadataService

    db = home / "data" / "bacmap.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    StrainMetadataService(db).upsert(
        isolate,
        {"sample_id": isolate, "isolation_date": "2026-01-01",
         "province": "Guangdong", "sample_source": "food"},
    )


@pytest.fixture
def home(tmp_path: Path):
    return tmp_path


class TestRepresentative:
    def test_one_strain_per_isolate_latest_wins(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1"), ("DS1__ont", "ISO-1"), ("DS2__ilm", "ISO-2")])
        _sample_dir(home, "DS1__ilm", 1_700_000_000)
        _sample_dir(home, "DS1__ont", 1_800_000_000)
        _sample_dir(home, "DS2__ilm", 1_700_000_000)
        _meta(home, "ISO-1")
        _meta(home, "ISO-2")
        cand = baseline.build_candidate(home, {})
        assert sorted(s["strain_id"] for s in cand["strains"]) == ["DS1__ont", "DS2__ilm"]
        reps = cand["representative_runs"]
        assert reps["ISO-1"]["dataset_id"] == "DS1__ont"
        assert reps["ISO-1"]["reason"] == "latest"
        assert cand["superseded"] == [
            {"isolate_id": "ISO-1", "dataset_id": "DS1__ilm", "reason": "latest"}
        ]

    def test_explicit_dataset_choice(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1"), ("DS1__ont", "ISO-1")])
        _sample_dir(home, "DS1__ilm", 1_700_000_000)
        _sample_dir(home, "DS1__ont", 1_800_000_000)
        _meta(home, "ISO-1")
        cand = baseline.build_candidate(home, {"representative_dataset": {"ISO-1": "DS1__ilm"}})
        assert [s["strain_id"] for s in cand["strains"]] == ["DS1__ilm"]
        assert cand["representative_runs"]["ISO-1"]["reason"] == "explicit"

    def test_unknown_explicit_choice_is_recorded_as_excluded(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1")])
        _sample_dir(home, "DS1__ilm", 1_700_000_000)
        _meta(home, "ISO-1")
        cand = baseline.build_candidate(home, {"representative_dataset": {"ISO-1": "NOPE"}})
        assert cand["strains"] == []
        assert cand["excluded"][0]["reason"] == "representative_dataset_missing"

    def test_scope_strains_accepts_isolate(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1"), ("DS1__ont", "ISO-1"), ("DS2__ilm", "ISO-2")])
        for ds, mt in (("DS1__ilm", 1), ("DS1__ont", 2), ("DS2__ilm", 3)):
            _sample_dir(home, ds, 1_700_000_000 + mt)
        _meta(home, "ISO-1")
        _meta(home, "ISO-2")
        cand = baseline.build_candidate(home, {"strains": ["ISO-1"]})
        assert [s["strain_id"] for s in cand["strains"]] == ["DS1__ont"]


class TestUnknownRepresentativeIsolate:
    def test_typo_isolate_is_reported_not_silently_ignored(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1")])
        _sample_dir(home, "DS1__ilm", 1_700_000_000)
        _meta(home, "ISO-1")
        cand = baseline.build_candidate(
            home,
            {"representative_dataset": {"ISO-1": "DS1__ilm", "TYPO": "DS1__ilm"}},
        )
        assert [s["strain_id"] for s in cand["strains"]] == ["DS1__ilm"]
        assert any(
            e["reason"] == "representative_isolate_missing" and e["isolate_id"] == "TYPO"
            for e in cand["excluded"]
        )


class TestStaleSummaryNotCounted:
    def test_differently_named_summary_ignored(self, home):
        _tsv(home, [("DS1__ilm", "ISO-1")])
        _sample_dir(home, "DS1__ilm", 1_700_000_000)
        rep = home / "results" / "DS1__ilm" / "report"
        (rep / "STALE_summary.json").write_text(json.dumps(_summary("STALE")))
        _meta(home, "ISO-1")
        cand = baseline.build_candidate(home, {})
        assert [s["strain_id"] for s in cand["strains"]] == ["DS1__ilm"]
        assert cand["superseded"] == []
