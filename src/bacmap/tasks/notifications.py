"""任务通知 outbox 与智能体回调（v1.10.30）。

背景：智能体提交/确认计划后，任务可能在后台运行数小时。MCP 是请求驱动
协议，任务结束时不一定还有活跃请求；这里把通知写入 ``tasks.sqlite`` 的
outbox，并支持两种消费方式：

1. **callback_url（推荐）**：智能体/宿主暴露本机 HTTP 端点，bacmap 在
   step/终态/周期进度时 POST 一条通知（只含 D1 元数据）；
2. **轮询**：``bacmap_task_notifications`` 读取 outbox（可按 task/plan 过滤）。

回调地址默认只允许 loopback（防止 SSRF）；需要局域网回调时显式设置
``BACMAP_NOTIFY_ALLOWED_HOSTS=host1,host2``。通知不包含任务 message（可能含
样本 ID/路径，D2），智能体收到后再用 ``bacmap_task_status``/``result`` 取详情。
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})


def _db(home: Path) -> Path:
    return Path(home) / "tasks.sqlite"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def validate_callback_url(url: str) -> str:
    """只允许 http(s) loopback 或显式白名单主机（无 userinfo）。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("callback_url must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("callback_url must not contain credentials")
    allowed = _LOOPBACK | {
        host.strip().lower()
        for host in os.environ.get("BACMAP_NOTIFY_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    if parsed.hostname.lower() not in allowed:
        raise ValueError(
            "callback_url host is not allowed; use loopback or set "
            "BACMAP_NOTIFY_ALLOWED_HOSTS"
        )
    return url


def append(
    home: Path,
    task_id: str,
    kind: str,
    *,
    state: str = "",
    step: str = "",
    progress_pct: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """追加一条通知（幂等由调用方控制；重复 step 重试可接受）。"""
    db = _db(home)
    if not task_id or not db.is_file():
        return 0
    body = dict(payload or {})
    body.setdefault("task_id", task_id)
    with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO task_notifications"
            " (task_id, kind, state, step, progress_pct, created_at, payload_json)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                task_id,
                kind,
                state,
                step,
                progress_pct,
                _now(),
                json.dumps(body, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid or 0)


def _rows_to_notifications(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = {}
        try:
            loaded = json.loads(row["payload_json"] or "{}")
            if isinstance(loaded, dict):
                payload = loaded
        except ValueError:
            payload = {}
        out.append(
            {
                "seq": int(row["seq"]),
                "task_id": str(row["task_id"]),
                "kind": str(row["kind"]),
                "state": str(row["state"]),
                "step": str(row["step"]),
                "progress_pct": row["progress_pct"],
                "created_at": str(row["created_at"]),
                "payload": payload,
            }
        )
    return out


def _plan_task_ids(conn: sqlite3.Connection, plan_id: str) -> list[str]:
    row = conn.execute(
        "SELECT task_ids_json FROM plans"
        " WHERE plan_id = ? AND state = 'submitted'"
        " ORDER BY version DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    if row is None:
        return []
    try:
        loaded = json.loads(row["task_ids_json"] or "[]")
    except ValueError:
        return []
    return [str(item) for item in loaded] if isinstance(loaded, list) else []


def list_after(
    home: Path,
    *,
    after: int = 0,
    task_id: str = "",
    plan_id: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    db = _db(home)
    if not db.is_file():
        return []
    clauses = ["seq > ?"]
    args: list[Any] = [max(0, after)]
    with closing(sqlite3.connect(db, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        if task_id:
            clauses.append("task_id = ?")
            args.append(task_id)
        elif plan_id:
            ids = _plan_task_ids(conn, plan_id)
            if not ids:
                return []
            clauses.append(f"task_id IN ({','.join('?' for _ in ids)})")
            args.extend(ids)
        args.append(max(1, min(limit, 500)))
        rows = conn.execute(
            f"SELECT * FROM task_notifications WHERE {' AND '.join(clauses)}"  # noqa: S608
            " ORDER BY seq LIMIT ?",
            args,
        ).fetchall()
    return _rows_to_notifications(rows)


def register_watch(home: Path, scope: str, target_id: str, callback_url: str) -> int:
    """注册回调。scope=task|plan；同一目标+URL 复用（重置 last_seq=0）。"""
    if scope not in {"task", "plan"}:
        raise ValueError("scope must be 'task' or 'plan'")
    url = validate_callback_url(callback_url)
    db = _db(home)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
        row = conn.execute(
            "SELECT watch_id FROM task_watches WHERE scope=? AND target_id=? AND callback_url=?",
            (scope, target_id, url),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE task_watches SET last_error='', updated_at=? WHERE watch_id=?",
                (_now(), int(row[0])),
            )
            return int(row[0])
        cur = conn.execute(
            "INSERT INTO task_watches"
            " (scope, target_id, callback_url, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (scope, target_id, url, _now(), _now()),
        )
        return int(cur.lastrowid or 0)


def _watch_payload(watch: sqlite3.Row, notification: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": notification["task_id"],
        "kind": notification["kind"],
        "state": notification["state"],
        "step": notification["step"],
        "progress_pct": notification["progress_pct"],
        "seq": notification["seq"],
        "created_at": notification["created_at"],
        "plan_id": watch["target_id"] if watch["scope"] == "plan" else "",
    }


def _post(url: str, payload: dict[str, Any], timeout: float) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — URL 已在注册时白名单校验
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "bacmap-task-notifier",
            "X-Bacmap-Event": str(payload.get("kind", "task")),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout):  # noqa: S310
        return


def deliver_pending(home: Path, *, timeout: float = 3.0) -> int:
    """把未投递通知 POST 给所有 watch；返回成功投递条数。"""
    db = _db(home)
    if not db.is_file():
        return 0
    delivered = 0
    with closing(sqlite3.connect(db, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        watches = conn.execute("SELECT * FROM task_watches").fetchall()
        for watch in watches:
            task_ids = (
                [str(watch["target_id"])]
                if watch["scope"] == "task"
                else _plan_task_ids(conn, str(watch["target_id"]))
            )
            if not task_ids:
                continue
            marks = ",".join("?" for _ in task_ids)
            rows = conn.execute(
                f"SELECT * FROM task_notifications WHERE seq > ? AND task_id IN ({marks})"  # noqa: S608
                " ORDER BY seq LIMIT 50",
                [int(watch["last_seq"]), *task_ids],
            ).fetchall()
            for notification in _rows_to_notifications(rows):
                try:
                    _post(
                        str(watch["callback_url"]),
                        _watch_payload(watch, notification),
                        timeout,
                    )
                except (OSError, urllib.error.URLError, ValueError) as exc:
                    with conn:
                        conn.execute(
                            "UPDATE task_watches SET last_error=?, updated_at=? WHERE watch_id=?",
                            (str(exc)[:300], _now(), int(watch["watch_id"])),
                        )
                    break
                delivered += 1
                with conn:
                    conn.execute(
                        "UPDATE task_watches SET last_seq=?, last_error='', updated_at=?"
                        " WHERE watch_id=?",
                        (notification["seq"], _now(), int(watch["watch_id"])),
                    )
    return delivered


def deliver_task(home: Path, task_id: str, *, timeout: float = 3.0) -> int:
    """终态时同步投递该任务的通知（不依赖 notifier 线程）。"""
    db = _db(home)
    if not db.is_file():
        return 0
    delivered = 0
    with closing(sqlite3.connect(db, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        watches = conn.execute(
            "SELECT * FROM task_watches WHERE scope='task' AND target_id=?", (task_id,)
        ).fetchall()
        for watch in watches:
            rows = conn.execute(
                "SELECT * FROM task_notifications WHERE seq > ? AND task_id = ?"
                " ORDER BY seq LIMIT 50",
                (int(watch["last_seq"]), task_id),
            ).fetchall()
            for notification in _rows_to_notifications(rows):
                try:
                    _post(
                        str(watch["callback_url"]),
                        _watch_payload(watch, notification),
                        timeout,
                    )
                except (OSError, urllib.error.URLError, ValueError) as exc:
                    with conn:
                        conn.execute(
                            "UPDATE task_watches SET last_error=?, updated_at=? WHERE watch_id=?",
                            (str(exc)[:300], _now(), int(watch["watch_id"])),
                        )
                    break
                delivered += 1
                with conn:
                    conn.execute(
                        "UPDATE task_watches SET last_seq=?, last_error='', updated_at=?"
                        " WHERE watch_id=?",
                        (notification["seq"], _now(), int(watch["watch_id"])),
                    )
    return delivered
