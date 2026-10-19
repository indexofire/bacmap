"""DBOS 运行时生命周期（ADR-02：tasks 层是唯一导入 dbos 的模块群）。

单例 launch/destroy 的进程级守卫：Web 线程池 + CLI 并发初始化不双 launch
（check-then-set 双重检查锁）。
"""

from __future__ import annotations

import threading
from pathlib import Path

from dbos import DBOS

_dbos_ready = False
_dbos_ready_lock = threading.Lock()


def init_dbos(db_path: Path) -> None:
    global _dbos_ready
    if _dbos_ready:
        return
    from dbos._dbos_config import DBOSConfig

    with _dbos_ready_lock:
        if _dbos_ready:
            return
        cfg = DBOSConfig(
            name="bacmap", system_database_url=f"sqlite:///{db_path.resolve().as_posix()}"
        )
        DBOS(config=cfg)
        DBOS.launch()
        _dbos_ready = True


def shutdown_dbos() -> None:
    global _dbos_ready
    if not _dbos_ready:
        return
    DBOS.destroy()
    _dbos_ready = False
