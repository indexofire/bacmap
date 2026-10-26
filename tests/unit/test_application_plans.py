"""版本化计划（v1.5.1）：类型化参数、规范哈希、版本取代、确认幂等、输入指纹。"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from bacmap.application.errors import Conflict, NotFound, ValidationFailed
from bacmap.application.plans import (
    PlanService,
    PlanState,
    canonical_json,
    parse_tasks,
    plan_hash,
    plan_task_id,
)
from bacmap.tasks.params import AnalyzeParams, CurateParams, CurateScope, engine_params
from bacmap.tasks.spec import TaskId, TaskType


class FakeEngine:
    """记录提交；显式 task_id 幂等（与 DbosTaskEngine 契约一致）。"""

    def __init__(self, reject_index: int | None = None) -> None:
        self.calls: list[tuple[TaskType, dict[str, Any], str, str]] = []
        self.ids: set[str] = set()
        self.reject_index = reject_index
        self._lock = threading.Lock()

    def submit(self, task_type, params, submitted_by, *, task_id=None):
        with self._lock:
            if self.reject_index is not None and len(self.calls) == self.reject_index:
                self.calls.append((task_type, params, submitted_by, str(task_id)))
                raise ValueError("engine says no")
            self.calls.append((task_type, params, submitted_by, str(task_id)))
            self.ids.add(str(task_id))
            return TaskId(str(task_id))


@pytest.fixture
def svc(tmp_path: Path) -> tuple[PlanService, FakeEngine]:
    engine = FakeEngine()
    return PlanService(engine, tmp_path / "tasks.sqlite"), engine


def _analyze(*samples: str) -> AnalyzeParams:
    return AnalyzeParams(samples=list(samples))


class TestParams:
    def test_analyze_requires_exactly_one_input(self):
        with pytest.raises(ValueError, match="exactly one"):
            AnalyzeParams()
        with pytest.raises(ValueError, match="exactly one"):
            AnalyzeParams(samples=["A"], fasta_dir="/data")

    def test_rejects_unknown_fields_bad_ids_relative_dirs(self):
        with pytest.raises(ValueError):
            AnalyzeParams.model_validate({"samples": ["A"], "cores": 64})
        with pytest.raises(ValueError, match="invalid sample"):
            AnalyzeParams(samples=["../etc"])
        with pytest.raises(ValueError, match="absolute"):
            AnalyzeParams(fasta_dir="data/genomes")
        with pytest.raises(ValueError, match="species only"):
            AnalyzeParams(samples=["A"], species="SAL")

    def test_parse_tasks_discriminates_and_reports(self):
        tasks = parse_tasks(
            [{"task_type": "analyze", "samples": ["A"]}, {"task_type": "curate"}]
        )
        assert isinstance(tasks[0], AnalyzeParams) and isinstance(tasks[1], CurateParams)
        with pytest.raises(ValidationFailed, match="bogus"):
            parse_tasks([{"task_type": "bogus"}])

    def test_open_path_tasks_are_plannable(self):
        from bacmap.tasks.params import MineParams, WriteParams

        tasks = parse_tasks(
            [
                {
                    "task_type": "mine",
                    "objective": "按 ST 统计",
                    "script": "print(1)",
                    "input_paths": [],
                },
                {"task_type": "write", "objective": "写简报", "draft": "草稿"},
            ]
        )
        assert isinstance(tasks[0], MineParams) and isinstance(tasks[1], WriteParams)

    def test_mine_requires_script_and_absolute_paths(self):
        from bacmap.tasks.params import MineParams

        with pytest.raises(ValueError, match="script"):
            MineParams(objective="x", script="")
        with pytest.raises(ValueError, match="absolute"):
            MineParams(objective="x", script="print(1)", input_paths=["data/x"])
        with pytest.raises(ValueError, match="at most 20000"):
            MineParams(objective="x", script="x" * 40000)

    def test_engine_params_shape(self):
        assert engine_params(_analyze("A", "B")) == {"samples": ["A", "B"]}
        assert engine_params(AnalyzeParams(fastq_dir="/r", species="SAL")) == {
            "fastq_dir": "/r",
            "species": "SAL",
        }
        assert engine_params(CurateParams(scope=CurateScope(pathogen="SAL"))) == {
            "scope": {"pathogen": "SAL"}
        }


class TestCanonicalHash:
    def test_stable_and_parameter_sensitive(self):
        a = [_analyze("A", "B")]
        assert plan_hash(a, {}) == plan_hash([AnalyzeParams(samples=["A", "B"])], {})
        assert plan_hash(a, {}) != plan_hash([_analyze("B", "A")], {})
        assert plan_hash(a, {}) != plan_hash(a, {"/d": "x"})
        assert canonical_json(a, {}).isascii()

    def test_non_ascii_is_escaped_deterministically(self):
        t = [CurateParams(scope=CurateScope(pathogen="沙门菌"))]
        assert "\\u" in canonical_json(t, {})
        assert plan_hash(t, {}) == plan_hash(list(t), {})

    def test_deterministic_task_ids(self):
        assert plan_task_id("p", 1, 0) == plan_task_id("p", 1, 0)
        assert plan_task_id("p", 1, 0) != plan_task_id("p", 2, 0)
        assert len(plan_task_id("p", 1, 0)) == 32


class TestLifecycle:
    def test_create_and_get(self, svc):
        service, _ = svc
        rec = service.create([_analyze("A")], "why", "mcp-stdio:cloud:u")
        assert rec.version == 1 and rec.state is PlanState.AWAITING_CONFIRMATION
        assert service.get(rec.plan_id).plan_hash == rec.plan_hash
        assert [p.plan_id for p in service.list_plans()] == [rec.plan_id]
        with pytest.raises(NotFound):
            service.get("nope")

    def test_empty_or_oversized_plan_rejected(self, svc):
        service, _ = svc
        with pytest.raises(ValidationFailed):
            service.create([], "", "x")
        with pytest.raises(ValidationFailed, match="at most"):
            service.create([_analyze(f"S{i}") for i in range(11)], "", "x")

    def test_confirm_submits_once_with_deterministic_ids(self, svc):
        service, engine = svc
        rec = service.create([_analyze("A"), CurateParams()], "", "harness")
        done = service.confirm(rec.plan_id, 1, rec.short_hash, "cli:alice")
        assert done.state is PlanState.SUBMITTED
        assert done.task_ids == [plan_task_id(rec.plan_id, 1, i) for i in range(2)]
        assert done.confirmed_by == "cli:alice"
        assert engine.calls[0][2] == f"cli:alice via plan {rec.plan_id}@v1"
        again = service.confirm(rec.plan_id, 1, rec.plan_hash, "cli:bob")
        assert again.task_ids == done.task_ids and len(engine.calls) == 2

    def test_concurrent_confirm_yields_one_task_set(self, svc):
        service, engine = svc
        rec = service.create([_analyze("A")], "", "harness")
        results: list[Any] = []

        def go(who: str) -> None:
            results.append(service.confirm(rec.plan_id, 1, rec.plan_hash, who))

        threads = [threading.Thread(target=go, args=(f"u{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert engine.ids == {plan_task_id(rec.plan_id, 1, 0)}
        assert service.get(rec.plan_id).state is PlanState.SUBMITTED

    def test_hash_mismatch_and_short_prefix_conflict(self, svc):
        service, engine = svc
        rec = service.create([_analyze("A")], "", "harness")
        with pytest.raises(Conflict, match="mismatch"):
            service.confirm(rec.plan_id, 1, "0" * 64, "cli")
        with pytest.raises(Conflict):
            service.confirm(rec.plan_id, 1, rec.plan_hash[:6], "cli")
        assert engine.calls == []

    def test_revision_supersedes_and_old_version_cannot_run(self, svc):
        service, engine = svc
        v1 = service.create([_analyze("A")], "", "harness")
        v2 = service.revise(v1.plan_id, [_analyze("A", "B")], "add B", "harness")
        assert v2.version == 2 and v2.plan_hash != v1.plan_hash
        assert service.get(v1.plan_id, 1).state is PlanState.SUPERSEDED
        with pytest.raises(Conflict, match="superseded"):
            service.confirm(v1.plan_id, 1, v1.plan_hash, "cli")
        assert engine.calls == []
        assert service.confirm(v1.plan_id, 2, v2.plan_hash, "cli").state is PlanState.SUBMITTED

    def test_reject_then_revise(self, svc):
        service, _ = svc
        rec = service.create([_analyze("A")], "", "harness")
        rejected = service.reject(rec.plan_id, 1, "wrong sample", "cli")
        assert rejected.state is PlanState.REJECTED and "wrong sample" in rejected.message
        with pytest.raises(Conflict):
            service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        with pytest.raises(Conflict):
            service.reject(rec.plan_id, 1, "again", "cli")
        assert service.revise(rec.plan_id, [_analyze("B")], "", "harness").version == 2

    def test_submitted_plan_cannot_be_revised(self, svc):
        service, _ = svc
        rec = service.create([_analyze("A")], "", "harness")
        service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        with pytest.raises(Conflict, match="submitted"):
            service.revise(rec.plan_id, [_analyze("B")], "", "harness")

    def test_engine_rejection_marks_failed(self, tmp_path: Path):
        engine = FakeEngine(reject_index=1)
        service = PlanService(engine, tmp_path / "tasks.sqlite")
        rec = service.create([_analyze("A"), _analyze("B")], "", "harness")
        out = service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        assert out.state is PlanState.FAILED
        assert out.task_ids == [plan_task_id(rec.plan_id, 1, 0)]
        assert "engine says no" in out.message

    def test_crash_after_claim_resumes_on_reconfirm(self, svc, tmp_path: Path):
        service, engine = svc
        rec = service.create([_analyze("A")], "", "harness")
        with sqlite3.connect(tmp_path / "tasks.sqlite") as conn:
            conn.execute(
                "UPDATE plans SET state='confirmed', confirmed_by='cli' WHERE plan_id=?",
                (rec.plan_id,),
            )
        out = service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        assert out.state is PlanState.SUBMITTED and len(engine.calls) == 1


class TestInputFingerprint:
    def _dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "genomes"
        d.mkdir()
        (d / "a.fna").write_text(">c\nACGT\n")
        return d

    def test_directory_change_blocks_confirmation(self, svc, tmp_path: Path):
        service, engine = svc
        d = self._dir(tmp_path)
        rec = service.create([AnalyzeParams(fasta_dir=str(d))], "", "harness")
        assert list(rec.inputs) == [str(d)]
        (d / "b.fna").write_text(">c\nGGGG\n")
        with pytest.raises(Conflict, match="changed"):
            service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        assert engine.calls == []

    def test_modified_file_blocks_confirmation(self, svc, tmp_path: Path):
        service, _ = svc
        d = self._dir(tmp_path)
        rec = service.create([AnalyzeParams(fasta_dir=str(d))], "", "harness")
        st = (d / "a.fna").stat()
        os.utime(d / "a.fna", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        with pytest.raises(Conflict):
            service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")

    def test_missing_directory(self, svc, tmp_path: Path):
        service, _ = svc
        with pytest.raises(ValidationFailed, match="not found"):
            service.create([AnalyzeParams(fasta_dir=str(tmp_path / "nope"))], "", "x")
        d = self._dir(tmp_path)
        rec = service.create([AnalyzeParams(fasta_dir=str(d))], "", "harness")
        (d / "a.fna").unlink()
        d.rmdir()
        with pytest.raises(Conflict, match="gone"):
            service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")

    def test_unchanged_directory_submits(self, svc, tmp_path: Path):
        service, engine = svc
        d = self._dir(tmp_path)
        rec = service.create([AnalyzeParams(fasta_dir=str(d), species="VPA")], "", "harness")
        assert service.confirm(rec.plan_id, 1, rec.plan_hash, "cli").state is PlanState.SUBMITTED
        assert engine.calls[0][1] == {"fasta_dir": str(d), "species": "VPA"}


class TestOpenPathPlans:
    def test_script_is_part_of_hash_and_submitted(self, svc):
        service, engine = svc
        from bacmap.tasks.params import MineParams

        a = service.create([MineParams(objective="o", script="print(1)")], "", "harness")
        b = service.create([MineParams(objective="o", script="print(2)")], "", "harness")
        assert a.plan_hash != b.plan_hash
        done = service.confirm(a.plan_id, 1, a.plan_hash, "cli")
        assert done.state is PlanState.SUBMITTED
        assert engine.calls[0][0] is TaskType.MINE
        assert engine.calls[0][1]["script"] == "print(1)"

    def test_write_plan_submits_draft(self, svc):
        service, engine = svc
        from bacmap.tasks.params import WriteParams

        rec = service.create([WriteParams(objective="简报", draft="草稿正文")], "", "harness")
        service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")
        assert engine.calls[0][0] is TaskType.WRITE
        assert engine.calls[0][1]["draft"] == "草稿正文"

    def test_mine_input_path_fingerprinted(self, svc, tmp_path):
        service, _ = svc
        from bacmap.tasks.params import MineParams

        f = tmp_path / "table.csv"
        f.write_text("a,b\n")
        rec = service.create(
            [MineParams(objective="o", script="print(1)", input_paths=[str(f)])], "", "harness"
        )
        assert str(f) in rec.inputs
        f.write_text("a,b,c\n")  # 内容变化 → 确认冲突
        with pytest.raises(Conflict, match="changed"):
            service.confirm(rec.plan_id, 1, rec.plan_hash, "cli")


class TestWithDbosEngine:
    """真实 DbosTaskEngine：显式 task_id 幂等提交（工作流替身，不跑管线）。"""

    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        import bacmap.tasks.engine.dbos_engine as eng

        started: list[str] = []

        def fake_start(workflow, params):
            started.append(params["task_id"])

        monkeypatch.setattr(eng.DBOS, "start_workflow", fake_start)
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", fake_start)
        e = eng.DbosTaskEngine(tmp_path)
        e.started = started
        yield e
        eng.shutdown_dbos()

    def test_explicit_task_id_is_idempotent(self, engine):
        tid = TaskId("a" * 32)
        assert engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "x", task_id=tid) == tid
        assert engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "x", task_id=tid) == tid
        assert engine.started == ["a" * 32]
        assert [t["task_id"] for t in engine.list_tasks(10)] == ["a" * 32]

    def test_explicit_task_id_format_enforced(self, engine):
        with pytest.raises(ValueError, match="32 lowercase hex"):
            engine.submit(TaskType.ANALYZE, {"samples": ["A"]}, "x", task_id=TaskId("../x"))

    def test_plan_confirm_through_real_engine(self, engine, tmp_path: Path):
        service = PlanService(engine, engine.db)
        rec = service.create([_analyze("A")], "", "harness")
        service.confirm(rec.plan_id, 1, rec.plan_hash, "cli:a")
        service.confirm(rec.plan_id, 1, rec.plan_hash, "cli:b")
        rows = engine.list_tasks(10)
        assert [r["task_id"] for r in rows] == [plan_task_id(rec.plan_id, 1, 0)]
        assert rows[0]["submitted_by"] == f"cli:a via plan {rec.plan_id}@v1"
