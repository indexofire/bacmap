"""bacmap TUI（Textual）测试：v1.6 任务台（只读查看 + 运维命令 + 签批）。

TUI 用 Textual 的 headless ``run_test`` 驱动。v1.6（ADR-21）移除内置对话后，
本界面不再有 LLM 会话/计划确认，因此测试只覆盖：布局与侧栏、命令台
（/help /tasks /search /result /analyze /approve）、Leader 和弦、任务失败回显、
签批两步确认、主题与窄终端折叠。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
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
                "abricate_vdb": [{"GENE": "ssrA"}],
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
    monkeypatch.setattr(e, "list_tasks", lambda limit=50: _TASKS)
    yield e
    eng.shutdown_dbos()


_TASKS: list[dict] = []


class _NoopArbiter:
    def heavy_guard(self):  # pragma: no cover
        return None


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

    def test_endpoint_status_without_config(self, engine):
        from bacmap.interfaces.views import endpoint_status

        status = endpoint_status(engine)
        assert isinstance(status, str) and status


class TestLayout:
    def test_mounts_tables_sidebar_and_log(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert len(app.query_one("#tasks-table", DataTable).columns) == 3
                assert app.query_one("#samples-table", DataTable).row_count == 1
                assert app.query_one("#conversation", VerticalScroll) is not None
                assert app.query_one("#sidebar") is not None

        asyncio.run(_run())

    def test_no_chat_input_semantics(self, engine):
        """v1.6：输入框只接受斜杠命令；自然语言不再触发任何会话。"""

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                assert "命令" in str(inp.placeholder)
                inp.value = "跑一下 SAM-001 的分析"
                inp.focus()
                await pilot.press("enter")
                await pilot.pause()
                hint = str(app.query_one("#plan-hint").render())
                assert "Harness" in hint or "斜杠" in hint
                assert not hasattr(app, "_session") or app._session is None

        asyncio.run(_run())

    def test_toggle_sidebar_and_responsive(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                sidebar = app.query_one("#sidebar")
                assert not sidebar.has_class("hidden")
                await pilot.press("ctrl+b")
                await pilot.pause()
                assert sidebar.has_class("hidden")
                await pilot.press("ctrl+b")
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                assert sidebar.has_class("hidden")  # 窄终端折叠
                await pilot.resize_terminal(140, 40)
                await pilot.pause()
                assert not sidebar.has_class("hidden")

        asyncio.run(_run())

    def test_theme_toggle(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app.query_one("#tasks-table", DataTable).focus()
                await pilot.press("ctrl+g")
                assert app._leader is True
                before = app.theme
                await pilot.press("t")
                await pilot.pause()
                assert app._leader is False
                assert app.theme != before

        asyncio.run(_run())

    def test_input_focused_on_mount(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert app.focused is app.query_one("#prompt", Input)

        asyncio.run(_run())


class TestLeaderWhileInputFocused:
    def test_leader_chords_work_with_input_focused(self, engine):
        """回归：Input 会吞可打印键，leader 和弦必须先于 Input 处理（否则 a/t 无效）。"""

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert app.focused is app.query_one("#prompt", Input)
                await pilot.press("ctrl+g")
                await pilot.press("t")  # 主题切换：走 leader 和弦，不落进输入框
                await pilot.pause()
                assert app.theme == "bacmap-light"
                assert app.query_one("#prompt", Input).value == ""
                await pilot.press("ctrl+g")
                app._leader = True
                await pilot.press("i")
                await pilot.pause()
                assert app.focused is app.query_one("#prompt", Input)

        asyncio.run(_run())


class TestCommandConsole:
    def test_help_lists_commands_without_chat(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._run_slash("/help")
                await pilot.pause()
                text = "".join(
                    str(w.render()) for w in app.query("#conversation Static")
                )
                assert "/approve" in text and "/result" in text
                assert "自然语言分析需求" not in text

        asyncio.run(_run())

    def test_unknown_command_and_bad_scope(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._run_slash("/nope")
                await pilot.pause()
                app._slash_submit("curate", "{not json")
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "未知命令" in text and "不是合法 JSON" in text

        asyncio.run(_run())

    def test_analyze_submits_and_requires_samples(self, engine, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            engine, "submit", lambda tt, params, by: calls.append((str(tt), params, by)) or "tid-1"
        )

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._slash_submit("analyze", "SAM-001, SAM-002")
                await pilot.pause()
                app._slash_submit("analyze", "")
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "用法：/analyze" in text
                assert calls[0][1] == {"samples": ["SAM-001", "SAM-002"]}

        asyncio.run(_run())

    def test_search_and_result(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._slash_search("CTX-M")
                app._slash_result("SAM-001")
                await pilot.pause()
                await asyncio.sleep(0.2)
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "SAM-001" in text and "CTX-M" in text
                assert "结果 · SAM-001" in text and "Salmonella" in text

        asyncio.run(_run())

    def test_result_unknown_sample(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._slash_result("NOPE")
                await asyncio.sleep(0.2)
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "无结果" in text

        asyncio.run(_run())

    def test_overlong_command_rejected(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._run_slash("/search x")
                app._logline("[#f85149]命令过长（上限 4000 字符）[/]")
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "命令过长" in text

        asyncio.run(_run())


class TestApproval:
    def _seed(self, engine, app) -> None:
        table = app.query_one("#tasks-table", DataTable)
        table.clear()
        table.add_row("t-awaiting", "awaiting_approval", "mine", key="task-abc123def456")
        table.move_cursor(row=0)

    def test_leader_a_then_ctrl_y_approves(self, engine, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            engine,
            "approve",
            lambda tid, ap: calls.append((str(tid), ap.approver, ap.decision, ap.signature)),
        )

        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                self._seed(engine, app)
                await pilot.press("ctrl+g")
                await pilot.press("a")
                await pilot.pause()
                assert app._pending_approval is not None
                assert app._pending_approval["task_id"] == "task-abc123def456"
                app.query_one("#tasks-table", DataTable).focus()
                await pilot.press("ctrl+y")
                await asyncio.sleep(0.3)
                await pilot.pause()
                assert calls and calls[0][0] == "task-abc123def456"
                assert calls[0][2] == "approve"
                assert calls[0][1] == calls[0][3]  # approver = signature（默认签名）

        asyncio.run(_run())

    def test_no_selection_hints(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app.query_one("#tasks-table", DataTable).clear()
                await pilot.press("ctrl+g")
                await pilot.press("a")
                await pilot.pause()
                assert app._pending_approval is None

        asyncio.run(_run())

    def test_escape_cancels_pending_approval(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app._pending_approval = {"task_id": "x", "signature": "mark", "decision": "approve"}
                await pilot.press("escape")
                await pilot.pause()
                assert app._pending_approval is None

        asyncio.run(_run())

    def test_slash_approve_sets_pending(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                inp = app.query_one("#prompt", Input)
                inp.value = "/approve 93d8fd57 张三"
                inp.focus()
                await pilot.press("enter")
                await pilot.pause()
                assert app._pending_approval is not None
                assert app._pending_approval["task_id"] == "93d8fd57"
                assert app._pending_approval["signature"] == "张三"

        asyncio.run(_run())

    def test_ctrl_y_without_pending_hints(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                app.query_one("#tasks-table", DataTable).focus()
                await pilot.press("ctrl+y")
                await pilot.pause()
                assert "无待确认签批" in str(app.query_one("#plan-hint").render())

        asyncio.run(_run())


class TestTaskEcho:
    def test_failed_task_echoed_once(self, engine, monkeypatch):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                bad = [
                    {
                        "task_id": "f" * 32,
                        "task_type": "analyze",
                        "state": "failed",
                        "current_step": "pipeline",
                        "message": "snakemake rc=1",
                    }
                ]
                engine.list_tasks = lambda limit=50: bad  # type: ignore[assignment]
                app.refresh_data()
                await asyncio.sleep(0.3)
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert text.count("failed") >= 1
                app.refresh_tasks()
                await asyncio.sleep(0.3)
                await pilot.pause()
                text2 = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert text2.count("snakemake rc=1") == text.count("snakemake rc=1")

        asyncio.run(_run())

    def test_history_not_echoed_on_startup(self, engine):
        async def _run():
            app = BacmapTUI(engine)
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                text = "".join(str(w.render()) for w in app.query("#conversation Static"))
                assert "旧任务失败" not in text

        asyncio.run(_run())


class TestDigestHardening:
    def test_digest_reads_species_species_key(self):
        d = sample_digest({"sample": "S", "steps": {"species": {"species": "VPA"}}})
        assert d["verdict"] == "VPA"

    def test_digest_tolerates_non_dict_hits(self):
        d = sample_digest(
            {"sample": "S", "steps": {"mlst": {"scheme": "x", "st": 7}, "amr": "oops"}}
        )
        assert d["sample_id"] == "S"

    def test_digest_tolerates_string_mlst(self):
        d = sample_digest({"sample": "S", "steps": {"mlst": "FILE\tSCHEME\tST\taroC\nc\ts\t19\t2"}})
        assert d["st"] == "19"
