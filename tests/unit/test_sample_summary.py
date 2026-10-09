"""Unit tests for bacmap.store.sample_summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.store.sample_summary import (  # noqa: E402
    classify_samples,
    read_summary,
    sample_status,
    sample_steps,
    snp_cohort_status,
    summary_fields,
    summary_path,
)

_MLST_TSV = "ST\trpoB\n152\t12\n"


def _make_sample(base: Path, sid: str, steps: list[str]) -> None:
    artifacts = {
        "qc": base / sid / "qc" / f"{sid}_fastp.json",
        "assembly": base / sid / "assembly" / "contigs.fasta",
        "species": base / sid / "species" / "species_id.json",
        "mlst": base / sid / "typing" / "mlst.tsv",
        "amr": base / sid / "amr" / "abricate_card.tsv",
        "report": base / sid / "report" / f"{sid}_summary.json",
    }
    for step in steps:
        p = artifacts[step]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")


class TestSampleSteps:
    def test_no_artifacts(self, tmp_path):
        steps = sample_steps(tmp_path, "S1")
        assert steps == {
            "qc": False,
            "assembly": False,
            "species": False,
            "mlst": False,
            "amr": False,
            "report": False,
        }

    def test_all_artifacts(self, tmp_path):
        _make_sample(tmp_path, "S1", ["qc", "assembly", "species", "mlst", "amr", "report"])
        steps = sample_steps(tmp_path, "S1")
        assert all(steps.values())

    def test_partial_artifacts(self, tmp_path):
        _make_sample(tmp_path, "S1", ["qc", "assembly"])
        steps = sample_steps(tmp_path, "S1")
        assert steps["qc"] and steps["assembly"]
        assert not steps["mlst"] and not steps["report"]


class TestReadSummary:
    def test_missing_returns_none(self, tmp_path):
        assert read_summary(tmp_path, "S1") is None

    def test_invalid_json_returns_none(self, tmp_path):
        p = summary_path(tmp_path, "S1")
        p.parent.mkdir(parents=True)
        p.write_text("not json{")
        assert read_summary(tmp_path, "S1") is None

    def test_valid_json(self, tmp_path):
        p = summary_path(tmp_path, "S1")
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"sample": "S1"}))
        assert read_summary(tmp_path, "S1") == {"sample": "S1"}


class TestSampleStatus:
    def test_completed(self, tmp_path):
        _make_sample(tmp_path, "S1", ["report"])
        assert sample_status(tmp_path, "S1") == "completed"

    def test_in_progress(self, tmp_path):
        _make_sample(tmp_path, "S1", ["assembly"])
        assert sample_status(tmp_path, "S1") == "in-progress"

    def test_not_started(self, tmp_path):
        assert sample_status(tmp_path, "S1") == "not-started"

    def test_qc_only_is_not_started(self, tmp_path):
        # web 规范:in-progress 以 contigs 为准,qc 单独存在不算
        _make_sample(tmp_path, "S1", ["qc"])
        assert sample_status(tmp_path, "S1") == "not-started"


class TestClassifySamples:
    def test_grouping(self, tmp_path):
        _make_sample(tmp_path, "DONE", ["report"])
        _make_sample(tmp_path, "WIP", ["qc"])
        result = classify_samples(tmp_path, ["DONE", "WIP", "NEW"])
        assert list(result["done"]) == ["DONE"]
        assert result["done"]["DONE"]["report"] is True
        assert list(result["in_progress"]) == ["WIP"]
        assert result["not_started"] == ["NEW"]
        assert result["snp_cohort"] == {"tree": False, "summary": False}

    def test_empty_list(self, tmp_path):
        result = classify_samples(tmp_path, [])
        assert result["done"] == {} and result["in_progress"] == {}
        assert result["not_started"] == []

    def test_snp_cohort(self, tmp_path):
        snp = tmp_path / "snp"
        snp.mkdir()
        (snp / "core.treefile").write_text("tree")
        (snp / "snp_summary.json").write_text("{}")
        result = classify_samples(tmp_path, [])
        assert result["snp_cohort"] == {"tree": True, "summary": True}


class TestSummaryFields:
    def test_full_summary(self):
        summary = {
            "steps": {
                "species": {"species": "Salmonella"},
                "mlst": _MLST_TSV,
                "serotype": {"sistr": "Typhimurium"},
            }
        }
        assert summary_fields(summary) == {
            "species": "Salmonella",
            "mlst_st": "152",
            "serotype": "Typhimurium",
        }

    def test_empty_summary(self):
        assert summary_fields({}) == {"species": "N/A", "mlst_st": "N/A", "serotype": "N/A"}

    def test_non_dict_species(self):
        summary = {"steps": {"species": "Unknown"}}
        assert summary_fields(summary)["species"] == "Unknown"

    def test_missing_sistr(self):
        summary = {"steps": {"serotype": {"other": "x"}}}
        assert summary_fields(summary)["serotype"] == "N/A"

    def test_invalid_mlst(self):
        summary = {"steps": {"mlst": "garbage"}}
        assert summary_fields(summary)["mlst_st"] == "N/A"


class TestSnpCohortStatus:
    def test_absent(self, tmp_path):
        assert snp_cohort_status(tmp_path) == {"tree": False, "summary": False}

    def test_present(self, tmp_path):
        snp = tmp_path / "snp"
        snp.mkdir()
        (snp / "snp_summary.json").write_text("{}")
        assert snp_cohort_status(tmp_path) == {"tree": False, "summary": True}
