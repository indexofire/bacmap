"""DBOS 系统库半迁移自愈（v1.10.26）。

实测事故：btrfs 上删除数据目录后立即重启，DBOS 迁移 1 执行到一半遇到
``disk I/O error``——DDL（workflow_status + 索引）已落盘但 ``dbos_migrations``
为空，此后每次启动都抛 ``table workflow_status already exists``，系统永久
无法启动。这里固定检测签名、隔离保留现场与重建行为。
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from bacmap.tasks.engine import _runtime
from bacmap.tasks.engine.task_engine import DbosTaskEngine


def _half_migrated_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE dbos_migrations (version INTEGER)")
    conn.execute(
        "CREATE TABLE workflow_status (workflow_uuid TEXT PRIMARY KEY, created_at INTEGER)"
    )
    conn.execute("CREATE INDEX workflow_status_created_at_index ON workflow_status (created_at)")
    conn.commit()
    conn.close()


class TestInconsistencyDetector:
    def test_half_migrated_detected(self, tmp_path):
        db = tmp_path / "dbos.sqlite"
        _half_migrated_db(db)
        assert _runtime._system_db_inconsistent(db) is True

    def test_missing_or_empty_not_flagged(self, tmp_path):
        assert _runtime._system_db_inconsistent(tmp_path / "missing.sqlite") is False
        empty = tmp_path / "empty.sqlite"
        empty.write_bytes(b"")
        assert _runtime._system_db_inconsistent(empty) is False

    def test_fresh_db_without_dbos_tables_not_flagged(self, tmp_path):
        db = tmp_path / "dbos.sqlite"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE other (x INTEGER)")
        conn.commit()
        conn.close()
        assert _runtime._system_db_inconsistent(db) is False

    def test_garbage_file_flagged(self, tmp_path):
        db = tmp_path / "dbos.sqlite"
        db.write_text("not a sqlite database", encoding="utf-8")
        assert _runtime._system_db_inconsistent(db) is True


class TestQuarantine:
    def test_quarantine_moves_db_and_sidecars(self, tmp_path):
        db = tmp_path / "dbos.sqlite"
        _half_migrated_db(db)
        (tmp_path / "dbos.sqlite-wal").write_bytes(b"wal")
        target = _runtime._quarantine_system_db(db)
        assert not db.exists() and target.is_file()
        assert target.name.startswith("dbos.sqlite.corrupt-")
        assert (tmp_path / f"{target.name}-wal").is_file()


class TestEngineSelfHeal:
    def test_engine_reinitializes_half_migrated_system_db(self, tmp_path):
        """真实事故复现：半迁移 dbos.sqlite → 启动自愈并保留现场。"""
        _half_migrated_db(tmp_path / "dbos.sqlite")
        # DBOS 是进程级单例：先确保未就绪，再让 init_dbos 走完整路径。
        with contextlib.suppress(Exception):
            _runtime.shutdown_dbos()
        _runtime._dbos_ready = False
        try:
            engine = DbosTaskEngine(tmp_path)
            assert engine.home == tmp_path
            assert list(tmp_path.glob("dbos.sqlite.corrupt-*"))
            assert (tmp_path / "dbos.sqlite").is_file()
        finally:
            with contextlib.suppress(Exception):
                _runtime.shutdown_dbos()
            _runtime._dbos_ready = False
