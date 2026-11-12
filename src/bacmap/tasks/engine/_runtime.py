"""DBOS 运行时生命周期（ADR-02：tasks 层是唯一导入 dbos 的模块群）。

单例 launch/destroy 的进程级守卫：Web 线程池 + CLI 并发初始化不双 launch
（check-then-set 双重检查锁）。
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from dbos import DBOS

logger = logging.getLogger(__name__)

_dbos_ready = False
_dbos_ready_lock = threading.Lock()


def _system_db_inconsistent(db_path: Path) -> bool:
    """DBOS 3.x SQLite 迁移半途崩溃检测。

    DBOS 的迁移逐语句执行、版本行在迁移末尾才写入：中途 I/O 失败会留下
    "业务表已存在 + ``dbos_migrations`` 为空"的半迁移库，重试必然抛
    ``table ... already exists``（实测：btrfs 上删目录重建时触发）。
    该签名（以及无法读取的损坏库）视为不一致，交由隔离重建处理。
    """
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "dbos_migrations" not in tables or "workflow_status" not in tables:
                return False
            recorded = conn.execute("SELECT COUNT(*) FROM dbos_migrations").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return True
    return recorded == 0


def _quarantine_system_db(db_path: Path) -> Path:
    """把不一致的 DBOS 系统库改名保留现场（不删除），返回新路径。"""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    target = db_path.with_name(f"{db_path.name}.corrupt-{stamp}")
    db_path.replace(target)
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        with contextlib.suppress(OSError):
            side.replace(db_path.with_name(target.name + suffix))
    return target


def _launch(db_path: Path) -> None:
    from dbos._dbos_config import DBOSConfig

    cfg = DBOSConfig(
        name="bacmap", system_database_url=f"sqlite:///{db_path.resolve().as_posix()}"
    )
    DBOS(config=cfg)
    DBOS.launch()


def init_dbos(db_path: Path) -> None:
    global _dbos_ready
    if _dbos_ready:
        return
    with _dbos_ready_lock:
        if _dbos_ready:
            return
        if _system_db_inconsistent(db_path):
            quarantined = _quarantine_system_db(db_path)
            logger.error(
                "DBOS system database was left half-migrated by an interrupted "
                "launch; moved it to %s and reinitializing (tasks.sqlite and "
                "result directories are unaffected)",
                quarantined,
            )
        _launch(db_path)
        _dbos_ready = True
        # v1.10.22：跨版本中断恢复（收养旧版 PENDING 工作流 + 卡死任务对账）。
        try:
            from bacmap.tasks.engine.recovery import recover_interrupted

            result = recover_interrupted(db_path.parent)
            if result["adopted"] or result["reconciled"]:
                logger.info("startup recovery: %s", result)
        except Exception:  # 恢复失败不阻断服务启动
            logger.warning("startup recovery failed", exc_info=True)


def shutdown_dbos() -> None:
    global _dbos_ready
    if not _dbos_ready:
        return
    DBOS.destroy()
    _dbos_ready = False
