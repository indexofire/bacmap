"""步级实时推送：产物解析（workflow.progress）与 StepWatcher 事件发射。

设计约束复核：
- 事件是观察不是真相——解析畸形/残缺产物返回 {}，绝不抛错；
- 同一 (step, subject) 在一次监听内只推一次（覆盖式合并交给前端）；
- 样本级载荷标 D2；颗粒度事件默认不进通知 outbox（里程碑步除外）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from bacmap.store.migrations import migrate
from bacmap.tasks.engine._progress import record_step_result
from bacmap.tasks.engine.step_watch import StepWatcher
from bacmap.tasks.events import EventLog, EventType
from bacmap.tasks.spec import TASKS_MIGRATIONS
from bacmap.tools.spec import DataClass
from bacmap.workflow.progress import (
    parse_amrfinder,
    parse_assembly_stats,
    parse_gspec_typing,
    parse_mlst,
    parse_screen,
    parse_species,
    parse_step_result,
    parse_summary,
)


class TestParsers:
    def test_species_flat(self, tmp_path: Path):
        p = tmp_path / "species_id.json"
        p.write_text(json.dumps({"species": "Vibrio parahaemolyticus", "method": "ani"}))
        assert parse_species(p) == {"species": "Vibrio parahaemolyticus", "method": "ani"}

    def test_species_nested_methods(self, tmp_path: Path):
        p = tmp_path / "species_id.json"
        p.write_text(
            json.dumps({"methods": {"fast": {"result": {"species": "Salmonella enterica"}}}})
        )
        assert parse_species(p)["species"] == "Salmonella enterica"

    def test_assembly_stats_tsv(self, tmp_path: Path):
        p = tmp_path / "assembly_stats.tsv"
        p.write_text(
            "file\tformat\ttype\tnum_seqs\tsum_len\tmin_len\tavg_len\tmax_len\tN50\tGC(%)\n"
            "x.fasta\tFASTA\tDNA\t42\t5100000\t200\t121428.6\t400000\t180000\t45.32\n"
        )
        out = parse_assembly_stats(p)
        assert out == {"contigs": 42, "total_length": 5100000, "n50": 180000, "gc_pct": 45.32}

    def test_mlst_json(self, tmp_path: Path):
        p = tmp_path / "mlst.json"
        p.write_text(json.dumps({"st": "3", "scheme": "vpmlst"}))
        assert parse_mlst(p) == {"st": "3", "scheme": "vpmlst"}

    def test_gspec_typing_databases(self, tmp_path: Path):
        p = tmp_path / "typing.json"
        p.write_text(
            json.dumps(
                {
                    "serotype": "O3:K6",
                    "databases": {"vpa_ok": {"hits": [{"g": 1}, {"g": 2}]}},
                }
            )
        )
        out = parse_gspec_typing(p)
        assert out["serotype"] == "O3:K6"
        assert out["database_hits"] == {"vpa_ok": 2}

    def test_amrfinder_counts_rows(self, tmp_path: Path):
        p = tmp_path / "amrfinderplus.tsv"
        p.write_text("header\nrow1\nrow2\nrow3\n")
        assert parse_amrfinder(p) == {"hits": 3}

    def test_screen_counts_hits(self, tmp_path: Path):
        p = tmp_path / "card.json"
        p.write_text(json.dumps({"hits": [{"a": 1}, {"b": 2}]}))
        assert parse_screen(p) == {"hits": 2}

    def test_summary_extracts_key_results(self, tmp_path: Path):
        p = tmp_path / "S1_summary.prelim.json"
        p.write_text(
            json.dumps(
                {
                    "steps": {
                        "species": {"species": "Vibrio parahaemolyticus"},
                        "serotype": {"serotype": "O3:K6"},
                        "mlst": {"st": "3"},
                        "qc": {},
                    },
                    "prelim": True,
                }
            )
        )
        out = parse_summary(p)
        assert out["species"] == "Vibrio parahaemolyticus"
        assert out["serotype"] == "O3:K6" and out["st"] == "3"
        assert "qc" not in out["steps_done"] and "species" in out["steps_done"]

    def test_garbage_never_raises(self, tmp_path: Path):
        p = tmp_path / "species_id.json"
        p.write_text("{not json")
        assert parse_step_result("species", p) == {}
        assert parse_step_result("unknown_step", p) == {}
        assert parse_step_result("species", tmp_path / "missing.json") == {}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    db = tmp_path / "tasks.sqlite"
    migrate(db, TASKS_MIGRATIONS)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, created_at, updated_at)"
            " VALUES ('t1', 'analyze', 'running', 'x', 'x')"
        )
    return tmp_path


def _write_artifact(run_dir: Path, sample: str, rel: str, content: str) -> Path:
    path = run_dir / sample / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestRecordStepResult:
    def test_payload_enriched_and_d2(self, home: Path):
        record_step_result(
            home, "t1", "species", subject="S1",
            result={"species": "Vibrio parahaemolyticus"},
            artifact="S1/species/species_id.json",
        )
        (e,) = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert e.type is EventType.TASK_STEP
        assert e.data_class is DataClass.D2
        assert e.payload["step"] == "species"
        assert e.payload["subject"] == "S1"
        assert e.payload["result"]["species"] == "Vibrio parahaemolyticus"
        assert e.payload["artifact"] == "S1/species/species_id.json"

    def test_granular_step_skips_notification_outbox(self, home: Path):
        record_step_result(home, "t1", "mlst", subject="S1", result={"st": "3"})
        with sqlite3.connect(home / "tasks.sqlite") as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM task_notifications WHERE task_id = 't1'"
            ).fetchone()
        assert rows[0] == 0

    def test_milestone_step_writes_notification(self, home: Path):
        record_step_result(
            home, "t1", "prelim_summary", subject="S1", result={}, notify=True
        )
        with sqlite3.connect(home / "tasks.sqlite") as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM task_notifications WHERE task_id = 't1'"
            ).fetchone()
        assert rows[0] == 1


class TestStepWatcher:
    def test_scan_emits_new_stable_artifact(self, home: Path):
        run_dir = home / "results" / "runs" / "t1"
        _write_artifact(
            run_dir, "S1", "species/species_id.json",
            json.dumps({"species": "Vibrio parahaemolyticus"}),
        )
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05)
        assert watcher.scan() == 0  # 首轮只记签名（稳定性）
        assert watcher.scan() == 1  # 次轮签名不变 → 发射
        assert watcher.scan() == 0  # 首次发现去重
        events = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert len(events) == 1
        assert events[0].payload["step"] == "species"
        assert events[0].payload["result"]["species"] == "Vibrio parahaemolyticus"

    def test_threaded_watcher_pushes_before_pipeline_end(self, home: Path):
        """核心诉求：产物落盘后秒级推出，不等 runner.run() 整包返回。"""
        run_dir = home / "results" / "runs" / "t1"
        run_dir.mkdir(parents=True)
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05)
        watcher.start()
        try:
            time.sleep(0.1)
            _write_artifact(
                run_dir, "S1", "typing/mlst.json", json.dumps({"st": "3"})
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if EventLog(home / "tasks.sqlite").list(task_id="t1"):
                    break
                time.sleep(0.05)
            events = EventLog(home / "tasks.sqlite").list(task_id="t1")
            assert len(events) == 1
            assert events[0].payload["result"]["st"] == "3"
        finally:
            watcher.stop()

    def test_final_flush_catches_late_artifacts(self, home: Path):
        run_dir = home / "results" / "runs" / "t1"
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05)
        watcher.start()
        _write_artifact(
            run_dir, "S1", "report/S1_summary.json", json.dumps({"steps": {}})
        )
        watcher.stop()  # 立即停：稳定性来不及两轮，强制收尾扫描必须补上
        events = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert any(e.payload["step"] == "final_summary" for e in events)

    def test_cohort_artifact_scoped_by_group(self, home: Path):
        run_dir = home / "results" / "runs" / "t1"
        path = run_dir / "cgmlst" / "vparahaemolyticus" / "cgmlst_summary.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"n_samples": 3}))
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05)
        watcher.scan()
        watcher.scan()
        events = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert len(events) == 1
        assert events[0].payload["subject"] == "vparahaemolyticus"
        assert events[0].payload["result"]["n_samples"] == 3

    def test_disabled_without_tasks_db(self, tmp_path: Path):
        watcher = StepWatcher(tmp_path, "t1", tmp_path, ["S1"], interval=0.05)
        assert watcher.enabled is False
        watcher.start()
        assert watcher._thread is None
        watcher.stop()  # 不报错

    def test_malformed_artifact_does_not_break_scan(self, home: Path):
        run_dir = home / "results" / "runs" / "t1"
        _write_artifact(run_dir, "S1", "species/species_id.json", "{broken")
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05)
        watcher.scan()
        assert watcher.scan() == 1  # 事件照发，结果为空 dict
        (e,) = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert e.payload["result"] == {}

    def test_since_skips_preexisting_artifacts(self, home: Path):
        """reanalyze 场景：mtime 早于监听起点的旧产物不重推；再生的新产物照推。"""
        import os
        import time

        run_dir = home / "results" / "runs" / "t1"
        old = _write_artifact(
            run_dir, "S1", "species/species_id.json",
            json.dumps({"species": "Vibrio parahaemolyticus"}),
        )
        # 显式把旧产物 mtime 拨到一小时前（模拟原始运行的存量产物）
        old_ts = time.time() - 3600
        os.utime(old, (old_ts, old_ts))
        since = time.time()
        watcher = StepWatcher(home, "t1", run_dir, ["S1"], interval=0.05, since=since)
        watcher.scan()
        watcher.scan()
        assert EventLog(home / "tasks.sqlite").list(task_id="t1") == []
        # 再生产物（新 mtime）正常发射
        _write_artifact(
            run_dir, "S1", "typing/mlst.json", json.dumps({"st": "3"})
        )
        watcher.scan()
        assert watcher.scan() == 1
        (e,) = EventLog(home / "tasks.sqlite").list(task_id="t1")
        assert e.payload["step"] == "mlst"
        # 强制收尾扫描也不应补推旧产物
        watcher.scan(force=True)
        steps = [x.payload["step"] for x in EventLog(home / "tasks.sqlite").list(task_id="t1")]
        assert steps == ["mlst"]
