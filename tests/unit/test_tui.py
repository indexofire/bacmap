"""bacmap TUI（Textual）冒烟测试 + 共享视图层测试。

TUI 用 Textual 的 headless ``run_test`` 驱动：验证挂载、侧栏、leader 和弦、
斜杠命令、会话规划与确认提交（会话/执行注入，无需真实 LLM）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import DataTable, Input

from bacmap.interfaces.tui.app import BacmapTUI
from bacmap.interfaces.views import (
    load_summaries,
    overview_data,
    report_path,
    sample_digest,
    sample_rows,
    search_rows,
)


def _summary(sample: str, species: str = "Salmonella") -> dict:
    return {
        "sample": sample,
        "steps": {
            "species": {"verdict": species},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {
                "abricate_card": [{"GENE": "blaCTX-M-15"}],
                "abricate_vfdb": [{"GENE": "ssrA"}],
            },
            "plasmid": {"plasmidfinder": [{"GENE": "IncFIB"}]},
            "dec": {},
        },
    }


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    import bacmap.tasks.engine.dbos_engine as eng

    rep = tmp_path / "results" / "SAM-001" / "report"
    rep.mkdir(parents=True)
    (rep / "SAM-001_summary.json").write_text(json.dumps(_summary("SAM-001")), encoding="utf-8")
    monkeypatch.setattr(eng, "_memory_arbiter", lambda: _NoopArbiter())
    e = eng.DbosTaskEngine(tmp_path)
    yield e
    eng.shutdown_dbos()


class _NoopArbiter:
    def heavy_guard(self):  # pragma: no cover
        return None


async def _respond_async_ok(self, text):
    from bacmap.agent.session import AgentReply, AnalysisPlan, PlannedTask

    return AgentReply(
        message="ok",
        plan=AnalysisPlan(
            reply="ok",
            tasks=[PlannedTask(task_type="mine", params={"script": "print(1)"})],
        ),
    )


class TestViews:
    def test_overview_and_samples(self, engine):
        ov = overview_data(engine)
        assert ov["paths"]["BACMAP_HOME"] == str(engine.home)
        rows = sample_rows(engine)
        assert [r["sample_id"] for r in rows] == ["SAM-001"]
        assert rows[0]["st"] == "19"

    def test_digest_and_search(self, engine):
        rows = sample_rows(engine)
        assert search_rows(rows, query="CTX-M") == rows
        assert search_rows(rows, query="nope") == []
        assert search_rows(rows, mlst_st="19") == rows
        assert search_rows(rows, mlst_st="99") == []

    def test_report_path_and_summaries(self, engine):
        assert load_summaries(engine)[0]["_sample_id"] == "SAM-001"
        assert report_path(engine, "SAM-001").name == "SAM-001_report.html"
        assert sample_digest({"sample": "X", "steps": {}})["sample_id"] == "X"


class TestTuiLayout:
    def test_mounts_with_sidebar_and_tables(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert len(app.query_one("#tasks-table", DataTable).columns) == 3
                assert len(app.query_one("#samples-table", DataTable).columns) == 3
                assert app.query_one("#samples-table", DataTable).row_count == 1
                assert app.query_one("#sidebar") is not None

        asyncio.run(_run())

    def test_toggle_sidebar(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                sidebar = app.query_one("#sidebar")
                assert not sidebar.has_class("hidden")
                await pilot.press("ctrl+b")
                await pilot.pause()
                assert sidebar.has_class("hidden")

        asyncio.run(_run())

    def test_leader_chord_toggles_theme(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app.query_one("#tasks-table", DataTable).focus()  # 避免 Input 吞键
                await pilot.press("ctrl+x")
                assert app._leader is True
                before = app.theme
                await pilot.press("t")
                await pilot.pause()
                assert app._leader is False
                assert app.theme != before

        asyncio.run(_run())


class TestTuiSlash:
    def test_help_and_unknown_command(self, engine, monkeypatch):
        async def _run():
            app = BacmapTUI(engine)
            captured: list[str] = []
            async with app.run_test(size=(140, 40)) as pilot:
                app._chat_append = lambda m: captured.append(m)
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "/nope"
                inp.focus()
                await pilot.press("enter")
                await pilot.pause()
                assert any("未知命令" in c for c in captured)

        asyncio.run(_run())

    def test_slash_analyze_submits(self, engine, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            engine, "submit", lambda tt, params, by: submitted.append((str(tt), params)) or "t1"
        )

        async def _run():
            app = BacmapTUI(engine)
            captured: list[str] = []
            async with app.run_test(size=(140, 40)) as pilot:
                app._chat_append = lambda m: captured.append(m)
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "/analyze SAM-001"
                inp.focus()
                await pilot.press("enter")
                await asyncio.sleep(0.4)
                await pilot.pause()
                assert submitted and submitted[0][0] == "analyze"

        asyncio.run(_run())


class TestTuiChat:
    def test_chat_plan_and_confirm(self, engine, monkeypatch):
        from bacmap.agent.session import AgentReply, AnalysisPlan, PlannedTask
        from bacmap.interfaces import assistant as A

        class _FakeSession:
            async def respond_async(self, text):
                return AgentReply(
                    message="规划完成",
                    plan=AnalysisPlan(
                        reply="规划完成",
                        tasks=[PlannedTask(task_type="analyze", params={"samples": ["SAM-001"]})],
                    ),
                )

        monkeypatch.setattr(
            A, "build_session", lambda engine, submitted_by="assistant": _FakeSession()
        )
        submitted: list = []
        monkeypatch.setattr(
            A,
            "execute_plan",
            lambda engine, plan, submitted_by="assistant": (
                submitted.append(plan),
                [{"task_type": "analyze", "task_id": "t1", "ok": True}],
            )[1],
        )

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "跑 SAM-001 的分析"
                inp.focus()
                await pilot.press("enter")
                await asyncio.sleep(0.5)
                await pilot.pause()
                assert app._pending_plan is not None
                app.query_one("#tasks-table", DataTable).focus()  # ctrl+y 不被 Input 吞
                await pilot.press("ctrl+y")
                await asyncio.sleep(0.5)
                await pilot.pause()
                assert submitted

        asyncio.run(_run())

    def test_escape_discards_pending_plan(self, engine, monkeypatch):
        from bacmap.interfaces import assistant as A

        monkeypatch.setattr(
            A,
            "build_session",
            lambda engine, submitted_by="assistant": type(
                "_S",
                (),
                {"respond_async": _respond_async_ok},
            )(),
        )

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "统计一下"
                inp.focus()
                await pilot.press("enter")
                await asyncio.sleep(0.5)
                await pilot.pause()
                assert app._pending_plan is not None
                await pilot.press("escape")
                await pilot.pause()
                assert app._pending_plan is None

        asyncio.run(_run())


class TestSkillGuidelines:
    """tui-design 技能要点：不可信文本转义、跟随模式、响应式折叠。"""

    def test_untrusted_reply_text_escaped(self, engine):
        from bacmap.agent.session import AgentReply

        async def _run():
            app = BacmapTUI(engine)
            captured: list[str] = []
            async with app.run_test(size=(140, 40)) as pilot:
                app._chat_append = lambda m: captured.append(m)
                await pilot.pause()
                app._chat_reply(AgentReply(message="[red]boom[/red] 控制序列 \x1b[2JA"))
                joined = "".join(captured)
                assert "\\[red]" in joined  # 已被转义，不会当作 Rich 标记
                assert "\x1b[2JA" in joined  # 控制字符原样保留但作为文本渲染

        asyncio.run(_run())

    def test_follow_toggle(self, engine):
        from textual.widgets import RichLog

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app.query_one("#tasks-table", DataTable).focus()
                assert app.query_one("#conversation", RichLog).auto_scroll is True
                await pilot.press("ctrl+f")
                await pilot.pause()
                assert app._follow is False
                assert app.query_one("#conversation", RichLog).auto_scroll is False

        asyncio.run(_run())

    def test_responsive_sidebar_collapse(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                sidebar = app.query_one("#sidebar")
                assert not sidebar.has_class("hidden")
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                assert sidebar.has_class("hidden")  # 窄终端折叠
                await pilot.resize_terminal(140, 40)
                await pilot.pause()
                assert not sidebar.has_class("hidden")  # 恢复宽度回归

        asyncio.run(_run())


class TestTuiAsyncCancel:
    """异步会话：Esc 取消在途 LLM 请求（异步 worker 真正 cancel）。"""

    def test_escape_cancels_inflight_worker(self, engine, monkeypatch):
        from bacmap.interfaces import assistant as A

        class _SlowSession:
            async def respond_async(self, text):
                await asyncio.sleep(30)
                raise AssertionError("should have been cancelled")

        monkeypatch.setattr(
            A, "build_session", lambda engine, submitted_by="assistant": _SlowSession()
        )

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "慢请求"
                inp.focus()
                await pilot.press("enter")
                await asyncio.sleep(0.2)
                worker = app._chat_task
                assert worker is not None and not worker.is_finished
                await pilot.press("escape")
                await asyncio.sleep(0.3)
                assert worker.is_cancelled

        asyncio.run(_run())


class TestTuiTheme:
    def test_registers_and_toggles_bacmap_themes(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert app.theme == "bacmap-dark"
                app.query_one("#tasks-table", DataTable).focus()
                await pilot.press("ctrl+x")
                await pilot.press("t")
                await pilot.pause()
                assert app.theme == "bacmap-light"

        asyncio.run(_run())
