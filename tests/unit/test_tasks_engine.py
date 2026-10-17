"""DbosTaskEngine 回环测试（monkeypatch 管线执行，不跑真实 snakemake）。"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.tasks.spec import Approval, TaskState, TaskType


class _Proc:
    def __init__(self, rc: int) -> None:
        self.returncode = rc


class _NoopArbiter:
    """测试用仲裁器：直通，不探测内存/不访问管理端点。"""

    @contextlib.contextmanager
    def heavy_step(self):
        yield


def _sal_summary() -> dict:
    return {
        "sample": "SAM-001",
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
            "dec": {},
        },
    }


@pytest.fixture
def engine(tmp_path, monkeypatch):
    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
    monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc(0))
    monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "test-run-1"})
    monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
    monkeypatch.setattr(eng, "_memory_arbiter", lambda: _NoopArbiter())
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


def _wait(e: eng.DbosTaskEngine, tid: str, timeout_s: float = 30.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = e.status(tid)
        if st.state != TaskState.RUNNING:
            return st
        time.sleep(0.2)
    return e.status(tid)


class TestDbosTaskEngine:
    def test_analyze_roundtrip_succeeded(self, engine):
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
        st = _wait(engine, tid)
        assert st.state == TaskState.SUCCEEDED
        assert st.current_step == "analyze"

    def test_analyze_failed_run(self, engine, monkeypatch):
        monkeypatch.setattr(eng, "_run_snakemake", lambda p: _Proc(1))
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
        st = _wait(engine, tid)
        assert st.state == TaskState.FAILED

    def test_gate_review_awaits_approval_then_approves(self, engine):
        tid = engine.submit(
            TaskType.ANALYZE,
            {
                "samples": ["SAM-001"],
                "interpretation_text": "该菌株为 E. coli，未检出 blaCTX-M-15。",
            },
            "tester",
        )
        st = _wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        engine.approve(
            tid,
            Approval(
                approver="reviewer", decision="approve", signature="sig", at=datetime.now(UTC)
            ),
        )
        assert engine.status(tid).state == TaskState.SUCCEEDED

    def test_unsupported_task_type_rejected(self, engine):
        with pytest.raises(NotImplementedError):
            engine.submit("bogus", {}, "tester")  # type: ignore[arg-type]

    def test_status_unknown_task_raises(self, engine):
        with pytest.raises(KeyError):
            engine.status("no-such-task")


class TestFastqResolution:
    """_fastqs 应以 samples.tsv 登记为准（gs/ 约定作回退）——修复前：只认 gs/ 硬编码，
    登记在别处的样本 input_files 为空，C4 证据链不完整。"""

    def _make_home(self, tmp_path, registered: dict[str, tuple[str, str]] | None):
        wf = tmp_path / "workflows" / "bacmap"
        (wf / "config").mkdir(parents=True, exist_ok=True)
        gs = tmp_path / "gs"
        if registered is not None:
            lines = ["sample\tspecies\tR1\tR2"]
            for s, (r1, r2) in registered.items():
                lines.append(f"{s}\tX\t{r1}\t{r2}")
            (wf / "config" / "samples.tsv").write_text("\n".join(lines), encoding="utf-8")
        else:
            (gs / "SAM-GS").mkdir(parents=True, exist_ok=True)
            for r in ("R1", "R2"):
                (gs / "SAM-GS" / f"SAM-GS_{r}.fastq.gz").write_bytes(b"x")
        return tmp_path

    def test_registered_path_wins(self, tmp_path):
        alt = tmp_path / "alt"
        alt.mkdir()
        (alt / "SAM-ALT_R1.fastq.gz").write_bytes(b"x")
        (alt / "SAM-ALT_R2.fastq.gz").write_bytes(b"x")
        home = self._make_home(tmp_path, {"SAM-ALT": ("../../alt/SAM-ALT_R1.fastq.gz",
                                                      "../../alt/SAM-ALT_R2.fastq.gz")})
        got = eng._fastqs(home, ["SAM-ALT"])
        assert [p.name for p in got] == ["SAM-ALT_R1.fastq.gz", "SAM-ALT_R2.fastq.gz"]

    def test_gs_fallback_when_unregistered(self, tmp_path):
        home = self._make_home(tmp_path, registered={})
        gs = home / "gs" / "SAM-GS"
        gs.mkdir(parents=True)
        for r in ("R1", "R2"):
            (gs / f"SAM-GS_{r}.fastq.gz").write_bytes(b"x")
        got = eng._fastqs(home, ["SAM-GS"])
        assert [p.name for p in got] == ["SAM-GS_R1.fastq.gz", "SAM-GS_R2.fastq.gz"]

    def test_no_samples_tsv_still_works(self, tmp_path):
        gs = tmp_path / "gs" / "SAM-ONLY"
        gs.mkdir(parents=True)
        for r in ("R1", "R2"):
            (gs / f"SAM-ONLY_{r}.fastq.gz").write_bytes(b"x")
        got = eng._fastqs(tmp_path, ["SAM-ONLY"])
        assert len(got) == 2


class TestEngineStateMachineHardening:
    """深度审计循环 4：approve 状态守卫（防 V11③ 引擎层绕过）/ analyze REJECT 不得静默
    SUCCEEDED / status 条件更新（防 approve 后被降级回 awaiting）。"""

    def _insert_task(self, e, tid: str, state: str, task_type: str = "curate") -> None:
        import sqlite3

        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(e.db) as conn:
            conn.execute(
                "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
                " created_at, updated_at, workflow_id, current_step)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (tid, task_type, state, "{}", "t", now, now, "", "curate"),
            )

    def _approval(self) -> Approval:
        return Approval(
            approver="auditor",
            decision="approve",
            signature="sig-x",
            comment="",
            at=datetime.now(UTC),
        )

    def test_approve_running_task_rejected(self, engine):
        self._insert_task(engine, "t-running", "running")
        with pytest.raises(ValueError, match="awaiting_approval"):
            engine.approve("t-running", self._approval())

    def test_approve_failed_curate_does_not_publish(self, engine):
        """审计场景：门拒绝的 curate 任务（FAILED、候选已暂存）——approve 不得绕过发布门。"""
        self._insert_task(engine, "t-failed", "failed", task_type="curate")
        with pytest.raises(ValueError):
            engine.approve("t-failed", self._approval())

    def test_double_approve_rejected(self, engine):
        self._insert_task(engine, "t-done", "succeeded")
        with pytest.raises(ValueError):
            engine.approve("t-done", self._approval())

    def test_analyze_reject_needs_review_not_succeeded(self, engine):
        """summary 缺失 → 门 reject：修复前任务静默 SUCCEEDED（绿色任务藏红色门）。"""
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-NOSUM"]}, "t")
        st = _wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        assert "reject" in (st.message or "")

    def test_status_transition_guard_helper(self, engine):
        self._insert_task(engine, "t-guard", "running")
        assert engine._transition_from_running("t-guard", "awaiting_approval", "{}") is True
        assert engine._transition_from_running("t-guard", "awaiting_approval", "{}") is False
        assert engine.status("t-guard").state == TaskState.AWAITING_APPROVAL


class TestAnalyzeAutoReport:
    """§2 注①：analyze 任务末尾的模板化分析报告应自动生成（不再只是按需工具）。"""

    def test_report_generated_at_end_of_analyze(self, engine, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            eng, "_generate_report_for", lambda s: (calls.append(s), {"sample_id": s})[1]
        )
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "t")
        st = _wait(engine, tid)
        assert calls == ["SAM-001"]
        assert st.state in (TaskState.SUCCEEDED, TaskState.AWAITING_APPROVAL)


class TestMemoryArbiterWiring:
    """ADR-17：analyze 的内存密集步骤必须经资源仲裁（此前仲裁器未接线）。"""

    def test_analyze_wraps_run_in_heavy_step(self, tmp_path, monkeypatch):
        rep = tmp_path / "results" / "SAM-001" / "report"
        rep.mkdir(parents=True)
        (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
        events: list[str] = []

        class _Recorder:
            @contextlib.contextmanager
            def heavy_step(self):
                events.append("enter")
                try:
                    yield
                finally:
                    events.append("exit")

        monkeypatch.setattr(eng, "_memory_arbiter", lambda: _Recorder())
        monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc(0))
        monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "r1"})
        monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
        e = eng.DbosTaskEngine(tmp_path)
        try:
            tid = e.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "tester")
            _wait(e, tid)
        finally:
            eng.shutdown_dbos()
        assert events.count("enter") >= 1
        assert events.count("enter") == events.count("exit")

    def test_memory_arbiter_disabled_when_not_colocated(self, tmp_path, monkeypatch):
        import bacmap.config as cfgmod

        monkeypatch.setattr(cfgmod, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text("[llm.resources]\nco_located = false\n")
        arb = eng._memory_arbiter()
        assert arb._enabled is False

    def test_memory_arbiter_admin_url_from_endpoint(self, tmp_path, monkeypatch):
        import bacmap.config as cfgmod

        monkeypatch.setattr(cfgmod, "BACMAP_HOME", tmp_path)
        (tmp_path / "config.toml").write_text(
            """
