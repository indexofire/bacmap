"""GOM 分析入库契约（ANALYSIS ingest）回归测试。

覆盖：单样本/逐样本 cgMLST/队列对象的入库、证据链字段、特征索引填充、
查询工具读回（search_samples / snp_tree / review_flags）与读路径一致性。
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap import config
from bacmap.store import runs
from bacmap.store.genome_object_service import GenomeObjectService, ObjectType
from bacmap.tasks.spec import TaskState, TaskType
from bacmap.tools import pipeline as tools_pipeline
from bacmap.tools import services as tools_services


class _Proc:
    def __init__(self, rc: int) -> None:
        self.returncode = rc


class _NoopArbiter:
    @contextlib.contextmanager
    def heavy_step(self):
        yield


_SUMMARY = {
    "sample": "SAM-001",
    "steps": {
        "species": {"species": "Salmonella"},
        "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
        "serotype": {"sistr": "Typhimurium"},
        "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}], "abricate_vfdb": []},
        "dec": {},
        "plasmid": {"plasmidfinder": [{"GENE": "IncFIB"}]},
    },
}

_CGMLST_TSV = "File\tScheme\tST\tL1\tL2\tL3\nSAM-001\tsenterica_2\t19\t1\t2\t3\n"

_SNP_COHORT = {
    "tree_newick": "(SAM-001:0.1,SAM-002:0.2);",
    "n_snp_sites": 120,
    "n_samples": 2,
    "samples": ["SAM-001", "SAM-002"],
    "pairwise_distances": {"SAM-001|SAM-002": 12},
    "missing_rate": 0.01,
    "organism": "Salmonella enterica",
}

_CGMLST_COHORT = {
    "samples": ["SAM-001", "SAM-002"],
    "n_samples": 2,
    "scheme": "senterica_2",
    "n_loci": 3002,
    "allele_distances": {"SAM-001|SAM-002": 7},
    "tree_newick": "(SAM-001:0.1,SAM-002:0.2);",
    "missing_rate": 0.02,
    "thresholds_applied": {"outbreak_allele_dist": 10},
}


def _write_results(home: Path) -> None:
    rep = home / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_SUMMARY), encoding="utf-8")
    typing = home / "results" / "SAM-001" / "typing"
    typing.mkdir()
    (typing / "cgmlst.tsv").write_text(_CGMLST_TSV, encoding="utf-8")
    snp = home / "results" / "snp" / "salmonella"
    snp.mkdir(parents=True)
    (snp / "snp_summary.json").write_text(json.dumps(_SNP_COHORT), encoding="utf-8")
    cg = home / "results" / "cgmlst" / "salmonella"
    cg.mkdir(parents=True)
    (cg / "cgmlst_summary.json").write_text(json.dumps(_CGMLST_COHORT), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    _write_results(tmp_path)
    return tmp_path


@pytest.fixture
def engine(home: Path, monkeypatch):
    monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc(0))
    monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
    monkeypatch.setattr(eng, "_memory_arbiter", lambda: _NoopArbiter())
    e = eng.DbosTaskEngine(home)
    yield e
    eng.shutdown_dbos()


def _wait(e, tid: str, timeout_s: float = 30.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = e.status(tid)
        if st.state != TaskState.RUNNING:
            return st
        time.sleep(0.2)
    return e.status(tid)


def _run_analyze(engine) -> None:
    tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
    assert _wait(engine, tid).state == TaskState.SUCCEEDED


# ---------------------------------------------------------------------------
# 纯函数：证据链 + 幂等入库
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_no_run_record_yields_valid_fallback(self, tmp_path: Path):
        prov = eng._analysis_provenance(tmp_path, "missing-run")
        assert prov["pipeline_version"]
        assert prov["tool_versions"]  # 保证 ANALYSIS 校验通过

    def test_database_versions_from_run_record(self, tmp_path: Path):
        wf = tmp_path / "workflows" / "bacmap"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "config.yaml").write_text("iqtree_seed: 42\n", encoding="utf-8")
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "manifest.json").write_text(
            json.dumps({"databases": [{"name": "gside:marker", "version": "2026-01"}]}),
            encoding="utf-8",
        )
        run = runs.create_run(
            workflow="bacmap",
            workflow_dir=wf,
            strain_ids=[],
            db_path=tmp_path / "runs.sqlite",
            refs_dir=refs,
        )
        prov = eng._analysis_provenance(tmp_path, run.run_id)
        assert prov["database_versions"] == {"gside:marker": "2026-01"}
        assert prov["tool_versions"]
        assert prov["pipeline_version"]


class TestIngestObject:
    def test_idempotent_same_object_id(self, tmp_path: Path):
        prov = {"pipeline_version": "v1", "database_versions": {}, "tool_versions": {"x": "1"}}
        oid1 = eng._ingest_analysis_object(
            tmp_path, "k:s:r", "s", {"analysis_type": "sample_analysis"}, prov, None
        )
        oid2 = eng._ingest_analysis_object(
            tmp_path, "k:s:r", "s", {"analysis_type": "sample_analysis"}, prov, None
        )
        assert oid1 == oid2 == "k:s:r"
        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            assert len(gos.list_by_type(ObjectType.ANALYSIS)) == 1


class TestWorkflowGit:
    def test_non_repo_is_empty(self, tmp_path: Path):
        assert runs._workflow_git(tmp_path) == ("", False)


class TestReadPathsConsistent:
    def test_gom_tools_all_use_gom_db(self):
        assert tools_services._GOM_DB == config.GOM_DB
        assert tools_pipeline._REFLECTION_DB_PATH == config.GOM_DB


# ---------------------------------------------------------------------------
# 端到端：analyze → GOM 入库 → 工具读回
# ---------------------------------------------------------------------------


class TestAnalyzeIngestEndToEnd:
    def test_analysis_objects_written(self, engine, home: Path):
        _run_analyze(engine)
        with GenomeObjectService(home / "gom.sqlite") as gos:
            objs = gos.list_by_type(ObjectType.ANALYSIS)
        kinds = {(o.strain_id, o.payload.get("analysis_type")) for o in objs}
        assert ("SAM-001", "sample_analysis") in kinds
        assert ("SAM-001", "cgmlst_profile") in kinds
        assert ("cohort:salmonella-snp", "snp_cohort") in kinds
        assert ("cohort:salmonella-cgmlst", "cgmlst_cohort") in kinds

        sample_obj = next(o for o in objs if o.payload.get("analysis_type") == "sample_analysis")
        assert sample_obj.payload["serotype"] == {"sistr": "Typhimurium"}
        assert sample_obj.payload["mlst"].startswith("FILE")
        assert sample_obj.payload["run_id"] == "run-1"
        assert sample_obj.pipeline_version
        assert sample_obj.tool_versions or sample_obj.database_versions

        prof = next(o for o in objs if o.payload.get("analysis_type") == "cgmlst_profile")
        assert prof.payload["n_loci"] == 3
        assert prof.payload["n_total"] == 3

    def test_genotype_index_and_search_samples(self, engine, home: Path, monkeypatch):
        _run_analyze(engine)
        gom_db = home / "gom.sqlite"
        from bacmap.store.strain_index import StrainGenotypeIndex

        idx = StrainGenotypeIndex(gom_db)
        try:
            assert idx.count() == 1
            hits = idx.search(serotype="Typhimurium")
            assert [h.strain_id for h in hits] == ["SAM-001"]
        finally:
            idx.close()

        monkeypatch.setattr(tools_services, "_GOM_DB", gom_db)
        out = json.loads(tools_services.search_samples({"serotype": "Typhimurium"}))
        assert out["count"] == 1
        assert out["results"][0]["strain_id"] == "SAM-001"

    def test_snp_tree_reads_gom_cohort(self, engine, home: Path, monkeypatch):
        _run_analyze(engine)
        monkeypatch.setattr(tools_services, "_GOM_DB", home / "gom.sqlite")
        out = json.loads(tools_services.snp_tree({}))
        assert out["source"] == "gom"
        assert out["n_snp_sites"] == 120
        assert out["tree_newick"].startswith("(SAM-001")

    def test_review_flags_roundtrip(self, engine, home: Path, monkeypatch):
        _run_analyze(engine)
        from bacmap.core.verify.nli_reflector import record_reflection_event
        from bacmap.core.verify.nli_types import ReflectionResult

        reflection = ReflectionResult(
            verdicts=(),
            verifiable_count=2,
            contradicted_count=1,
            contradiction_rate=0.5,
            needs_human_review=True,
            threshold=0.3,
        )
        gom_db = home / "gom.sqlite"
        assert record_reflection_event(gom_db, "SAM-001", reflection) is True

        monkeypatch.setattr(tools_services, "_GOM_DB", gom_db)
        out = json.loads(tools_services.review_flags({}))
        assert out["total"] == 1
        assert out["events"][0]["sample_id"] == "SAM-001"
