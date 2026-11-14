"""任务通知 outbox、回调投递与进度估算（v1.10.30）。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from bacmap.store.migrations import migrate
from bacmap.tasks import notifications
from bacmap.tasks.notifier import TaskNotifier
from bacmap.tasks.progress import compute
from bacmap.tasks.spec import TASKS_MIGRATIONS


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "tasks.sqlite"
    migrate(db, TASKS_MIGRATIONS)
    return db


def _insert(
    db: Path,
    task_id: str,
    *,
    state: str,
    step: str,
    created_minutes: float,
    updated_minutes: float = 0,
) -> None:
    now = datetime.now(UTC)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO tasks (task_id, task_type, state, params_json, submitted_by,"
            " created_at, updated_at, workflow_id, current_step)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                "analyze",
                state,
                "{}",
                "mcp:test",
                (now - timedelta(minutes=created_minutes)).isoformat(),
                (now - timedelta(minutes=updated_minutes)).isoformat(),
                "",
                step,
            ),
        )


def test_outbox_and_callback_delivery(tmp_path: Path):
    _db(tmp_path)
    task_id = "a" * 32
    notifications.append(
        tmp_path, task_id, "submitted", state="running", step="pipeline", progress_pct=0
    )
    notifications.append(
        tmp_path, task_id, "finished", state="succeeded", progress_pct=100
    )
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("content-length", "0"))
            received.append(json.loads(self.rfile.read(size)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        notifications.register_watch(
            tmp_path, "task", task_id, f"http://127.0.0.1:{server.server_port}/cb"
        )
        assert notifications.deliver_pending(tmp_path) == 2
        assert [item["kind"] for item in received] == ["submitted", "finished"]
        assert notifications.deliver_pending(tmp_path) == 0
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_notifier_progress_tick_is_deduplicated(tmp_path: Path):
    db = _db(tmp_path)
    task_id = "b" * 32
    _insert(db, task_id, state="running", step="pipeline", created_minutes=30)
    notifier = TaskNotifier(tmp_path, 600)
    notifier._progress_tick()
    first = notifications.list_after(tmp_path, task_id=task_id)
    assert len(first) == 1 and first[0]["kind"] == "progress"
    assert first[0]["progress_pct"] == 20  # 无历史中位耗时 → step 下限
    notifier._progress_tick()
    assert len(notifications.list_after(tmp_path, task_id=task_id)) == 1


def test_progress_uses_historical_median(tmp_path: Path):
    db = _db(tmp_path)
    _insert(
        db,
        "c" * 32,
        state="succeeded",
        step="pipeline",
        created_minutes=100,
        updated_minutes=10,
    )
    task_id = "d" * 32
    _insert(db, task_id, state="running", step="pipeline", created_minutes=30)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        progress = compute(conn, row)
    assert progress["progress_pct"] == 33
    assert progress["estimated"] is True
    assert progress["eta_seconds"] == 3600


def test_callback_url_validation(monkeypatch):
    assert notifications.validate_callback_url("http://127.0.0.1:9999/cb")
    assert notifications.validate_callback_url("http://localhost:9999/cb")
    with pytest.raises(ValueError):
        notifications.validate_callback_url("http://evil.example/cb")
    with pytest.raises(ValueError):
        notifications.validate_callback_url("file:///tmp/x")
    monkeypatch.setenv("BACMAP_NOTIFY_ALLOWED_HOSTS", "agent.lan")
    assert notifications.validate_callback_url("http://agent.lan:9000/hook")