[llm.endpoints.strata]
base_url = "http://127.0.0.1:9999/v1"
model = "m"
admin_url = "http://127.0.0.1:9999"

[llm.resources]
co_located = true
min_free_ram_gb_for_heavy_steps = 12
""",
            encoding="utf-8",
        )
        arb = eng._memory_arbiter()
        assert arb._enabled is True
        assert arb._admin_url == "http://127.0.0.1:9999"
        assert arb._min_free_gb == 12


class TestGateEventsPersisted:
    """§4.2/ADR-07：每次门评估写入 GOM events（event_type = "gate.<name>"）。"""

    def test_analyze_records_analysis_claims_gate_event(self, engine, tmp_path):
        from bacmap.store.genome_object_service import GenomeObjectService, ObjectType

        tid = engine.submit(
            TaskType.ANALYZE,
            {"samples": ["SAM-001"], "interpretation_text": "该菌株为 Salmonella。"},
            "tester",
        )
        _wait(engine, tid)

        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            objs = gos.list_by_type(ObjectType.ANALYSIS)
            assert objs, "analyze 应写入样本 GOM 分析对象"
            assert objs[0].payload.get("analysis_type") == "sample_analysis"
            events = gos.list_events(objs[0].object_id)
        gate_types = {e.event_type for e in events}
        assert "gate.analysis_claims" in gate_types
        gate_events = [e for e in events if e.event_type == "gate.analysis_claims"]
        assert gate_events[0].event_payload.get("verdict")


class TestSubmitHardening:
    """提交健壮性：workflow_id 确定性映射、current_step 正确、样本校验、启动失败回滚。"""

    def test_workflow_id_equals_task_id_and_step(self, engine):
        tid = engine.submit(TaskType.MINE, {"script": "pass"}, "tester")
        with engine._conn() as conn:
            row = conn.execute(
                "SELECT workflow_id, current_step FROM tasks WHERE task_id = ?", (tid,)
            ).fetchone()
        assert row["workflow_id"] == tid
        assert row["current_step"] == "mine"

    def test_invalid_sample_id_rejected(self, engine):
        with pytest.raises(ValueError):
            engine.submit(TaskType.ANALYZE, {"samples": ["../evil"]}, "tester")

    def test_start_failure_marks_task_failed(self, engine, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("start failed")

        monkeypatch.setattr(eng.DBOS, "start_workflow", boom)
        with pytest.raises(RuntimeError):
            engine.submit(TaskType.CURATE, {}, "tester")
        with engine._conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE state='failed'").fetchone()["c"]
        assert n >= 1


class TestCountStates:
    """count_states 统计全部任务，不受 list_tasks 的 limit 截断（概览页口径）。"""

    def test_counts_exceed_list_limit(self, engine):
        for i in range(55):
            _insert_task_helper(engine, f"t-done-{i}", "succeeded")
        for i in range(5):
            _insert_task_helper(engine, f"t-run-{i}", "running")
        counts = engine.count_states()
        assert counts.get("succeeded") == 55
        assert counts.get("running") == 5
        assert sum(counts.values()) == 60
        assert len(engine.list_tasks()) == 50  # 列表默认截断，计数不截断


def _insert_task_helper(e, tid: str, state: str) -> None:
    import sqlite3

    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(e.db) as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at, workflow_id, current_step)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (tid, "curate", state, "{}", "t", now, now, "", "curate"),
        )
