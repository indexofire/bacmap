"""后台任务通知器（v1.10.30）：周期进度 + 回调投递。

在 Web 守护进程中启动一次（任务通常在 Web 进程里运行）。每 5 秒投递 outbox 中
待发送的回调；每隔 ``BACMAP_TASK_PROGRESS_INTERVAL_S``（默认 600 秒）为
running 任务生成一条 progress 通知（阶段变化或进度前进 ≥5% 时）。

测试/短生命周期进程可用 ``BACMAP_TASK_NOTIFIER=0`` 关闭；pytest 下自动禁用。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from bacmap.tasks import notifications
from bacmap.tasks.progress import compute as compute_progress

logger = logging.getLogger(__name__)
_INTERVAL = 5.0
_started: dict[str, TaskNotifier] = {}
_lock = threading.Lock()


class TaskNotifier(threading.Thread):
    daemon = True

    def __init__(self, home: Path, progress_interval: float) -> None:
        super().__init__(name=f"bacmap-notifier-{home.name}")
        self.home = Path(home)
        self.progress_interval = max(30.0, progress_interval)
        self._stop = threading.Event()
        self._last: dict[str, tuple[int, str]] = {}

    def stop(self) -> None:
        self._stop.set()

    def _running(self) -> list[sqlite3.Row]:
        db = self.home / "tasks.sqlite"
        if not db.is_file():
            return []
        with closing(sqlite3.connect(db, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                "SELECT task_id, task_type, state, current_step, created_at"
                " FROM tasks WHERE state IN ('running','awaiting_approval')"
                " ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()

    def _progress_tick(self) -> None:
        db = self.home / "tasks.sqlite"
        if not db.is_file():
            return
        with closing(sqlite3.connect(db, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            for row in self._running():
                try:
                    progress = compute_progress(conn, row)
                    raw_pct = progress.get("progress_pct")
                    pct = int(raw_pct) if isinstance(raw_pct, (int, float)) else 0
                    stage = str(progress.get("stage") or "")
                    last_pct, last_stage = self._last.get(
                        str(row["task_id"]), (-1, "")
                    )
                    if stage == last_stage and pct - last_pct < 5:
                        continue
                    self._last[str(row["task_id"])] = (pct, stage)
                    notifications.append(
                        self.home,
                        str(row["task_id"]),
                        "progress",
                        state=str(row["state"]),
                        step=stage,
                        progress_pct=pct,
                        payload={
                            "estimated": bool(progress.get("estimated")),
                            "eta_seconds": progress.get("eta_seconds"),
                            "elapsed_seconds": progress.get("elapsed_seconds"),
                        },
                    )
                except sqlite3.Error:
                    logger.warning(
                        "progress tick failed for %s", row["task_id"], exc_info=True
                    )

    def run(self) -> None:
        next_progress = 0.0
        while not self._stop.is_set():
            try:
                notifications.deliver_pending(self.home)
            except Exception:
                logger.warning("notification delivery failed", exc_info=True)
            if time.monotonic() >= next_progress:
                try:
                    self._progress_tick()
                except Exception:
                    logger.warning("progress tick failed", exc_info=True)
                next_progress = time.monotonic() + self.progress_interval
            self._stop.wait(_INTERVAL)


def start(home: Path, *, progress_interval: float | None = None) -> TaskNotifier | None:
    """启动该 home 的通知线程（幂等）；测试/禁用环境返回 None。"""
    if os.environ.get("BACMAP_TASK_NOTIFIER", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    key = str(Path(home).resolve())
    with _lock:
        existing = _started.get(key)
        if existing is not None and existing.is_alive():
            return existing
        interval = progress_interval
        if interval is None:
            try:
                interval = float(
                    os.environ.get("BACMAP_TASK_PROGRESS_INTERVAL_S", "600")
                )
            except ValueError:
                interval = 600.0
        thread = TaskNotifier(Path(home), interval)
        _started[key] = thread
        thread.start()
        return thread


def stop_all() -> None:
    with _lock:
        for thread in _started.values():
            thread.stop()
        _started.clear()
