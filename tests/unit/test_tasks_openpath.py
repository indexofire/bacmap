"""开放路径测试（迁移第 10 步）：挖掘门/引用门 + mine/write 工作流（V11⑤⑥）。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.tasks import gates
from bacmap.tasks.gates import GateVerdict
from bacmap.tasks.spec import Approval, TaskState, TaskType


class TestMiningGate:
    def test_signed_reproducible_passes(self):
        r = gates.evaluate_mining(
            {"artifacts": [{"name": "plot.png", "reproducible": True}], "signed_by": "dr.wang"}
        )
        assert r.verdict == GateVerdict.PASS

    def test_unsigned_rejects(self):
        r = gates.evaluate_mining(
            {"artifacts": [{"name": "plot.png", "reproducible": True}], "signed_by": None}
        )
        assert r.verdict == GateVerdict.REJECT
        assert "unsigned" in r.details["problems"]

    def test_empty_artifacts_rejects(self):
        r = gates.evaluate_mining({"artifacts": [], "signed_by": "x"})
        assert r.verdict == GateVerdict.REJECT

    def test_not_reproducible_rejects(self):
        r = gates.evaluate_mining(
            {"artifacts": [{"name": "ad_hoc.xlsx", "reproducible": False}], "signed_by": "x"}
        )
        assert r.verdict == GateVerdict.REJECT
        assert any("not_reproducible" in p for p in r.details["problems"])


class TestCitationGate:
    def test_known_citation_passes(self):
        r = gates.evaluate_citation(
            {
                "draft": "blaCTX-M-15 检出 [12345678]，与暴发株同簇。",
                "known_citations": ["12345678"],
            }
        )
        assert r.verdict == GateVerdict.PASS

    def test_unknown_citation_rejects(self):
        r = gates.evaluate_citation(
            {"draft": "见 PMID: 87654321。", "known_citations": ["12345678"]}
        )
        assert r.verdict == GateVerdict.REJECT
        assert "87654321" in r.details["unknown"]

    def test_no_citations_passes(self):
        r = gates.evaluate_citation({"draft": "结论……", "known_citations": []})
        assert r.verdict == GateVerdict.PASS


class _FakeSandboxResult:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""
        self.backend = "fake"


class TestMineWorkflow:
    """V11⑤ 挖掘门闭环：沙箱产物 → 未签字 REJECT → AWAIT → 签字 → PASS。

    沙箱执行器已有独立单元测试（test_sandbox.py）；此处验证的是
    approve() 的 workspace 扫描 → 挖掘门 → 状态机闭环。
    产物文件由主线程直接创建（跨线程文件可见性 workaround）。
    """

    @pytest.fixture
    def engine(self, tmp_path: Path):
        eng._run_sandbox = lambda spec: _FakeSandboxResult(0)
        e = eng.DbosTaskEngine(tmp_path)
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

    def test_mine_gate_v11e_signs_artifacts(self, engine, tmp_path):
        tid = engine.submit(TaskType.MINE, {"script": "pass"}, "analyst")
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        assert "unsigned" in (st.message or "")

        ws = tmp_path / "workspaces" / tid
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "result.txt").write_text("finding", encoding="utf-8")
        assert (ws / "result.txt").exists()

        engine.approve(
            tid,
            Approval(
                approver="reviewer",
                decision="approve",
                signature="sig",
                at=datetime.now(UTC),
            ),
        )
        final = engine.status(tid)
        assert final.state == TaskState.SUCCEEDED, f"msg={final.message}"

    def test_mine_gate_rejects_empty(self, engine, tmp_path):
        """V11⑤ 反面：签字时产物为空 → 门拒绝。"""
        tid = engine.submit(TaskType.MINE, {"script": "pass"}, "analyst")
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL

        ws = tmp_path / "workspaces" / tid
        ws.mkdir(parents=True, exist_ok=True)
        # 不创建产物文件 → approve 时 artifacts 为空 → gate 拒绝

        engine.approve(
            tid,
            Approval(
                approver="reviewer",
                decision="approve",
                signature="sig",
                at=datetime.now(UTC),
            ),
        )
        final = engine.status(tid)
        assert final.state == TaskState.FAILED
        assert "empty_artifacts" in (final.message or "")

    def test_mine_sandbox_failure(self, engine, monkeypatch):
        monkeypatch.setattr(eng, "_run_sandbox", lambda spec: _FakeSandboxResult(1))
        tid = engine.submit(TaskType.MINE, {"script": "exit(1)"}, "analyst")
        st = self._wait(engine, tid)
        assert st.state == TaskState.FAILED


class TestWriteWorkflow:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        e = eng.DbosTaskEngine(tmp_path)
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

    def test_write_valid_citation_awaits_then_approves(self, engine):
        tid = engine.submit(
            TaskType.WRITE,
            {"draft": "检出 blaCTX-M-15 [12345678]。", "known_citations": ["12345678"]},
            "writer",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        engine.approve(
            tid,
            Approval(approver="editor", decision="approve", signature="sig", at=datetime.now(UTC)),
        )
        assert engine.status(tid).state == TaskState.SUCCEEDED

    def test_write_unknown_citation_fails_immediately(self, engine):
        """V11⑥：含知识库中不存在引用的成稿被引用门拒绝导出。"""
        tid = engine.submit(
            TaskType.WRITE,
            {"draft": "结论见 [99999999]。", "known_citations": ["12345678"]},
            "writer",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.FAILED
        assert "99999999" in (st.message or "") or "99999999" in str(st.message)

    def test_write_reject_approval(self, engine):
        tid = engine.submit(
            TaskType.WRITE,
            {"draft": "正常引用 [12345678]。", "known_citations": ["12345678"]},
            "writer",
        )
        st = self._wait(engine, tid)
        assert st.state == TaskState.AWAITING_APPROVAL
        engine.approve(
            tid,
            Approval(approver="editor", decision="reject", signature="sig", at=datetime.now(UTC)),
        )
        assert engine.status(tid).state == TaskState.FAILED


class TestGateAuditTrail:
    """§4.2/ADR-07：无样本锚点的门（mine/write/curate）以 GOM TASK 对象留痕。"""

    def _wait(self, e, tid, timeout_s=30):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = e.status(tid)
            if st.state != TaskState.RUNNING:
                return st
            time.sleep(0.2)
        return e.status(tid)

    def test_mine_records_gate_event_on_task_object(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(eng, "_run_sandbox", lambda spec: _FakeSandboxResult(0))
        e = eng.DbosTaskEngine(tmp_path)
        try:
            tid = e.submit(TaskType.MINE, {"script": "pass"}, "analyst")
            self._wait(e, tid)
        finally:
            eng.shutdown_dbos()

        from bacmap.store.genome_object_service import GenomeObjectService

        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            events = gos.list_events(tid)
        assert any(ev.event_type == "gate.mining" for ev in events), [
            ev.event_type for ev in events
        ]

    def test_write_records_citation_gate_event(self, tmp_path: Path):
        e = eng.DbosTaskEngine(tmp_path)
        try:
            tid = e.submit(
                TaskType.WRITE,
                {"draft": "见 [12345678]。", "known_citations": ["12345678"]},
                "writer",
            )
            self._wait(e, tid)
        finally:
            eng.shutdown_dbos()

        from bacmap.store.genome_object_service import GenomeObjectService

        with GenomeObjectService(tmp_path / "gom.sqlite") as gos:
            events = gos.list_events(tid)
        assert any(ev.event_type == "gate.citation" for ev in events)


class TestCitationKnownNormalization:
    """引用门：知识库侧标识符归一（PMID 前缀/方括号/DOI 大小写）与成稿侧可比。"""

    def test_pmid_prefix_in_known_matches_bracket_citation(self):
        r = gates.evaluate_citation(
            {"draft": "检出 blaCTX-M-15 [12345678]。", "known_citations": ["PMID:12345678"]}
        )
        assert r.verdict == GateVerdict.PASS

    def test_lowercase_pmid_prefix_draft(self):
        r = gates.evaluate_citation(
            {"draft": "见 pmid: 12345678。", "known_citations": ["12345678"]}
        )
        assert r.verdict == GateVerdict.PASS

    def test_bracketed_known_normalized(self):
        r = gates.evaluate_citation(
            {"draft": "见 PMID:12345678。", "known_citations": ["[12345678]"]}
        )
        assert r.verdict == GateVerdict.PASS

    def test_doi_case_insensitive_both_sides(self):
        r = gates.evaluate_citation(
            {"draft": "见 10.1128/JCM.00123-24。", "known_citations": ["10.1128/jcm.00123-24"]}
        )
        assert r.verdict == GateVerdict.PASS

    def test_unknown_pmid_still_rejected(self):
        r = gates.evaluate_citation(
            {"draft": "见 PMID:99999999。", "known_citations": ["PMID:12345678"]}
        )
        assert r.verdict == GateVerdict.REJECT
        assert "99999999" in r.details["unknown"]

    def test_short_list_number_not_treated_as_citation(self):
        r = gates.evaluate_citation({"draft": "步骤 [1] 与 [2] 见正文。", "known_citations": []})
        assert r.verdict == GateVerdict.PASS
