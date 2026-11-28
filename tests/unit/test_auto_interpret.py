"""里程碑自动解读：扫描过滤、属主授权与去重的单元测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bacmap.agent.chat.auto_interpret import (
    MILESTONE_SUCCEEDED,
    actor_for_owner,
    scan_pending,
)
from bacmap.store.chat import ChatStore
from bacmap.store.schema import data_migrations, migrate
from bacmap.store.users import Role, UserService
from bacmap.tasks.events import EventLog, EventType


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


def _db(home: Path) -> Path:
    return home / "data" / "bacmap.sqlite"


def _events_db(home: Path) -> Path:
    return home / "tasks.sqlite"


def _succeeded(home: Path, task_id: str) -> None:
    EventLog(_events_db(home)).append(
        EventType.TASK_STATE, task_id=task_id, payload={"state": "succeeded"},
    )


def _linked_session(home: Path, owner: str, task_id: str, backend: str = "builtin") -> str:
    with ChatStore(_db(home)) as store:
        session = store.create_session(owner, backend_id=backend)
        store.link_task(session.session_id, owner, task_id)
        return session.session_id


class TestScanPending:
    def test_linked_builtin_session_is_pending(self, home: Path):
        sid = _linked_session(home, "local", "t1")
        _succeeded(home, "t1")
        pending, cursor = scan_pending(_db(home), _events_db(home), after=0)
        assert [(s, t) for s, t, _ in pending] == [(sid, "t1")]
        assert cursor > 0

    def test_external_backend_session_skipped(self, home: Path):
        _linked_session(home, "local", "t1", backend="hermes")
        _succeeded(home, "t1")
        pending, _ = scan_pending(_db(home), _events_db(home), after=0)
        assert pending == []

    def test_dedupe_record_suppresses_repeat(self, home: Path):
        sid = _linked_session(home, "local", "t1")
        with ChatStore(_db(home)) as store:
            store.record_auto_interpretation(sid, "t1", MILESTONE_SUCCEEDED)
        _succeeded(home, "t1")
        pending, _ = scan_pending(_db(home), _events_db(home), after=0)
        assert pending == []

    def test_non_terminal_states_ignored_but_cursor_advances(self, home: Path):
        sid = _linked_session(home, "local", "t1")
        log = EventLog(_events_db(home))
        log.append(EventType.TASK_STATE, task_id="t1", payload={"state": "running"})
        log.append(EventType.TASK_STATE, task_id="t1", payload={"state": "failed"})
        pending, cursor = scan_pending(_db(home), _events_db(home), after=0)
        assert pending == []
        assert cursor == 2
        # 后续成功事件仍能被扫到（游标语义正确）
        _succeeded(home, "t1")
        pending, cursor2 = scan_pending(_db(home), _events_db(home), after=cursor)
        assert [(s, t) for s, t, _ in pending] == [(sid, "t1")]
        assert cursor2 > cursor

    def test_unlinked_task_produces_nothing(self, home: Path):
        _linked_session(home, "local", "t1")
        _succeeded(home, "t-other")
        pending, _ = scan_pending(_db(home), _events_db(home), after=0)
        assert pending == []


class TestActorForOwner:
    def test_legacy_local_owner_is_admin_equivalent(self, home: Path):
        migrate(_db(home), data_migrations())
        actor = actor_for_owner(_db(home), "local")
        assert actor is not None and actor.is_admin and actor.can_confirm_plans

    def test_real_user_role_mapping(self, home: Path):
        migrate(_db(home), data_migrations())
        with UserService(_db(home)) as users:
            user = users.create("analyst1", password="Str0ng!pass", role=Role.ANALYST)
        actor = actor_for_owner(_db(home), user.user_id)
        assert actor is not None
        assert actor.role == "analyst" and actor.can_confirm_plans and not actor.is_admin

    def test_disabled_or_missing_user_returns_none(self, home: Path):
        migrate(_db(home), data_migrations())
        with UserService(_db(home)) as users:
            user = users.create("user01", password="Str0ng!pass", role=Role.USER)
            users.set_disabled(user.user_id, True)
        assert actor_for_owner(_db(home), user.user_id) is None
        assert actor_for_owner(_db(home), "u-nonexistent") is None


class TestMigration:
    def test_dedupe_table_created_by_migration_9(self, home: Path):
        migrate(_db(home), data_migrations())
        with sqlite3.connect(_db(home)) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name='chat_auto_interpretations'",
            ).fetchone()
        assert row is not None

    def test_dedupe_roundtrip(self, home: Path):
        migrate(_db(home), data_migrations())
        with ChatStore(_db(home)) as store:
            assert not store.has_auto_interpretation("s1", "t1", MILESTONE_SUCCEEDED)
            store.record_auto_interpretation("s1", "t1", MILESTONE_SUCCEEDED)
            assert store.has_auto_interpretation("s1", "t1", MILESTONE_SUCCEEDED)
            # 幂等：重复记账不报错（INSERT OR IGNORE）
            store.record_auto_interpretation("s1", "t1", MILESTONE_SUCCEEDED)
