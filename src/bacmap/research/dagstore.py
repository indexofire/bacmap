"""DAG 执行状态的持久化：运行、节点、内容寻址产物（P1）。

产物以规范化 JSON 落盘（``$BACMAP_HOME/artifacts/<aa>/<sha256>.json``），
``artifact_id = sha256:<hex>``。同一内容重复写入是幂等的——缓存与重放都依赖
这一点。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bacmap.research.store import RESEARCH_MIGRATIONS, research_db_path
from bacmap.store.migrations import migrate


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DagStore:
    """DAG 运行状态与产物库（单连接，显式提交）。"""

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.db = research_db_path(home)
        migrate(self.db, RESEARCH_MIGRATIONS)
        self.artifacts_dir = self.home / "artifacts"
        self._conn = sqlite3.connect(str(self.db), timeout=30)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> DagStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- run ----------------------------------------------------------

    def ensure_run(self, task_id: str, dag_hash: str, data_class: int) -> None:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO dag_runs"
                " (task_id, dag_hash, state, data_class, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(task_id) DO UPDATE SET dag_hash=excluded.dag_hash,"
                " data_class=excluded.data_class, updated_at=excluded.updated_at",
                (task_id, dag_hash, "running", data_class, now, now),
            )

    def set_run_state(self, task_id: str, state: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE dag_runs SET state = ?, updated_at = ? WHERE task_id = ?",
                (state, _now(), task_id),
            )

    def get_run(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM dag_runs WHERE task_id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    # ---- nodes --------------------------------------------------------

    def completed_nodes(self, task_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT node_id FROM dag_nodes WHERE task_id = ? AND state = 'succeeded'",
            (task_id,),
        ).fetchall()
        return {str(row["node_id"]) for row in rows}

    def node_outputs(self, task_id: str, node_id: str) -> dict[str, str]:
        row = self._conn.execute(
            "SELECT outputs_json FROM dag_nodes WHERE task_id = ? AND node_id = ?",
            (task_id, node_id),
        ).fetchone()
        if row is None:
            return {}
        return {str(k): str(v) for k, v in json.loads(row["outputs_json"]).items()}

    def mark_running(self, task_id: str, node_id: str, op: str) -> None:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO dag_nodes (task_id, node_id, op, state, started_at)"
                " VALUES (?,?,?,'running',?)"
                " ON CONFLICT(task_id, node_id) DO UPDATE SET"
                " state='running', op=excluded.op, error='', started_at=excluded.started_at",
                (task_id, node_id, op, now),
            )

    def mark_succeeded(
        self, task_id: str, node_id: str, outputs: dict[str, str], *, cache_hit: bool = False
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE dag_nodes SET state='succeeded', outputs_json=?, error='',"
                " cache_hit=?, finished_at=? WHERE task_id=? AND node_id=?",
                (
                    json.dumps(outputs, sort_keys=True),
                    1 if cache_hit else 0,
                    _now(),
                    task_id,
                    node_id,
                ),
            )

    def mark_failed(self, task_id: str, node_id: str, error: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO dag_nodes (task_id, node_id, op, state, error, finished_at)"
                " VALUES (?,?,?,'failed',?,?)"
                " ON CONFLICT(task_id, node_id) DO UPDATE SET"
                " state='failed', error=excluded.error, finished_at=excluded.finished_at",
                (task_id, node_id, "", error[:4000], _now()),
            )

    def node_rows(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM dag_nodes WHERE task_id = ? ORDER BY rowid", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- cache（P6） ---------------------------------------------------

    def cache_get(self, key: str) -> dict[str, str] | None:
        row = self._conn.execute(
            "SELECT outputs_json FROM dag_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE dag_cache SET hits = hits + 1, last_hit_at = ? WHERE cache_key = ?",
                (_now(), key),
            )
        return {str(k): str(v) for k, v in json.loads(row["outputs_json"]).items()}

    def cache_put(self, key: str, op: str, outputs: dict[str, str]) -> None:
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO dag_cache (cache_key, op, outputs_json, created_at, last_hit_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(cache_key) DO UPDATE SET outputs_json=excluded.outputs_json",
                (key, op, json.dumps(outputs, sort_keys=True), now, now),
            )

    # ---- artifacts ----------------------------------------------------

    def put_artifact(
        self,
        *,
        type_: str,
        value: Any,
        task_id: str,
        node_id: str,
        data_class: int = 2,
    ) -> str:
        payload = json.dumps(
            {"type": type_, "value": value}, sort_keys=True, ensure_ascii=False
        ).encode()
        digest = hashlib.sha256(payload).hexdigest()
        artifact_id = f"sha256:{digest}"
        path = self.artifacts_dir / digest[:2] / f"{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(payload)
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO dag_artifacts (artifact_id, type, sha256, path,"
                " producer_task, producer_node, data_class, size_bytes, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    artifact_id,
                    type_,
                    digest,
                    str(path.relative_to(self.home)),
                    task_id,
                    node_id,
                    data_class,
                    len(payload),
                    now,
                ),
            )
        return artifact_id

    def load_artifact(self, artifact_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT path FROM dag_artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no such artifact: {artifact_id}")
        path = self.home / str(row["path"])
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return dict(loaded)

    def gc(self, *, keep_days: int = 0, dry_run: bool = True) -> dict[str, Any]:
        """删除无引用的产物（节点输出 + Text.claims 证据之外）。"""
        referenced: set[str] = set()
        for row in self._conn.execute("SELECT outputs_json FROM dag_nodes"):
            referenced |= {str(v) for v in json.loads(row["outputs_json"]).values()}
        for row in self._conn.execute(
            "SELECT artifact_id FROM dag_artifacts WHERE type = 'Text'"
        ):
            try:
                payload = self.load_artifact(str(row["artifact_id"]))
            except (KeyError, OSError, ValueError):
                continue
            for claim in (payload.get("value") or {}).get("claims", []):
                referenced |= {str(item) for item in claim.get("evidence", [])}

        cutoff = datetime.now(UTC) - timedelta(days=max(0, keep_days))
        rows = self._conn.execute("SELECT * FROM dag_artifacts").fetchall()
        targets = [
            dict(row)
            for row in rows
            if str(row["artifact_id"]) not in referenced
            and str(row["created_at"]) < cutoff.isoformat()
        ]
        total_bytes = sum(int(row["size_bytes"]) for row in targets)
        if not dry_run:
            for row in targets:
                self._conn.execute(
                    "DELETE FROM dag_artifacts WHERE artifact_id = ?", (row["artifact_id"],)
                )
                path = self.home / str(row["path"])
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
            self._conn.commit()
        return {
            "dry_run": dry_run,
            "artifacts": len(targets),
            "bytes": total_bytes,
            "ids": [row["artifact_id"] for row in targets],
        }

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """任务可见产物：本任务产出的 + 本任务节点引用的（含缓存复用）。

        缓存命中时产物由别的任务产出，但仍须能从当前任务列出/导出。
        """
        used: set[str] = set()
        for row in self._conn.execute(
            "SELECT outputs_json FROM dag_nodes WHERE task_id = ?", (task_id,)
        ):
            used |= {str(v) for v in json.loads(row["outputs_json"]).values()}
        if not used:
            rows = self._conn.execute(
                "SELECT * FROM dag_artifacts WHERE producer_task = ? ORDER BY rowid",
                (task_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        placeholders = ",".join("?" * len(used))
        rows = self._conn.execute(
            f"SELECT * FROM dag_artifacts WHERE producer_task = ?"  # noqa: S608
            f" OR artifact_id IN ({placeholders}) ORDER BY rowid",
            (task_id, *sorted(used)),
        ).fetchall()
        return [dict(row) for row in rows]
