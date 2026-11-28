"""Web 控制台对话的会话与消息持久化（data/bacmap.sqlite，迁移 8）。

设计约束：

- 会话严格按 ``owner_user_id`` 隔离——所有读写都要求显式传入 owner，
  任何跨用户访问返回 None/False（接口层映射为 404，不泄露存在性）；
- 消息正文/思考过程/工具调用/卡片 JSON 存 TEXT 列，读取时经 pydantic 模型复原；
- 首条 user 消息自动生成会话标题（截断 60 字符），``updated_at`` 随活动推进。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from bacmap.store.schema import ensure_data_schema

CHAT_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id     TEXT PRIMARY KEY,
    owner_user_id  TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    backend_id     TEXT NOT NULL DEFAULT 'builtin',
    linked_tasks   TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
)
"""

CHAT_MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id     TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content        TEXT NOT NULL DEFAULT '',
    thinking       TEXT NOT NULL DEFAULT '',
    tool_calls     TEXT NOT NULL DEFAULT '[]',
    cards          TEXT NOT NULL DEFAULT '[]',
    backend_id     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL
)
"""

CHAT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner"
    " ON chat_sessions(owner_user_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session"
    " ON chat_messages(session_id, created_at ASC)",
)


CHAT_AUTO_INTERPRET_DDL = """
CREATE TABLE IF NOT EXISTS chat_auto_interpretations (
    session_id     TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    milestone      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (session_id, task_id, milestone)
)
"""

_TITLE_LEN = 60


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChatSession(BaseModel):
    session_id: str
    owner_user_id: str
    title: str = ""
    backend_id: str = "builtin"
    linked_tasks: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    backend_id: str = ""
    created_at: str


def _session_from(row: sqlite3.Row) -> ChatSession:
    try:
        linked = json.loads(str(row["linked_tasks"] or "[]"))
    except (TypeError, ValueError):
        linked = []
    return ChatSession(
        session_id=str(row["session_id"]),
        owner_user_id=str(row["owner_user_id"]),
        title=str(row["title"] or ""),
        backend_id=str(row["backend_id"] or "builtin"),
        linked_tasks=[str(t) for t in linked] if isinstance(linked, list) else [],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _message_from(row: sqlite3.Row) -> ChatMessage:
    def _load(raw: Any) -> list[dict[str, Any]]:
        try:
            value = json.loads(str(raw or "[]"))
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return ChatMessage(
        message_id=str(row["message_id"]),
        session_id=str(row["session_id"]),
        role=row["role"],
        content=str(row["content"] or ""),
        thinking=str(row["thinking"] or ""),
        tool_calls=_load(row["tool_calls"]),
        cards=_load(row["cards"]),
        backend_id=str(row["backend_id"] or ""),
        created_at=str(row["created_at"]),
    )


class ChatStore:
    """对话会话/消息持久化（上下文管理器，显式关闭连接）。"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 30000")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ChatStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 会话 ---------------------------------------------------------------

    def create_session(
        self,
        owner_user_id: str,
        *,
        title: str = "",
        backend_id: str = "builtin",
    ) -> ChatSession:
        now = _now()
        session_id = "cs_" + secrets.token_hex(8)
        self._conn.execute(
            "INSERT INTO chat_sessions"
            " (session_id, owner_user_id, title, backend_id, linked_tasks,"
            "  created_at, updated_at) VALUES (?,?,?,?,'[]',?,?)",
            (session_id, owner_user_id, title.strip()[:200], backend_id, now, now),
        )
        self._conn.commit()
        session = self.get_session(session_id, owner_user_id)
        if session is None:  # pragma: no cover — 插入成功却读不到只可能是库损坏
            raise RuntimeError("created chat session cannot be read back")
        return session

    def list_sessions(
        self, owner_user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ChatSession]:
        rows = self._conn.execute(
            "SELECT * FROM chat_sessions WHERE owner_user_id = ?"
            " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (owner_user_id, max(1, min(limit, 500)), max(0, offset)),
        ).fetchall()
        return [_session_from(r) for r in rows]

    def get_session(self, session_id: str, owner_user_id: str) -> ChatSession | None:
        row = self._conn.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ? AND owner_user_id = ?",
            (session_id, owner_user_id),
        ).fetchone()
        return _session_from(row) if row else None

    def update_session(
        self,
        session_id: str,
        owner_user_id: str,
        *,
        title: str | None = None,
        backend_id: str | None = None,
    ) -> ChatSession | None:
        if self.get_session(session_id, owner_user_id) is None:
            return None
        updates: list[str] = []
        params: list[Any] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title.strip()[:200])
        if backend_id is not None:
            updates.append("backend_id = ?")
            params.append(backend_id.strip()[:64])
        if not updates:
            return self.get_session(session_id, owner_user_id)
        updates.append("updated_at = ?")
        params.append(_now())
        params.extend((session_id, owner_user_id))
        self._conn.execute(
            "UPDATE chat_sessions SET " + ", ".join(updates)  # noqa: S608 — 列名由本模块常量拼装，值参数化
            + " WHERE session_id = ? AND owner_user_id = ?",
            params,
        )
        self._conn.commit()
        return self.get_session(session_id, owner_user_id)

    def link_task(self, session_id: str, owner_user_id: str, task_id: str) -> None:
        session = self.get_session(session_id, owner_user_id)
        if session is None:
            raise KeyError(session_id)
        if task_id not in session.linked_tasks:
            session.linked_tasks.append(task_id)
        self._conn.execute(
            "UPDATE chat_sessions SET linked_tasks = ?, updated_at = ?"
            " WHERE session_id = ? AND owner_user_id = ?",
            (json.dumps(session.linked_tasks), _now(), session_id, owner_user_id),
        )
        self._conn.commit()

    def sessions_for_task(self, task_id: str) -> list[ChatSession]:
        """跨用户查找链接了某任务的会话（里程碑自动解读用；调用方按 owner 自行授权）。"""
        rows = self._conn.execute(
            "SELECT * FROM chat_sessions WHERE linked_tasks LIKE ?",
            (f'%"{task_id}"%',),
        ).fetchall()
        return [_session_from(row) for row in rows]

    def has_auto_interpretation(self, session_id: str, task_id: str, milestone: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM chat_auto_interpretations"
            " WHERE session_id = ? AND task_id = ? AND milestone = ?",
            (session_id, task_id, milestone),
        ).fetchone()
        return row is not None

    def record_auto_interpretation(self, session_id: str, task_id: str, milestone: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO chat_auto_interpretations"
            " (session_id, task_id, milestone, created_at) VALUES (?,?,?,?)",
            (session_id, task_id, milestone, _now()),
        )
        self._conn.commit()

    def delete_session(self, session_id: str, owner_user_id: str) -> bool:
        if self.get_session(session_id, owner_user_id) is None:
            return False
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "DELETE FROM chat_messages WHERE session_id = ?", (session_id,)
            )
            self._conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ? AND owner_user_id = ?",
                (session_id, owner_user_id),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return True

    # ---- 消息 ---------------------------------------------------------------

    def append_message(
        self,
        session_id: str,
        owner_user_id: str,
        *,
        role: Literal["user", "assistant", "system"],
        content: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        cards: list[dict[str, Any]] | None = None,
        backend_id: str = "",
    ) -> ChatMessage:
        session = self.get_session(session_id, owner_user_id)
        if session is None:
            raise KeyError(session_id)
        now = _now()
        message_id = "cm_" + secrets.token_hex(8)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "INSERT INTO chat_messages"
                " (message_id, session_id, role, content, thinking, tool_calls,"
                "  cards, backend_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    thinking,
                    json.dumps(tool_calls or [], ensure_ascii=False),
                    json.dumps(cards or [], ensure_ascii=False),
                    backend_id,
                    now,
                ),
            )
            title_sql = ""
            params: list[Any] = []
            if not session.title and role == "user" and content.strip():
                title_sql = ", title = ?"
                params.append(content.strip()[:_TITLE_LEN])
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ?" + title_sql  # noqa: S608 — 列名由本模块常量拼装，值参数化
                + " WHERE session_id = ?",
                (now, *params, session_id),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return ChatMessage(
            message_id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            thinking=thinking,
            tool_calls=tool_calls or [],
            cards=cards or [],
            backend_id=backend_id,
            created_at=now,
        )

    def list_recent_messages(
        self, session_id: str, owner_user_id: str, *, limit: int = 200
    ) -> list[ChatMessage]:
        """最近 N 条消息（按时间倒序取后反转为正序）——长会话传最近上下文。"""
        if self.get_session(session_id, owner_user_id) is None:
            raise KeyError(session_id)
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ?"
            " ORDER BY created_at DESC, message_id DESC LIMIT ?",
            (session_id, max(1, min(limit, 2000))),
        ).fetchall()
        return [_message_from(r) for r in reversed(rows)]

    def list_messages(
        self, session_id: str, owner_user_id: str, *, limit: int = 200
    ) -> list[ChatMessage]:
        if self.get_session(session_id, owner_user_id) is None:
            raise KeyError(session_id)
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ?"
            " ORDER BY created_at ASC, message_id ASC LIMIT ?",
            (session_id, max(1, min(limit, 2000))),
        ).fetchall()
        return [_message_from(r) for r in rows]
