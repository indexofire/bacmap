"""本地流行特征库（ADR-19）测试：发布门 / 候选构建 / curate 任务回环。"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.store import baseline
from bacmap.store.strain_metadata import StrainMetadataService
from bacmap.tasks import gates
from bacmap.tasks.gates import GateVerdict
from bacmap.tasks.spec import Approval, TaskState, TaskType


def _sal_summary(strain: str = "SAM-001") -> dict:
    return {
        "sample": strain,
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {
                "abricate_card": [{"GENE": "blaCTX-M-15"}],
                "abricate_vfdb": [{"GENE": "ssrA"}],
            },
            "plasmid": {"plasmidfinder": [{"GENE": "IncFIB"}]},
            "qc": {"after_filtering": {"total_reads": 1000}},
            "dec": {},
        },
    }


def _valid_candidate() -> dict:
    return {
        "home": "/tmp/x",
        "scope": {},
        "strains": [
            {
                "strain_id": "SAM-001",
                "features": {
                    "species": "Salmonella",
                    "serotype": "Typhimurium",
                    "mlst_st": "19",
                    "isolation_date": "2025-06-01",
                    "province": "Guangdong",
                    "city": "Shenzhen",
                    "sample_source": "food",
                },
            }
        ],
        "excluded": [],
    }


class TestBaselineReleaseGate:
    def test_valid_candidate_passes(self):
        r = gates.evaluate_baseline_release(_valid_candidate())
        assert r.verdict == GateVerdict.PASS
        assert r.details["n_strains"] == 1

    def test_missing_isolation_date_rejects(self):
        c = _valid_candidate()
        del c["strains"][0]["features"]["isolation_date"]
        r = gates.evaluate_baseline_release(c)
        assert r.verdict == GateVerdict.REJECT
        assert any("isolation_date" in p for p in r.details["problems"])

    def test_duplicate_strain_rejects(self):
        c = _valid_candidate()
        c["strains"].append(dict(c["strains"][0]))
        r = gates.evaluate_baseline_release(c)
        assert r.verdict == GateVerdict.REJECT
        assert any("duplicate" in p for p in r.details["problems"])

    def test_d4_leak_rejects(self):
        c = _valid_candidate()
        c["strains"][0]["features"]["patient_name"] = "Zhang San"
        r = gates.evaluate_baseline_release(c)
        assert r.verdict == GateVerdict.REJECT
        assert any("d4_leak" in p for p in r.details["problems"])

    def test_unknown_species_rejects(self):
        c = _valid_candidate()
        c["strains"][0]["features"]["species"] = "unknown"
        r = gates.evaluate_baseline_release(c)
        assert r.verdict == GateVerdict.REJECT

    def test_empty_candidate_rejects(self):
        r = gates.evaluate_baseline_release({"strains": [], "excluded": []})
        assert r.verdict == GateVerdict.REJECT

    def test_registry_dispatch(self):
        r = gates.evaluate(
            gates.GateSubject(gate="baseline_release", payload={"candidate": _valid_candidate()})
        )
        assert r.gate == "baseline_release"


@pytest.fixture
def fixture_home(tmp_path: Path) -> Path:
    home = tmp_path
    bad_summary = _sal_summary("SAM-BAD")
    bad_summary["steps"]["species"] = {"verdict": "Listeria"}
    for strain, summary in [("SAM-001", _sal_summary("SAM-001")), ("SAM-BAD", bad_summary)]:
        rep = home / "results" / strain / "report"
        rep.mkdir(parents=True)
        (rep / f"{strain}_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    (home / "data").mkdir(parents=True, exist_ok=True)
    meta = StrainMetadataService(home / "data" / "metadata.sqlite")
    meta.upsert(
        "SAM-001",
        {
            "sample_id": "S001",
            "isolation_date": "2025-06-01",
            "province": "Guangdong",
            "city": "Shenzhen",
            "district": "Nanshan",
            "sample_source": "food",
            "food_category": "poultry",
            "outbreak_id": "OB-2025-03",
            "patient_name": "张三",
            "patient_phone": "13800000000",
        },
    )
    meta.upsert(
        "SAM-BAD",
        {
            "sample_id": "S002",
            "isolation_date": "2025-07-01",
            "province": "GD",
            "sample_source": "clinical",
        },
    )
    return home


class TestBuildCandidate:
    def test_includes_valid_excludes_failing(self, fixture_home):
        c = baseline.build_candidate(fixture_home)
        ids = [s["strain_id"] for s in c["strains"]]
        assert ids == ["SAM-001"]
        assert c["excluded"] == [{"strain_id": "SAM-BAD", "reason": "analysis_ok"}]

    def test_features_whitelist_no_d4_leak(self, fixture_home):
        c = baseline.build_candidate(fixture_home)
        f = c["strains"][0]["features"]
        assert f["species"] == "Salmonella"
        assert f["mlst_st"] == "19"
        assert f["amr_genes"] == ["blaCTX-M-15"]
        assert f["isolation_date"] == "2025-06-01"
        assert f["outbreak_id"] == "OB-2025-03"
        from bacmap.tasks.gates import _D4_KEYS

        assert not (_D4_KEYS & set(f))
        assert "patient_name" not in f and "patient_phone" not in f

    def test_scope_pathogen_filters(self, fixture_home):
        c = baseline.build_candidate(fixture_home, scope={"pathogen": "Salmonella"})
        assert [s["strain_id"] for s in c["strains"]] == ["SAM-001"]
        c2 = baseline.build_candidate(fixture_home, scope={"pathogen": "Vibrio"})
        assert c2["strains"] == []

    def test_stats_aggregate(self, fixture_home):
        c = baseline.build_candidate(fixture_home)
        s = baseline.compute_stats(c)
        assert s["n_strains"] == 1
        key = "Salmonella|2025|Guangdong|food"
        assert s["by_species_year_region_source"][key] == 1


class TestPublish:
    def test_publish_and_get_release(self, fixture_home):
        c = baseline.build_candidate(fixture_home)
        db = fixture_home / "baseline.sqlite"
        v1 = baseline.publish(db, c, created_by="curator", signature="sig-001")
        assert v1 == 1
        v2 = baseline.publish(db, c, created_by="curator", signature="sig-002")
        assert v2 == 2

        rel = baseline.get_release(db, 1)
        assert rel["n_strains"] == 1
        assert rel["signature"] == "sig-001"
        manifest = json.loads(rel["manifest_json"])
        assert manifest["strains"][0]["strain_id"] == "SAM-001"

        versions = [r["version"] for r in baseline.list_releases(db)]
        assert versions == [1, 2]

    def test_candidate_roundtrip(self, fixture_home):
        c = baseline.build_candidate(fixture_home)
        db = fixture_home / "baseline.sqlite"
        gate = gates.evaluate_baseline_release(c).model_dump(mode="json")
        baseline.save_candidate(db, "task-1", c, gate)
        loaded = baseline.load_candidate(db, "task-1")
        assert loaded is not None
        assert loaded["manifest"]["strains"][0]["strain_id"] == "SAM-001"
        assert loaded["gate"]["verdict"] == "pass"


class TestCurateTaskRoundtrip:
    @pytest.fixture
    def engine(self, fixture_home, monkeypatch):
        e = eng.DbosTaskEngine(fixture_home)
        yield e
        eng.shutdown_dbos()

    def _wait(self, e, tid, timeout_s=30):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = e.status(tid)
            if st.state != TaskState.RUNNING:
                return st
            time.sleep(0.2)
        return e.status(tid)

    def test_curate_awaits_approval_then_publishes(self, engine, fixture_home):
        tid = engine.submit(TaskType.CURATE, {"scope": {}}, "curator")
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL

        engine.approve(
            tid,
            Approval(
                approver="reviewer",
                decision="approve",
                signature="sig-approved",
                at=datetime.now(UTC),
            ),
        )
        final = engine.status(tid)
        assert final.state == TaskState.SUCCEEDED
        assert "published baseline v1" in (final.message or "")

        releases = baseline.list_releases(fixture_home / "baseline.sqlite")
        assert len(releases) == 1
        assert releases[0]["n_strains"] == 1
        rel = baseline.get_release(fixture_home / "baseline.sqlite", 1)
        manifest = json.loads(rel["manifest_json"])
        assert "patient_name" not in manifest["strains"][0]["features"]

    def test_curate_reject_approval_fails_without_publish(self, engine, fixture_home):
        tid = engine.submit(TaskType.CURATE, {"scope": {}}, "curator")
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        engine.approve(
            tid,
            Approval(
                approver="reviewer",
                decision="reject",
                signature="sig-rejected",
                at=datetime.now(UTC),
            ),
        )
        assert engine.status(tid).state == TaskState.FAILED
        assert baseline.list_releases(fixture_home / "baseline.sqlite") == []


class TestBuildCandidateArbitraryIds:
    """样本 ID 不限 SAM-*（与 bio_list_samples/Web 扫描口径一致）。"""

    def test_non_sam_sample_id_included(self, tmp_path):
        rep = tmp_path / "results" / "CTX008" / "report"
        rep.mkdir(parents=True)
        (rep / "CTX008_summary.json").write_text(json.dumps(_sal_summary("CTX008")))
        (tmp_path / "data").mkdir()
        meta = StrainMetadataService(tmp_path / "data" / "metadata.sqlite")
        meta.upsert(
            "CTX008",
            {"isolation_date": "2025-01-01", "province": "GD", "sample_source": "food"},
        )
        c = baseline.build_candidate(tmp_path)
        assert [s["strain_id"] for s in c["strains"]] == ["CTX008"]


class TestPublishParentVersion:
    """ADR-19：发布版本记录 parent_version（版本链）。"""

    def test_parent_version_chain(self, tmp_path):
        from bacmap.store import baseline as b

        db = tmp_path / "baseline.sqlite"
        v1 = b.publish(db, _valid_candidate(), "mark", "sig1")
        v2 = b.publish(db, _valid_candidate(), "mark", "sig2")
        assert v2 == v1 + 1
        assert b.get_release(db, v1)["parent_version"] is None
        assert b.get_release(db, v2)["parent_version"] == v1
