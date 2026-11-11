"""ADR-22/23：高级统计外部化 + research 计划类型。

覆盖：AnalysisSpec 校验、R 脚本确定性渲染、结果归一、ResearchParams 校验、
research 工作流（session 确定性 / advstats 沙箱 monkeypatch）与计划输入指纹。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from bacmap.research import advstats
from bacmap.tasks.params import ResearchParams


def _workflow_dir(home: Path) -> Path:
    wf = home / "workflows" / "bacmap" / "config"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "config.yaml").write_text("threads: 2\n")
    return home / "workflows" / "bacmap"


def _run(home: Path, strains: list[str]) -> None:
    from bacmap.store import runs as runs_store

    _workflow_dir(home)
    run = runs_store.create_run(
        "bacmap", home / "workflows" / "bacmap", strains,
        db_path=home / "runs.sqlite", task_id="task-1",
    )
    with sqlite3.connect(home / "runs.sqlite") as conn:
        conn.execute(
            "UPDATE analysis_runs SET run_id = ? WHERE run_id = ?", ("run-1", run.run_id)
        )


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
def home(tmp_path: Path) -> Path:
    strains = [f"S{i}" for i in range(10)]
    _run(tmp_path, strains)
    _gom(tmp_path, {s: ["g"] for s in strains[:4]})
    _labs(tmp_path, {**{s: "R" for s in strains[:4]}, **{s: "S" for s in strains[4:]}})
    return tmp_path


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    """v1.10.24：研究计划测试对本地 [debug] enabled 配置免疫（debug 下
    PlanService 自动确认，round-trip 状态断言随环境漂移）。"""
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


class TestAnalysisSpec:
    def test_method_requirements(self):
        with pytest.raises(ValueError, match="mixed_logistic requires"):
            advstats.AnalysisSpec(method="mixed_logistic", data_path="/input/d.csv")
        with pytest.raises(ValueError, match="cox requires"):
            advstats.AnalysisSpec(
                method="cox", data_path="/input/d.csv", time="t", event="e"
            )

    def test_identifier_validation(self):
        with pytest.raises(ValueError, match="R column name"):
            advstats.AnalysisSpec(
                method="cox",
                data_path="/input/d.csv",
                time="t",
                event="e",
                predictors=["bad name!"],
            )

    def test_duplicate_columns_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            advstats.AnalysisSpec(
                method="cox",
                data_path="/input/d.csv",
                time="t",
                event="e",
                predictors=["x", "x"],
            )

    def test_valid_specs_per_method(self):
        specs = [
            advstats.AnalysisSpec(
                method="mixed_logistic", data_path="/input/d.csv",
                outcome="y", group="ward", predictors=["gene", "age"],
            ),
            advstats.AnalysisSpec(
                method="iptw", data_path="/input/d.csv",
                treatment="tx", outcome="y", confounders=["age", "sex"],
            ),
            advstats.AnalysisSpec(
                method="matching", data_path="/input/d.csv",
                treatment="tx", outcome="y", confounders=["age"],
            ),
            advstats.AnalysisSpec(
                method="survival_km", data_path="/input/d.csv",
                time="days", event="died", treatment="tx",
            ),
            advstats.AnalysisSpec(
                method="cox", data_path="/input/d.csv",
                time="days", event="died", predictors=["tx", "age"],
            ),
        ]
        assert all(s.model_extra is None for s in specs)


class TestRenderScript:
    def _spec(self, method: str, **kw) -> advstats.AnalysisSpec:
        base = dict(
            mixed_logistic=dict(outcome="y", group="ward", predictors=["gene"]),
            iptw=dict(treatment="tx", outcome="y", confounders=["age"]),
            matching=dict(treatment="tx", outcome="y", confounders=["age"]),
            survival_km=dict(time="days", event="died", treatment="tx"),
            cox=dict(time="days", event="died", predictors=["tx"]),
        )
        return advstats.AnalysisSpec(
            method=method, data_path="/input/ds-1/data.csv", **base[method], **kw
        )

    def test_each_method_renders_its_engine(self):
        expectations = {
            "mixed_logistic": ("glmer(", "(1 | ward)"),
            "iptw": ("weightit(", "svyglm("),
            "matching": ("matchit(", "svyglm("),
            "survival_km": ("survfit(", "survdiff("),
            "cox": ("coxph(", "cox.zph("),
        }
        for method, tokens in expectations.items():
            script = advstats.render_r_script(self._spec(method))
            for token in tokens:
                assert token in script, f"{method}: missing {token!r}"
            assert 'write(toJSON(payload' in script
            assert "/workspace/result.json" in script

    def test_render_is_deterministic(self):
        spec = self._spec("cox")
        assert advstats.render_r_script(spec) == advstats.render_r_script(spec)

    def test_relative_data_path_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            advstats.render_r_script(
                advstats.AnalysisSpec(
                    method="cox", data_path="relative.csv",
                    time="t", event="e", predictors=["x"],
                )
            )

    def test_tsv_uses_tab_delimiter(self):
        spec = advstats.AnalysisSpec(
            method="cox", data_path="/input/d.tsv",
            time="t", event="e", predictors=["x"],
        )
        assert 'sep="\\t"' in advstats.render_r_script(spec)


class TestSummarize:
    def test_normalization(self):
        payload = {
            "method": "cox", "ok": True, "n": 120, "n_used": 34,
            "estimates": [{"name": "tx", "hazard_ratio": 0.5, "p_value": 0.01}],
            "diagnostics": {"events": 34},
        }
        out = advstats.summarize(payload)
        assert out["schema"] == advstats.ADVSTATS_RESULT_SCHEMA
        assert out["title"].startswith("Cox")
        assert out["estimates"][0]["hazard_ratio"] == 0.5
        assert out["n_used"] == 34

    def test_failure_kept_honest(self):
        out = advstats.summarize(
            {"method": "mixed_logistic", "ok": False, "error": "convergence"}
        )
        assert out["ok"] is False
        assert out["error"] == "convergence"
        assert out["estimates"] == []


class TestResearchParams:
    def test_session_requires_fields(self):
        with pytest.raises(ValueError, match="run_id, gene and test_name"):
            ResearchParams(analysis="session", run_id="run-1")

    def test_session_valid(self):
        p = ResearchParams(
            analysis="session", run_id="run-1", gene="g", test_name="meropenem"
        )
        assert p.profile == "research"

    def test_advstats_validates_via_spec(self):
        with pytest.raises(ValueError):
            ResearchParams(
                analysis="advstats",
                method="cox",
                data_path="/abs/d.csv",
                time="t",
                event="e",
                predictors=[],
            )

    def test_advstats_data_path_must_be_absolute(self):
        with pytest.raises(ValueError, match="absolute"):
            ResearchParams(
                analysis="advstats", method="cox", data_path="rel.csv",
                time="t", event="e", predictors=["x"],
            )

    def test_advstats_spec_guest_path(self):
        p = ResearchParams(
            analysis="advstats", method="cox", data_path="/abs/d.csv",
            time="t", event="e", predictors=["x"],
        )
        spec = p.advstats_spec("/input/ds-1/data.csv")
        assert spec.data_path == "/input/ds-1/data.csv"


class _FakeSandboxResult:
    def __init__(self, returncode=0, result_payload: dict | None = None):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "" if returncode == 0 else "boom"
        self.backend = "fake"
        self.result_payload = result_payload


class TestResearchWorkflow:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng

        def fake_run(spec):
            result = _FakeSandboxResult(0)
            payload = {
                "method": "cox",
                "ok": True,
                "n": 120,
                "n_used": 34,
                "estimates": [
                    {"name": "tx", "hazard_ratio": 0.55,
                     "ci_low": 0.31, "ci_high": 0.98, "p_value": 0.041}
                ],
                "diagnostics": {"events": 34},
            }
            spec.workspace.joinpath("result.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            return result

        monkeypatch.setattr(eng, "_run_sandbox", fake_run)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def _wait(self, e, tid, timeout_s=30):
        from bacmap.tasks.spec import TaskState

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = e.status(tid)
            if st.state != TaskState.RUNNING:
                return st
            time.sleep(0.2)
        return e.status(tid)

    def test_session_kind_end_to_end(self, engine, home):
        from bacmap.tasks.spec import TaskState, TaskType

        tid = engine.submit(
            TaskType.RESEARCH,
            {
                "analysis": "session",
                "run_id": "run-1",
                "gene": "g",
                "test_name": "meropenem",
                "profile": "open-test",
            },
            "analyst",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.SUCCEEDED
        with sqlite3.connect(home / "research.sqlite") as conn:
            rows = conn.execute(
                "SELECT run_id, gene FROM analysis_sessions"
            ).fetchall()
        assert ("run-1", "g") in rows

    def test_advstats_kind_end_to_end(self, engine, home):
        from bacmap.tasks.spec import TaskState, TaskType

        data = home / "cohort.csv"
        data.write_text("days,died,tx\n1,1,0\n2,0,1\n", encoding="utf-8")
        tid = engine.submit(
            TaskType.RESEARCH,
            {
                "analysis": "advstats",
                "method": "cox",
                "data_path": str(data),
                "time": "days",
                "event": "died",
                "predictors": ["tx"],
            },
            "analyst",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.SUCCEEDED
        result_path = home / "research" / "advstats" / tid / "result.json"
        out = json.loads(result_path.read_text(encoding="utf-8"))
        assert out["method"] == "cox" and out["ok"] is True
        assert out["estimates"][0]["hazard_ratio"] == 0.55
        assert len(out["script_sha256"]) == 64
        script = (home / "workspaces" / tid / "advstats.R").read_text(encoding="utf-8")
        assert "coxph(" in script

    def test_advstats_missing_data_fails(self, engine, home):
        from bacmap.tasks.spec import TaskState, TaskType

        tid = engine.submit(
            TaskType.RESEARCH,
            {
                "analysis": "advstats",
                "method": "cox",
                "data_path": str(home / "nope.csv"),
                "time": "t",
                "event": "e",
                "predictors": ["x"],
            },
            "analyst",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.FAILED


class TestPlanIntegration:
    def test_research_task_in_plan_round_trip(self, home):
        from bacmap.application.plans import PlanService
        from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
        from bacmap.tasks.params import ResearchParams

        data = home / "cohort.csv"
        data.write_text("days,died,tx\n", encoding="utf-8")
        engine = DbosTaskEngine(home)
        svc = PlanService(engine, Path(engine.db))
        plan = svc.create(
            tasks=[
                ResearchParams(
                    analysis="advstats",
                    method="cox",
                    data_path=str(data),
                    time="days",
                    event="died",
                    predictors=["tx"],
                )
            ],
            rationale="cox on cohort",
            actor="tester",
        )
        # advstats 数据表进入输入指纹
        assert str(data) in plan.inputs
        assert plan.state.value == "awaiting_confirmation"

    def test_plan_hash_changes_with_data(self, home):
        from bacmap.application.plans import PlanService
        from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
        from bacmap.tasks.params import ResearchParams

        data = home / "cohort.csv"
        data.write_text("days,died,tx\n1,1,0\n", encoding="utf-8")
        engine = DbosTaskEngine(home)
        svc = PlanService(engine, Path(engine.db))
        task = ResearchParams(
            analysis="advstats", method="cox", data_path=str(data),
            time="days", event="died", predictors=["tx"],
        )
        p1 = svc.create(tasks=[task], rationale="r", actor="t")
        data.write_text("days,died,tx\n1,1,1\n", encoding="utf-8")
        p2 = svc.create(tasks=[task], rationale="r", actor="t")
        assert p1.plan_hash != p2.plan_hash
