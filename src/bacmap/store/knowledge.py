"""本地文献知识库（引用门后端，ADR-07/V11⑥；文献查询员的导入暂存载体）。

GBrain 等外部知识后端为可选件（ADR-13）；本模块是内建默认实现：
SQLite + FTS5 全文检索；条目先入暂存（approved_by 为空），
人审 approve 后才成为引用门（citation gate）认可的可引用来源。
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'literature',
    title TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    source TEXT,
    identifier TEXT,
    content TEXT,
    imported_by TEXT,
    imported_at TEXT NOT NULL,
    approved_by TEXT,
    task_id TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, authors, content, identifier,
    content='knowledge_entries', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS knowledge_fts_ai AFTER INSERT ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(rowid, title, authors, content, identifier)
    VALUES (new.id, new.title, new.authors, new.content, new.identifier);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_ad AFTER DELETE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, authors, content, identifier)
    VALUES ('delete', old.id, old.title, old.authors, old.content, old.identifier);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_au AFTER UPDATE ON knowledge_entries BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, authors, content, identifier)
    VALUES ('delete', old.id, old.title, old.authors, old.content, old.identifier);
    INSERT INTO knowledge_fts(rowid, title, authors, content, identifier)
    VALUES (new.id, new.title, new.authors, new.content, new.identifier);
END;
"""

_FTS_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
_PMID_NORM_RE = re.compile(r"(?i)^pmid[:\s]*(\d{6,9})$")

_FIELDS = (
    "id, kind, title, authors, year, source, identifier, content,"
    " imported_by, imported_at, approved_by, task_id"
)


class KnowledgeStore:
    """knowledge.sqlite 的薄服务层（风格对齐 store.strain_metadata）。"""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = db_path
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        return conn

    def import_candidate(
        self,
        entry: dict[str, Any],
        imported_by: str,
        task_id: str | None = None,
    ) -> int:
        """入暂存区（未经人审，不算可引用来源）。"""
        if not str(entry.get("title", "")).strip():
            raise ValueError("knowledge entry requires a non-empty title")
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_entries"
                " (kind, title, authors, year, source, identifier, content,"
                "  imported_by, imported_at, task_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(entry.get("kind", "literature")),
                    str(entry["title"]),
                    entry.get("authors"),
                    entry.get("year"),
                    entry.get("source"),
                    entry.get("identifier"),
                    entry.get("content"),
                    imported_by,
                    now,
                    task_id,
                ),
            )
            return int(cur.lastrowid or 0)

    def approve(self, entry_id: int, approver: str) -> None:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE knowledge_entries SET approved_by = ? WHERE id = ?",
                (approver, entry_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"no knowledge entry {entry_id}")

    def get(self, entry_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_FIELDS} FROM knowledge_entries WHERE id = ?",  # noqa: S608 — _FIELDS 为模块常量
                (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_pending(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_FIELDS} FROM knowledge_entries"  # noqa: S608 — 片段为模块内常量/占位符拼装，值一律 ? 绑定
                " WHERE approved_by IS NULL ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 全文检索（含未审核条目，结果带 approved 标记供调用方判断）。

        任意用户输入安全：分词后逐词加引号（FTS5 短语语法），
        AND/OR/括号/未闭合引号等语法字符不再触发 fts5 syntax error。
        """
        match = " ".join(f'"{tok}"' for tok in _FTS_TOKEN_RE.findall(query))
        if not match:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_FIELDS} FROM knowledge_entries"  # noqa: S608 — 片段为模块内常量/占位符拼装，值一律 ? 绑定
                " WHERE id IN (SELECT rowid FROM knowledge_fts WHERE knowledge_fts MATCH ?)"
                " ORDER BY id LIMIT ?",
                (match, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def known_citations(self) -> list[str]:
        """已人审条目的标识符（DOI/PMID/登录号）——引用门的可引用集合。

        PMID 式标识符（"PMID:12345678"）规范化为纯数字，与引用门
        _CITE_RE 的捕获形态（gates.evaluate_citation 提取纯数字）对齐。
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT identifier FROM knowledge_entries"
                " WHERE approved_by IS NOT NULL AND identifier IS NOT NULL"
                " AND trim(identifier) != ''"
            ).fetchall()
        out: set[str] = set()
        for r in rows:
            ident = r["identifier"].strip()
            if not ident:  # 纯空白标识符不入可引用集合
                continue
            m = _PMID_NORM_RE.match(ident)
            if m:
                out.add(m.group(1))
            elif ident[:3].lower() == "10.":
                out.add(ident.lower())
            else:
                out.add(ident)
        return sorted(out)
