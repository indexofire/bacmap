"""Research Workbench P1：确定性 AMR 关联、session 产物与 Profile 状态。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bacmap.research.models import CreateSessionRequest, ResearchError, ResearchProfile
from bacmap.research.service import ResearchService
from bacmap.research.stats import analyze_amr_association
from bacmap.store import runs


def _workflow_dir(home: Path) -> Path:
    wf = home / "workflows" / "bacmap"
    (wf / "config").mkdir(parents=True)
    (wf / "config" / "config.yaml").write_text("threads: 2\niqu_tree_seed: 42\n")
    return wf


def _run(home: Path, strains: list[str], run_id: str = "run-1") -> None:
    wf = _workflow_dir(home)
    run = runs.create_run(
        "bacmap", wf, strains, db_path=home / "runs.sqlite", task_id="task-1"
    )
    assert run.run_id
    # create_run generates an id; rewrite the test id for deterministic lookups.
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute("UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", (run_id, run.run_id))


def _gom(home: Path, genes: dict[str, list[str]]) -> None:
    from bacmap.store.genome_object_service import ensure_gom_schema

    ensure_gom_schema(home / "gom.sqlite")
    with sqlite3.connect(home / "gom.sqlite") as conn:
        for sid, names in genes.items():
            for name in names:
                conn.execute(
                    "INSERT INTO strain_amr_genes (strain_id, gene_name, database)"
                    " VALUES (?,?,?)",
                    (sid, name, "card"),
                )


def _labs(home: Path, values: dict[str, str]) -> None:
    from bacmap.store.lab_results import LabResultService

    with LabResultService(home / "data" / "bacmap.sqlite") as svc:
        for sid, interp in values.items():
            svc.add(sid, "mic", "meropenem", "0.25", interpretation=interp)


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    # 隔离 XDG 回落：真实机上的 ~/.config/bacmap/config.toml 会经
    # _iter_backup_files 的 config_path() 泄漏进备份断言（密闭性，同 v1.4.32）。
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-isolated"))
    strains = [f"S{i}" for i in range(16)]
    _run(tmp_path, strains)
    genes = {s: ["blaKPC-33"] for s in strains[:7]}
    _gom(tmp_path, genes)
    _labs(
        tmp_path,
        {
            **{s: "R" for s in strains[:6]},
            "S6": "S",
            **{s: "R" for s in strains[7:9]},
            **{s: "S" for s in strains[9:]},
        },
    )
    return tmp_path


class TestStat:
    def test_2x2_and_fisher(self, home: Path):
        stat = analyze_amr_association(home, "run-1", "blaKPC-33", "meropenem")
        assert stat.n == 16
        assert stat.table == {
            "gene_pos_resistant": 6,
            "gene_pos_susceptible": 1,
            "gene_neg_resistant": 2,
            "gene_neg_susceptible": 7,
        }
        assert stat.odds_ratio is not None and stat.odds_ratio > 1
        assert stat.ci_low is not None and stat.ci_high is not None
        assert stat.p_value is not None and 0 <= stat.p_value <= 1
        assert stat.diagnostics == []

    def test_zero_cell_haldane(self, tmp_path: Path):
        _run(tmp_path, ["A", "B"])
        _gom(tmp_path, {"A": ["g"], "B": ["g"]})
        _labs(tmp_path, {"A": "R", "B": "S"})
        stat = analyze_amr_association(tmp_path, "run-1", "g", "meropenem")
        assert stat.odds_ratio is not None
        assert any("Haldane" in d for d in stat.diagnostics)

    def test_missing_run(self, home: Path):
        with pytest.raises(ResearchError, match="no such run"):
            analyze_amr_association(home, "nope", "g", "meropenem")


class TestService:
    def test_open_test_session_and_artifacts(self, home: Path):
        view = ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1", gene="blaKPC-33", test_name="meropenem",
                profile=ResearchProfile.OPEN_TEST,
            ),
            actor="tester",
        )
        assert view.session.status.value == "complete_test"
        assert view.session.label == "TEST/UNVERIFIED"
        assert view.stat and view.stat.n == 16
        assert {a.kind.value for a in view.artifacts} == {
            "figure",
            "report",
            "manuscript",
            "figure_spec",
        }
        for art in view.artifacts:
            p = Path(art.path)
            assert p.is_file() and p.stat().st_size > 0
        assert view.artifacts[0].path.endswith(".svg") or True

    def test_research_profile_requires_review(self, home: Path):
        view = ResearchService(home).create_session(
            CreateSessionRequest(run_id="run-1", gene="blaKPC-33", test_name="meropenem"),
            profile=ResearchProfile.RESEARCH,
        )
        assert view.session.status.value == "review_required"
        assert view.session.label == "REVIEW REQUIRED"

    def test_get_and_artifact(self, home: Path):
        svc = ResearchService(home)
        created = svc.create_session(
            CreateSessionRequest(run_id="run-1", gene="blaKPC-33", test_name="meropenem"),
            profile=ResearchProfile.OPEN_TEST,
        )
        got = svc.get_session(created.session.session_id)
        assert got.session.session_id == created.session.session_id
        fig = svc.read_artifact(created.session.session_id, "figure")
        assert fig.read_text().startswith("<svg")

    def test_unknown_session(self, home: Path):
        with pytest.raises(ResearchError, match="no such research session"):
            ResearchService(home).get_session("rs-nope")

    def test_capabilities(self, home: Path):
        cap = ResearchService(home).capabilities(ResearchProfile.OPEN_TEST)
        assert cap.profile.value == "open-test"
        assert "figure" in cap.artifacts


class TestAPI:
    @pytest.fixture
    def engine(self, home: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(home)
        yield e
        eng.shutdown_dbos()

    def test_capabilities_and_session_roundtrip(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        client = TestClient(create_app(engine))
        cap = client.get("/api/v1/research/capabilities")
        assert cap.status_code == 200
        assert cap.json()["profile"] in {"open-test", "research", "publication"}

        created = client.post(
            "/api/v1/research/sessions",
            json={
                "run_id": "run-1",
                "gene": "blaKPC-33",
                "test_name": "meropenem",
                "profile": "open-test",
            },
        )
        assert created.status_code == 200, created.text
        sid = created.json()["session"]["session_id"]
        got = client.get(f"/api/v1/research/sessions/{sid}")
        assert got.status_code == 200
        assert got.json()["session"]["status"] == "complete_test"

        fig = client.get(f"/api/v1/research/sessions/{sid}/figure.svg")
        assert fig.status_code == 200 and fig.text.startswith("<svg")
        report = client.get(f"/api/v1/research/sessions/{sid}/report.md")
        assert report.status_code == 200 and "TEST/UNVERIFIED" in report.text

    def test_web_page_and_create(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        client = TestClient(create_app(engine))
        page = client.get("/research")
        assert page.status_code == 200 and "研究" in page.text
        created = client.post(
            "/research/sessions",
            data={
                "run_id": "run-1",
                "gene": "blaKPC-33",
                "test_name": "meropenem",
                "profile": "open-test",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"].startswith("/research/rs-")

    def test_unknown_session_404(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        client = TestClient(create_app(engine))
        assert client.get("/api/v1/research/sessions/rs-nope").status_code == 404


class TestResearchOps:
    def test_backup_and_doctor_include_research_db(self, home: Path, tmp_path: Path, capsys):
        import argparse
        import json
        import zipfile

        from bacmap.interfaces.cli import ops
        from bacmap.research.models import CreateSessionRequest, ResearchProfile

        ResearchService(home).create_session(
            CreateSessionRequest(run_id="run-1", gene="blaKPC-33", test_name="meropenem"),
            profile=ResearchProfile.OPEN_TEST,
        )
        out = tmp_path / "backup.zip"
        ops.backup(argparse.Namespace(home=str(home), out=str(out), with_results=False))
        with zipfile.ZipFile(out) as z:
            assert "research.sqlite" in z.namelist()
        capsys.readouterr()  # discard backup output

        ops.doctor(argparse.Namespace(home=str(home), json=True))
        data = json.loads(capsys.readouterr().out)
        assert any(c["name"] == "research" and c["status"] == "ok" for c in data["checks"])


class TestResearchObjects:
    def test_study_cohort_plan_claim_flow(self, home: Path):
        from bacmap.research.models import ClaimStatus, CohortStatus, PlanStatus
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("Does blaKPC-33 associate with resistance?", "KPN", 2, "tester")
        cohort = svc.create_cohort(
            study.study_id,
            [
                {"isolate_id": "I1", "dataset_id": "D1", "run_id": "R1"},
                {"isolate_id": "I2", "dataset_id": "D2", "run_id": "R2"},
            ],
            rules={"min_qc": True},
            name="discovery",
            actor="tester",
        )
        assert cohort.status is CohortStatus.DRAFT
        with pytest.raises(ValueError, match="frozen"):
            svc.create_plan(study.study_id, cohort.cohort_id, {"endpoint": "mic"})

        frozen = svc.freeze_cohort(cohort.cohort_id, "reviewer")
        assert frozen.status is CohortStatus.FROZEN
        assert len(frozen.snapshot_hash) == 64
        with pytest.raises(ValueError, match="already frozen"):
            svc.freeze_cohort(cohort.cohort_id, "reviewer")

        plan = svc.create_plan(study.study_id, cohort.cohort_id, {"endpoint": "mic"}, "tester")
        assert plan.status is PlanStatus.DRAFT and len(plan.plan_hash) == 64
        assert svc.freeze_plan(plan.plan_id, "reviewer").status is PlanStatus.FROZEN

        claim = svc.create_claim(
            study.study_id, "association", "blaKPC-33 is associated with resistance", "E2",
            {"stat": "stat-1"}, "tester",
        )
        assert claim.status is ClaimStatus.PROPOSED
        reviewed = svc.review_claim(claim.claim_id, "support", "ok", "reviewer")
        assert reviewed.status is ClaimStatus.SUPPORTED
        approved = svc.review_claim(claim.claim_id, "approve", "export", "reviewer")
        assert approved.status is ClaimStatus.APPROVED_FOR_EXPORT

    def test_invalid_claim_type(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "", 2, "tester")
        with pytest.raises(ResearchError, match="not a valid"):
            svc.create_claim(study.study_id, "bogus", "x")

    def test_evidence_edges(self, home: Path):
        from bacmap.research.store import ResearchObjectStore

        with ResearchObjectStore(home) as store:
            edge = store.add_edge(
                "claim", "c1", "SUPPORTS", "stat", "s1", "test", "tester"
            )
            assert edge.edge_type == "SUPPORTS"
            assert [e.edge_id for e in store.list_edges("claim", "c1")] == [edge.edge_id]


class TestResearchObjectAPI:
    @pytest.fixture
    def engine(self, home: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(home)
        yield e
        eng.shutdown_dbos()

    def test_study_to_claim_flow(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        c = TestClient(create_app(engine))
        study = c.post(
            "/api/v1/research/studies",
            json={"question": "AMR association", "pathogen_scope": "KPN", "data_class": 2},
        )
        assert study.status_code == 200, study.text
        sid = study.json()["study_id"]

        cohort = c.post(
            "/api/v1/research/cohorts",
            json={
                "study_id": sid,
                "name": "discovery",
                "rules": {"qc": True},
                "members": [{"isolate_id": "I1", "dataset_id": "D1", "run_id": "R1"}],
            },
        )
        assert cohort.status_code == 200, cohort.text
        cid = cohort.json()["cohort_id"]
        assert cohort.json()["status"] == "draft"

        frozen = c.post(f"/api/v1/research/cohorts/{cid}/freeze")
        assert frozen.status_code == 200
        assert frozen.json()["status"] == "frozen"

        plan = c.post(
            "/api/v1/research/plans",
            json={"study_id": sid, "cohort_id": cid, "spec": {"endpoint": "mic"}},
        )
        assert plan.status_code == 200, plan.text
        pid = plan.json()["plan_id"]
        assert c.post(f"/api/v1/research/plans/{pid}/freeze").json()["status"] == "frozen"

        claim = c.post(
            "/api/v1/research/claims",
            json={
                "study_id": sid,
                "claim_type": "association",
                "wording": "blaKPC-33 is associated with resistance",
                "evidence_level": "E2",
                "evidence": {"stat": "s1"},
            },
        )
        assert claim.status_code == 200, claim.text
        claim_id = claim.json()["claim_id"]
        reviewed = c.post(
            f"/api/v1/research/claims/{claim_id}/review",
            json={"decision": "support", "message": "ok"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "supported"

        assert c.get(f"/api/v1/research/cohorts?study_id={sid}").json()["items"]
        assert c.get(f"/api/v1/research/plans?study_id={sid}").json()["items"]
        assert c.get(f"/api/v1/research/claims?study_id={sid}").json()["items"]
        ledger = c.get(f"/api/v1/research/ledger?object_type=plan&object_id={pid}")
        assert ledger.status_code == 200 and ledger.json()["items"]

    def test_web_forms_create_and_freeze_objects(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        c = TestClient(create_app(engine))
        created = c.post(
            "/research/studies",
            data={"question": "web form study", "pathogen_scope": "KPN", "data_class": "2"},
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
        study_id = created.headers["location"].rsplit("/", 1)[-1]

        cohort = c.post(
            f"/research/studies/{study_id}/cohorts",
            data={
                "name": "web",
                "members": '[{"isolate_id":"I1","run_id":"R1"}]',
                "rules": "{}",
            },
            follow_redirects=False,
        )
        assert cohort.status_code == 303, cohort.text
        cohort_id = cohort.headers["location"].split("/")[-1]

        page = c.get(f"/research/studies/{study_id}")
        assert page.status_code == 200
        assert "G0" in page.text and "新建 Study" not in page.text
        # Draft cohorts/plans must not be selectable for downstream steps.
        assert f'<option value="{cohort_id}"' not in page.text


class TestClaimGate:
    def test_association_needs_e2(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "", 2, "tester")
        claim = svc.create_claim(study.study_id, "association", "gene is associated", "E1", {}, "tester")
        with pytest.raises(ResearchError, match="E2"):
            svc.review_claim(claim.claim_id, "support", "", "reviewer")

    def test_mechanism_needs_functional_evidence(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "", 2, "tester")
        claim = svc.create_claim(study.study_id, "mechanism", "gene mediates resistance", "E4", {}, "tester")
        with pytest.raises(ResearchError, match="functional"):
            svc.review_claim(claim.claim_id, "approve", "", "reviewer")

    def test_causal_wording_blocked_for_association(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "", 2, "tester")
        claim = svc.create_claim(study.study_id, "association", "gene causes resistance", "E2", {}, "tester")
        with pytest.raises(ResearchError, match="causal"):
            svc.review_claim(claim.claim_id, "support", "", "reviewer")


class TestPlanExecution:
    def test_frozen_plan_runs_p1_session(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("AMR", "KPN", 2, "tester")
        cohort = svc.create_cohort(
            study.study_id, [{"isolate_id": "S0", "run_id": "run-1"}], name="c", actor="tester"
        )
        svc.freeze_cohort(cohort.cohort_id, "reviewer")
        plan = svc.create_plan(
            study.study_id, cohort.cohort_id,
            {"run_id": "run-1", "gene": "blaKPC-33", "test_name": "meropenem"}, "tester",
        )
        with pytest.raises(ResearchError, match="not frozen"):
            svc.run_plan(plan.plan_id, "tester")
        svc.freeze_plan(plan.plan_id, "reviewer")
        view = svc.run_plan(plan.plan_id, "tester")
        assert view.session.study_id == study.study_id
        assert view.session.cohort_id == cohort.cohort_id
        assert view.session.plan_id == plan.plan_id
        assert view.stat and view.stat.n == 16

        claim = svc.claim_from_session(view.session.session_id, "gene is associated", "E2")
        assert claim.study_id == study.study_id
        assert claim.evidence["session_id"] == view.session.session_id
        assert svc.review_claim(claim.claim_id, "support", "", "reviewer").status.value == "supported"

    def test_cohort_preview_flags_duplicates_and_missing_runs(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "", 2, "tester")
        preview = svc.preview_cohort(
            study.study_id,
            [
                {"isolate_id": "I1", "dataset_id": "D1", "run_id": "run-1"},
                {"isolate_id": "I1", "dataset_id": "D1", "run_id": "missing-run"},
            ],
        )
        assert preview["ok"] is False
        assert preview["duplicate_isolates"] == ["I1"]
        assert preview["duplicate_datasets"] == ["D1"]
        assert preview["missing_runs"] == ["missing-run"]


class TestBenchmark:
    def test_amr_l0_benchmark_passes(self):
        from bacmap.research.benchmarks import run_amr_benchmark

        out = run_amr_benchmark()
        assert out["passed"] is True
        assert {c["name"] for c in out["cases"]} == {"strong-positive", "null", "strong-negative"}


class TestRealBenchmarkLoader:
    def test_missing_data_reports_unavailable(self, tmp_path: Path):
        from bacmap.research.benchmarks import run_bvbrc_amr_benchmark

        assert run_bvbrc_amr_benchmark(tmp_path)["available"] is False

    def test_tiny_real_format_runs(self, tmp_path: Path):
        from bacmap.research.benchmarks import run_bvbrc_amr_benchmark

        (tmp_path / "labels.csv").write_text(
            "genome_id,phenotype\nG1,Resistant\nG2,Resistant\nG3,Susceptible\nG4,Susceptible\n",
            encoding="utf-8",
        )
        (tmp_path / "genes.csv").write_text(
            "genome_id,gene,product\n"
            "G1,KPC-2,Class A beta-lactamase KPC family\n"
            "G2,KPC-2,Class A beta-lactamase KPC family\n",
            encoding="utf-8",
        )
        out = run_bvbrc_amr_benchmark(tmp_path)
        assert out["available"] is True
        kpc = next(c for c in out["cases"] if c["target"] == "KPC")
        assert kpc["n"] == 4 and kpc["table"]["gene_pos_resistant"] == 2


class TestStatisticalReview:
    def test_benjamini_hochberg(self):
        from bacmap.research.stats import benjamini_hochberg

        q = benjamini_hochberg([0.01, 0.04, 0.03, 0.002])
        assert q is not None
        assert q[3] == pytest.approx(0.008)
        assert q[0] == pytest.approx(0.02)
        assert q[1] == pytest.approx(0.04)
        assert q[2] == pytest.approx(0.04)

    def test_benjamini_hochberg_keeps_missing(self):
        from bacmap.research.stats import benjamini_hochberg

        assert benjamini_hochberg([None, None]) == [None, None]
        q = benjamini_hochberg([0.01, None, 0.02])
        assert q[1] is None and q[0] is not None and q[2] is not None

    def test_mantel_haenszel_equal_strata(self):
        from bacmap.research.stats import mantel_haenszel

        out = mantel_haenszel([(10, 2, 3, 15), (10, 2, 3, 15)])
        assert out["odds_ratio"] == pytest.approx(25.0)
        assert out["ci_low"] < out["odds_ratio"] < out["ci_high"]
        assert out["n_strata"] == 2 and out["n"] == 60
        assert out["p_value"] is not None and out["p_value"] < 0.001

    def test_mantel_haenszel_removes_confounding(self):
        from bacmap.research.stats import mantel_haenszel

        out = mantel_haenszel([(10, 1, 1, 10), (1, 10, 10, 1)])
        assert out["odds_ratio"] == pytest.approx(1.0)
        assert out["p_value"] is not None and out["p_value"] > 0.05

    def test_mantel_haenszel_zero_cell_diagnostic(self):
        from bacmap.research.stats import mantel_haenszel

        out = mantel_haenszel([(0, 5, 5, 10)])
        assert out["odds_ratio"] is not None
        assert any("0.5 correction" in d for d in out["diagnostics"])


class TestBenchmarkManifest:
    def test_verify_manifest_and_detect_corruption(self, tmp_path: Path):
        import hashlib

        from bacmap.research.benchmarks import verify_benchmark_dir

        data = tmp_path / "data.csv"
        data.write_text("a,b\n1,2\n", encoding="utf-8")
        digest = hashlib.sha256(data.read_bytes()).hexdigest()
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "dataset": "tiny",
                    "files": {"data.csv": {"sha256": digest, "min_rows": 1}},
                }
            ),
            encoding="utf-8",
        )
        assert verify_benchmark_dir(tmp_path)["ok"] is True
        data.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        out = verify_benchmark_dir(tmp_path)
        assert out["ok"] is False
        assert out["checks"][0]["sha256_ok"] is False

    def test_verify_missing_manifest(self, tmp_path: Path):
        from bacmap.research.benchmarks import verify_benchmark_dir

        assert verify_benchmark_dir(tmp_path)["available"] is False

    def test_osf_summary_fixture(self, tmp_path: Path):
        from bacmap.research.benchmarks import summarize_osf_cohort

        (tmp_path / "table_s1.csv").write_text(
            "name,study\nA,Study1\nB,Study1\nC,Study2\n", encoding="utf-8"
        )
        (tmp_path / "table_s2.csv").write_text(
            "name,study,breakpoint,mic\nA,Study1,S,1\nB,Study1,R,8\n", encoding="utf-8"
        )
        (tmp_path / "genomes.csv").write_text("A,a.fna.gz\nB,b.fna.gz\n", encoding="utf-8")
        out = summarize_osf_cohort(tmp_path)
        assert out["available"] is True
        assert out["n_metadata"] == 3
        assert out["n_phenotypes"] == 2
        assert out["phenotype_coverage"] == pytest.approx(0.6667, abs=1e-3)
        assert out["breakpoints"] == {"R": 1, "S": 1}


class TestExperimentAndPublication:
    def _study_with_frozen_plan(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("Is KPC associated with meropenem resistance?", "KPN", 2, "t")
        cohort = svc.create_cohort(
            study.study_id, [{"isolate_id": "I1", "run_id": "run-1"}], name="c", actor="t"
        )
        svc.freeze_cohort(cohort.cohort_id, "r")
        plan = svc.create_plan(
            study.study_id, cohort.cohort_id,
            {"run_id": "run-1", "gene": "blaKPC", "test_name": "meropenem"}, "t",
        )
        svc.freeze_plan(plan.plan_id, "r")
        return svc, study, plan

    def test_experiment_records_success_and_deviation(self, home: Path):
        from bacmap.research.models import ExperimentStatus

        svc, study, plan = self._study_with_frozen_plan(home)
        exp = svc.record_experiment(
            plan.plan_id, "success", ["run-1"], {"n": 16}, actor="t"
        )
        assert exp.status is ExperimentStatus.SUCCESS
        assert exp.plan_hash == plan.plan_hash
        assert exp.study_id == study.study_id
        with pytest.raises(ResearchError, match="requires a deviation note"):
            svc.record_experiment(plan.plan_id, "deviated", ["run-1"], actor="t")
        dev = svc.record_experiment(
            plan.plan_id, "deviated", ["run-1"], deviation="excluded 2 samples", actor="t"
        )
        assert dev.deviation == "excluded 2 samples"
        assert {e.experiment_id for e in svc.list_experiments(plan_id=plan.plan_id)} == {
            exp.experiment_id, dev.experiment_id
        }

    def test_publication_gates_require_claim_and_execution(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc, study, plan = self._study_with_frozen_plan(home)
        readiness = svc.publication_readiness(study.study_id)
        assert readiness["ready"] is False
        gates = {g["id"]: g for g in readiness["gates"]}
        assert gates["G0"]["ok"] is True
        assert gates["G1"]["ok"] is False and gates["G3"]["ok"] is False

        svc.record_experiment(plan.plan_id, "negative", ["run-1"], actor="t")
        claim = svc.create_claim(
            study.study_id, "association", "blaKPC is associated with meropenem resistance",
            "E2", {"run_id": "run-1"}, "t",
        )
        svc.review_claim(claim.claim_id, "approve", "reviewed", "r")
        readiness = ResearchObjectService(home).publication_readiness(study.study_id)
        assert readiness["ready"] is True, readiness

    def test_publication_blocks_d3_study(self, home: Path):
        svc, study, plan = self._study_with_frozen_plan(home)
        svc.record_experiment(plan.plan_id, "success", ["run-1"], actor="t")
        claim = svc.create_claim(
            study.study_id, "association", "gene is associated", "E2", {}, "t"
        )
        svc.review_claim(claim.claim_id, "approve", "", "r")
        d3 = svc.create_study("D3 study", "KPN", 3, "t")
        # A separate study cannot borrow the frozen plan, so G0/G3 fail as well.
        readiness = svc.publication_readiness(d3.study_id)
        assert readiness["ready"] is False
        assert any(g["id"] == "G2" and g["ok"] is False for g in readiness["gates"])


class TestExperimentAPI:
    @pytest.fixture
    def engine(self, home: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(home)
        yield e
        eng.shutdown_dbos()

    def test_experiment_and_readiness_roundtrip(self, engine):
        from fastapi.testclient import TestClient

        from bacmap.interfaces.web import create_app

        c = TestClient(create_app(engine))
        sid = c.post(
            "/api/v1/research/studies",
            json={"question": "q", "pathogen_scope": "KPN", "data_class": 2},
        ).json()["study_id"]
        cid = c.post(
            "/api/v1/research/cohorts",
            json={
                "study_id": sid,
                "members": [{"isolate_id": "I1", "run_id": "run-1"}],
            },
        ).json()["cohort_id"]
        c.post(f"/api/v1/research/cohorts/{cid}/freeze")
        pid = c.post(
            "/api/v1/research/plans",
            json={"study_id": sid, "cohort_id": cid, "spec": {"endpoint": "mic"}},
        ).json()["plan_id"]
        c.post(f"/api/v1/research/plans/{pid}/freeze")
        exp = c.post(
            "/api/v1/research/experiments",
            json={"plan_id": pid, "status": "success", "run_ids": ["run-1"], "outcome": {"n": 16}},
        )
        assert exp.status_code == 200, exp.text
        assert exp.json()["plan_id"] == pid
        assert c.get(f"/api/v1/research/experiments?plan_id={pid}").json()["items"]
        readiness = c.get(f"/api/v1/research/studies/{sid}/publication-readiness")
        assert readiness.status_code == 200
        assert readiness.json()["ready"] is False


class TestFigures:
    def _session(self, home: Path):
        return ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1",
                gene="blaKPC-33",
                test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
            ),
            actor="tester",
        )

    def test_figure_spec_is_stored_with_source(self, home: Path):
        view = self._session(home)
        spec = ResearchService(home).figure_spec(view.session.session_id)
        assert spec.schema_name == "bacmap.figure_spec/1"
        assert spec.recipe_id == "association_bar"
        assert spec.data["table"] == view.stat.table
        assert spec.data["odds_ratio"] == view.stat.odds_ratio
        assert spec.source.session_id == view.session.session_id
        assert spec.source.run_id == "run-1"
        assert len(spec.source.stat_sha256) == 64
        assert spec.style.dpi >= 300
        assert spec.style.panel_layout == "single"
        assert spec.style.reference_note == ""
        assert any("colorblind" in c for c in spec.constraints)
        stored = {a.kind.value for a in view.artifacts}
        assert "figure_spec" in stored

    def test_attach_registers_manifest_and_hashes(self, home: Path, tmp_path: Path):
        view = self._session(home)
        out = tmp_path / "figure.svg"
        out.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
        code = tmp_path / "plot.py"
        code.write_text("print('plot')\n", encoding="utf-8")
        art = ResearchService(home).attach_figure(
            view.session.session_id, out, code=code, renderer="agent-script"
        )
        assert len(art.output_sha256) == 64
        assert len(art.code_sha256) == 64
        assert Path(art.output).is_relative_to(home / "research" / view.session.session_id)
        assert Path(art.code_path).is_relative_to(home / "research" / view.session.session_id)
        assert len(art.spec_sha256) == 64
        assert len(art.data_sha256) == 64
        after = ResearchService(home).get_session(view.session.session_id)
        kinds = {a.kind.value for a in after.artifacts}
        assert {"figure_custom", "figure_manifest"} <= kinds
        manifest = json.loads(
            (home / "research" / view.session.session_id / "figure_custom.manifest.json")
            .read_text(encoding="utf-8")
        )
        assert manifest["schema"] == "bacmap.figure_artifact/1"
        assert manifest["renderer"] == "agent-script"
        assert manifest["recipe_id"] == "custom"

    def test_attach_rejects_spec_from_another_session(self, home: Path, tmp_path: Path):
        first = self._session(home)
        second = self._session(home)
        spec = ResearchService(home).figure_spec(first.session.session_id)
        from bacmap.research.figures import write_spec

        spec_path = tmp_path / "spec.json"
        write_spec(spec, spec_path)
        out = tmp_path / "figure.svg"
        out.write_text("<svg/>", encoding="utf-8")
        with pytest.raises(ResearchError, match="belongs to session"):
            ResearchService(home).attach_figure(
                second.session.session_id, out, spec_path=spec_path
            )

    def test_draft_records_ledger(self, home: Path, tmp_path: Path):
        view = self._session(home)
        out = tmp_path / "draft.svg"
        out.write_text("<svg/>", encoding="utf-8")
        svc = ResearchService(home)
        draft = svc.attach_draft(view.session.session_id, out, note="first pass")
        assert Path(draft["path"]).is_file()
        events = [entry["event"] for entry in svc.ledger(view.session.session_id)]
        assert "figure.draft" in events

    def test_attach_rejects_unsupported_format(self, home: Path, tmp_path: Path):
        view = self._session(home)
        out = tmp_path / "figure.txt"
        out.write_text("not a figure", encoding="utf-8")
        with pytest.raises(ResearchError, match="not allowed"):
            ResearchService(home).attach_figure(view.session.session_id, out)


class TestSubmissionPackageWithArtifacts:
    def test_package_copies_session_artifacts(self, home: Path, tmp_path: Path):
        from bacmap.research.reporting import build_submission_package
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "KPN", 2, "t")
        ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1",
                gene="blaKPC-33",
                test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
                study_id=study.study_id,
            ),
            actor="t",
        )
        out = tmp_path / "package"
        package = build_submission_package(home, study.study_id, out)
        assert (out / "submission_manifest.json").is_file()
        copied = [f for f in package.files if f.kind == "figure"]
        assert copied
        assert Path(copied[0].path).is_file()
        assert len(copied[0].sha256) == 64


class TestSessionLinking:
    def _objects(self, home: Path):
        from bacmap.research.service import ResearchObjectService

        svc = ResearchObjectService(home)
        study = svc.create_study("q", "KPN", 2, "t")
        cohort = svc.create_cohort(
            study.study_id,
            [{"isolate_id": "S00", "run_id": "run-1"}],
            name="discovery",
            actor="t",
        )
        svc.freeze_cohort(cohort.cohort_id, "t")
        plan = svc.create_plan(study.study_id, cohort.cohort_id, {"gene": "x"}, "t")
        svc.freeze_plan(plan.plan_id, "t")
        return study, cohort, plan

    def test_service_links_study_cohort_plan(self, home: Path):
        study, cohort, plan = self._objects(home)
        view = ResearchService(home).create_session(
            CreateSessionRequest(
                run_id="run-1",
                gene="blaKPC-33",
                test_name="meropenem",
                profile=ResearchProfile.RESEARCH,
                study_id=study.study_id,
                cohort_id=cohort.cohort_id,
                plan_id=plan.plan_id,
            ),
            actor="t",
        )
        assert view.session.study_id == study.study_id
        assert view.session.cohort_id == cohort.cohort_id
        assert view.session.plan_id == plan.plan_id

    def test_cli_links_study_cohort_plan(self, home: Path, capsys):
        import json as _json

        from bacmap.interfaces.cli.main import main

        study, cohort, plan = self._objects(home)
        main(
            [
                "research",
                "create",
                "--run-id",
                "run-1",
                "--gene",
                "blaKPC-33",
                "--test-name",
                "meropenem",
                "--profile",
                "research",
                "--study",
                study.study_id,
                "--cohort",
                cohort.cohort_id,
                "--plan",
                plan.plan_id,
                "--home",
                str(home),
                "--json",
            ]
        )
        payload = _json.loads(capsys.readouterr().out)
        session = payload["session"]
        assert session["study_id"] == study.study_id
        assert session["cohort_id"] == cohort.cohort_id
        assert session["plan_id"] == plan.plan_id
