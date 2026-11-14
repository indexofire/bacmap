"""任务进度估算（v1.10.30）。

DBOS 只在 step 边界更新 ``current_step``；长 step（pipeline/sandbox）内部没有
细粒度进度。这里用「step 下限 + 同类型历史任务的中位耗时」给出可解释的估计：

- ``progress_pct``：running 时取 max(step 下限, elapsed/median)，上限 95；
- ``eta_seconds``：中位耗时 − elapsed；
- ``estimated``：是否使用了历史耗时（False 时只看 step 下限）。

没有历史成功任务时只报阶段，不伪造百分比。任务完成/失败/取消后固定 100。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from statistics import median

# step → 进度下限（跨任务类型；step 名称本身足够区分）
_STEP_FLOOR: dict[str, int] = {
    "register_inputs": 5,
    "prelim_ready": 15,
    "pipeline": 20,
    "sandbox": 15,
    "draft": 35,
    "curate_build": 70,
    "run_record": 82,
    "ingest_and_gates": 92,
    "record": 10,
    "research_session": 20,
    "advstats_sandbox": 20,
}
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def _parse(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    # 旧 fixture/手工行可能是 naive 时间；统一按 UTC，避免 aware-naive 相减。
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _median_duration(conn: sqlite3.Connection, task_type: str) -> float | None:
    rows = conn.execute(
        "SELECT created_at, updated_at FROM tasks"
        " WHERE task_type = ? AND state = 'succeeded'"
        " ORDER BY updated_at DESC LIMIT 20",
        (task_type,),
    ).fetchall()
    durations: list[float] = []
    for row in rows:
        start = _parse(str(row["created_at"]))
        end = _parse(str(row["updated_at"]))
        if start is None or end is None:
            continue
        seconds = (end - start).total_seconds()
        if seconds >= 30:
            durations.append(seconds)
    return float(median(durations)) if durations else None


def compute(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    """任务行 → 可序列化进度块（API/MCP/通知共用）。"""
    state = str(row["state"])
    step = str(row["current_step"] or row["task_type"])
    floor = _STEP_FLOOR.get(step, 0)
    created = _parse(str(row["created_at"]))
    now = datetime.now(UTC)
    elapsed = max(0, int((now - created).total_seconds())) if created else 0

    if state in _TERMINAL:
        return {
            "stage": step,
            "progress_pct": 100,
            "elapsed_seconds": elapsed,
            "eta_seconds": 0,
            "estimated": False,
        }
    if state == "pending":
        return {
            "stage": step,
            "progress_pct": 0,
            "elapsed_seconds": elapsed,
            "eta_seconds": None,
            "estimated": False,
        }

    median_duration = _median_duration(conn, str(row["task_type"]))
    pct = floor
    eta: int | None = None
    estimated = False
    if median_duration and median_duration > 0 and state == "running":
        time_pct = min(95, int(elapsed / median_duration * 100))
        pct = max(floor, time_pct)
        eta = max(0, int(median_duration - elapsed))
        estimated = True
    if state == "awaiting_approval":
        pct = max(pct, 90)
    return {
        "stage": step,
        "progress_pct": max(0, min(100, pct)),
        "elapsed_seconds": elapsed,
        "eta_seconds": eta,
        "estimated": estimated,
    }
