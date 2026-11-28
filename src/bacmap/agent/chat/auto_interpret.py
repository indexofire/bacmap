"""里程碑自动解读：任务成功后，在链接了该任务的会话中自动触发一次简短解读。

设计边界（v1.10.60 增补）：

- 仅服务 **builtin** 后端的会话——external 后端对应用户本机的第三方 Agent 进程
  （拥有 shell/文件等通用能力），不在无人值守时由服务端代为唤起；
- 触发点为 ``task.state`` 事件中 ``state == "succeeded"``（终态一次性），
  不在 prelim 阶段重复触发，避免 token 双倍消耗；
- 去重持久化在 ``chat_auto_interpretations`` 表，**先记账后执行**——失败
  不重试（事件是观察性的，重试循环会在无人值守时持续烧 token）；
- 执行顺序串行（里程碑频率低），单次运行经 ``ChatOrchestrator.stream_run``
  耗尽异步迭代器即可——编排层的 ``_RunCollector`` 负责持久化，无需前端在线。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from bacmap.agent.chat.types import ChatActor
from bacmap.store.chat import ChatStore
from bacmap.store.users import Role, UserService
from bacmap.tasks.events import EventLog, EventType

if TYPE_CHECKING:
    from bacmap.agent.chat.service import ChatOrchestrator

log = logging.getLogger(__name__)

MILESTONE_SUCCEEDED = "succeeded"

PROMPT_TEMPLATE = (
    "任务 {task_id}（{task_type}）已成功完成。请使用可用工具查看该任务的分析结果，"
    "并用中文简要解读关键发现：物种鉴定与分型、重要的耐药/毒力命中、"
    "以及任何值得用户注意的质控问题。控制在 300 字以内，"
    "不要重复罗列全部原始数据，重点突出结论。"
)


def _legacy_actor() -> ChatActor:
    return ChatActor(
        user_id="local",
        username="web",
        role="admin",
        can_read_all=True,
        can_confirm_plans=True,
        is_admin=True,
    )


def actor_for_owner(db_path: Path, owner_user_id: str) -> ChatActor | None:
    """按会话属主构建操作者。

    ``local`` 是免登录/个人模式的哨兵属主，沿用服务端全权（与 Web 路由一致）；
    accounts 模式下查 users 表，用户被禁用或不存在则跳过（绝不升格为管理员）。
    """
    if owner_user_id == "local":
        return _legacy_actor()
    try:
        with UserService(db_path) as users:
            user = users.get(owner_user_id)
    except Exception:
        log.warning("auto-interpret: user lookup failed for %s", owner_user_id)
        return None
    if user is None or user.disabled:
        return None
    privileged = user.role in (Role.ADMIN, Role.ANALYST)
    return ChatActor(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        can_read_all=privileged,
        can_confirm_plans=privileged,
        is_admin=user.role == Role.ADMIN,
    )


def scan_pending(
    db_path: Path,
    events_db: Path,
    *,
    after: int,
    task_types: Callable[[str], str] | None = None,
) -> tuple[list[tuple[str, str, str]], int]:
    """扫描 succeeded 事件，返回 ``(session_id, task_id, task_type)`` 待办与游标。

    过滤规则：会话后端为 builtin（空值按默认 builtin 计）、未去过重。
    游标对所有事件照常推进（跳过的不回头重扫，与事件 API 语义一致）。
    """
    log_events = EventLog(events_db)
    events = log_events.list(after=after, limit=200)
    cursor = after
    pending: list[tuple[str, str, str]] = []
    for event in events:
        cursor = max(cursor, event.seq)
        if event.type is not EventType.TASK_STATE or not event.task_id:
            continue
        if str(event.payload.get("state", "")) != MILESTONE_SUCCEEDED:
            continue
        task_type = str(event.payload.get("task_type", "")) or (
            task_types(event.task_id) if task_types else ""
        )
        with ChatStore(db_path) as store:
            for session in store.sessions_for_task(event.task_id):
                backend = session.backend_id or "builtin"
                if backend != "builtin":
                    continue
                if store.has_auto_interpretation(
                    session.session_id, event.task_id, MILESTONE_SUCCEEDED,
                ):
                    continue
                pending.append((session.session_id, event.task_id, task_type))
    return pending, cursor


class AutoInterpreter:
    """后台线程：轮询事件表，对 builtin 会话执行一次性里程碑解读。"""

    def __init__(
        self,
        home: Path,
        orchestrator_factory: Callable[[], ChatOrchestrator],
        *,
        poll_seconds: float = 5.0,
    ) -> None:
        self._home = Path(home)
        self._factory = orchestrator_factory
        self._poll = max(1.0, poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db = self._home / "data" / "bacmap.sqlite"
        self._events_db = self._home / "tasks.sqlite"

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, name="chat-auto-interpret", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ---- 内部 -----------------------------------------------------------------

    def _run_loop(self) -> None:
        # 启动时把游标推到最新：只解读服务启动后新完成的任务，历史任务不补账。
        cursor = self._latest_seq()
        while not self._stop.wait(self._poll):
            try:
                cursor = self._scan_once(cursor)
            except Exception:
                log.exception("auto-interpret scan failed")

    def _latest_seq(self) -> int:
        try:
            with sqlite3.connect(self._events_db, timeout=30) as conn:
                row = conn.execute("SELECT MAX(seq) FROM events").fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0

    def _scan_once(self, cursor: int) -> int:
        if not self._db.is_file() or not self._events_db.is_file():
            return cursor
        pending, cursor = scan_pending(self._db, self._events_db, after=cursor)
        for session_id, task_id, task_type in pending:
            if self._stop.is_set():
                break
            self._interpret(session_id, task_id, task_type)
        return cursor

    def _interpret(self, session_id: str, task_id: str, task_type: str) -> None:
        with ChatStore(self._db) as store:
            session = None
            # sessions_for_task 已按 task 过滤；这里取回属主（跨用户，不用 owner 过滤）
            for s in store.sessions_for_task(task_id):
                if s.session_id == session_id:
                    session = s
                    break
            if session is None:
                return
            # 先记账：无论成败只尝试一次，避免无人值守的 token 重试循环。
            store.record_auto_interpretation(session_id, task_id, MILESTONE_SUCCEEDED)
        actor = actor_for_owner(self._db, session.owner_user_id)
        if actor is None:
            log.info("auto-interpret: skip session %s (owner unavailable)", session_id)
            return
        prompt = PROMPT_TEMPLATE.format(task_id=task_id, task_type=task_type or "analyze")
        try:
            orchestrator = self._factory()
            asyncio.run(self._drain(orchestrator, session_id, prompt, actor))
        except Exception:
            log.exception("auto-interpret run failed for session %s", session_id)

    @staticmethod
    async def _drain(
        orchestrator: ChatOrchestrator,
        session_id: str,
        prompt: str,
        actor: ChatActor,
    ) -> None:
        async for _event in orchestrator.stream_run(session_id, prompt, actor):
            pass  # 耗尽迭代器即完成持久化（_RunCollector 在 finally 中落库）


def start_auto_interpreter(
    home: Path,
    orchestrator_factory: Callable[[], ChatOrchestrator],
    *,
    poll_seconds: float = 5.0,
) -> AutoInterpreter:
    """启动后台自动解读线程（Web 进程内；chat 关闭或开关关闭时不调用）。"""
    interpreter = AutoInterpreter(home, orchestrator_factory, poll_seconds=poll_seconds)
    interpreter.start()
    return interpreter


__all__ = [
    "MILESTONE_SUCCEEDED",
    "PROMPT_TEMPLATE",
    "AutoInterpreter",
    "actor_for_owner",
    "scan_pending",
    "start_auto_interpreter",
]
