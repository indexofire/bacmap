"""Submission package history: build, list, manifest and zip."""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.research.analyses import ResearchAnalysisService
from bacmap.research.packages import ResearchPackageService
from bacmap.research.service import ResearchObjectService


@pytest.fixture
def study(tmp_path: Path):
    svc = ResearchObjectService(tmp_path)
    return svc.create_study("Package history question", "KPN", 2, "t"), tmp_path


def test_build_list_and_load_manifest(study):
    item, home = study
    svc = ResearchPackageService(home)
    record = svc.build(item.study_id, actor="web", label="submission")
    assert record.package_id.startswith("pkg-")
    assert record.label == "submission"
    assert Path(record.path).is_dir()
    assert (Path(record.path) / "submission_manifest.json").is_file()
    assert len(record.manifest_sha256) == 64
    items = svc.list_packages(item.study_id)
    assert [entry.package_id for entry in items] == [record.package_id]
    manifest = svc.load_manifest(record)
    assert manifest["schema"] == "bacmap.submission_package/1"
    assert manifest["study_id"] == item.study_id


def test_zip_is_created(study):
    item, home = study
    svc = ResearchPackageService(home)
    record = svc.build(item.study_id, actor="web")
    archive = svc.zip_path(record)
    assert archive.is_file()
    assert archive.suffix == ".zip"


def test_unknown_study_and_package(study):
    _, home = study
    svc = ResearchPackageService(home)
    with pytest.raises(ValueError, match="no such study"):
        svc.build("study-nope")
    with pytest.raises(ValueError, match="no such submission package"):
        svc.get_package("pkg-nope")


def test_package_includes_supplementary_analyses(study):
    item, home = study
    ResearchAnalysisService(home).save(
        item.study_id,
        "logistic",
        {"n": 20, "odds_ratio": 1.5},
        title="supplementary logistic",
        params={"outcome": "outcome"},
        actor="t",
    )
    record = ResearchPackageService(home).build(item.study_id, actor="t")
    manifest = ResearchPackageService(home).load_manifest(record)
    assert manifest["analyses"][0]["analysis_type"] == "logistic"
    supplementary = [f for f in manifest["files"] if f["kind"] == "supplementary"]
    assert {Path(f["path"]).name for f in supplementary} == {
        "analyses.json",
        "analyses.tsv",
    }
    assert (Path(record.path) / "supplementary" / "analyses.tsv").is_file()
