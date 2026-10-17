"""bacmap 全屏 TUI（Textual）——会话优先的工作台。

设计参考：
- **opencode TUI**：leader 键（``Ctrl+X``）和弦、命令面板（``Ctrl+P``）、侧栏开关、
  会话/消息导航、状态视图；
- **hermes agent**：对话优先的 REPL、``/`` 斜杠命令、``Esc`` 中断语义、``Tab`` 补全。

布局：Header（端点状态）→ Sidebar（任务/样本，``Ctrl+B`` 折叠）+ 会话日志 + 输入框
→ Footer（按键提示）。助手即会话：规划 → 确认（``Ctrl+Y``）→ 提交；写操作分级确认。
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.markup import escape as _esc
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
)

# 侧栏自动折叠阈值（tui-design：窄终端折叠次要面板，恢复时保留选择）
_SIDEBAR_MIN_WIDTH = 96
# 单轮需求文本上限（与 Web 一致，防超大提示词）
_MAX_PROMPT_LEN = 8000

# 语义调色板（对齐 opencode 的克制暗色 + hermes skin 的语义槽 + tui-design 技能）。
# 主题值集中在 Theme.variables，CSS 只用语义槽，不写死颜色。
_BACMAP_DARK = Theme(
    name="bacmap-dark",
    primary="#7170ff",
    secondary="#8b8bf5",
    accent="#7170ff",
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    foreground="#e6edf3",
    background="#0d1117",
    surface="#161b22",
    panel="#21262d",
    dark=True,
    variables={
        "text-muted": "#8b949e",
        "border": "#30363d",
        "tool": "#d2a8ff",
        "thinking": "#8b949e",
        "user": "#79c0ff",
        "assistant": "#3fb950",
    },
)
_BACMAP_LIGHT = Theme(
    name="bacmap-light",
    primary="#4f46e5",
    secondary="#6366f1",
    accent="#4f46e5",
    success="#1a7f37",
    warning="#9a6700",
    error="#cf222e",
    foreground="#1f2328",
    background="#ffffff",
    surface="#f6f8fa",
    panel="#eaeef2",
    dark=False,
    variables={
        "text-muted": "#59636e",
        "border": "#d0d7de",
        "tool": "#8250df",
        "thinking": "#59636e",
        "user": "#0969da",
        "assistant": "#1a7f37",
    },
)

_CSS = """
Screen { background: $background; }
#sidebar { width: 38; border-right: solid $border; background: $surface; }
#sidebar.hidden { display: none; }
.side-title { padding: 0 1; color: $text-muted; text-style: bold; }
#tasks-table, #samples-table { height: 1fr; }
#main { width: 1fr; }
#conversation { height: 1fr; padding: 0 2; }
#plan-hint { padding: 0 2; color: $warning; height: auto; }
#prompt { dock: bottom; border: round $border; }
#prompt:focus { border: round $accent; }
"""

_HELP = (
    "[b #3fb950]bacmap 会话助手[/]\n"
    "  输入自然语言分析需求；助手会查询样本、规划任务，写操作需确认后提交。\n"
    "  斜杠命令：/help /new /clear /tasks /samples /search <kw> /model "
    "/analyze <样本> /curate [scope] /quit\n"
    "  Leader（Ctrl+G）：n 新会话 · l 任务 · s 样本 · m 模型 · t 主题 · h 帮助 · q 退出\n"
    "  其它：Enter 发送 · Shift/Alt+Enter 换行 · Esc 中断 · Ctrl+Y 确认计划 · "
    "Ctrl+F 跟随开关 · Ctrl+B 侧栏 · Ctrl+R 刷新 · Ctrl+L 清屏 · Ctrl+P 命令面板"
)


class BacmapTUI(App[None]):
    """bacmap 会话优先的工作台。"""

    CSS = _CSS
    TITLE = "bacmap"
    BINDINGS = [
        ("ctrl+c", "quit", "退出"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
        ("ctrl+r", "refresh", "刷新"),
        ("ctrl+l", "clear_conversation", "清屏"),
        ("ctrl+p", "command_palette", "命令面板"),
        ("ctrl+f", "toggle_follow", "跟随"),
        ("ctrl+y", "confirm_plan", "确认计划"),
        ("ctrl+g", "leader", "Leader"),
        ("escape", "interrupt", "中断/清空"),
    ]

    # leader 和弦（Ctrl+G 之后）：键 → 本类同步动作方法
    _LEADER_CHORDS = {
        "n": "action_new_session",
        "l": "action_focus_tasks",
        "s": "action_focus_samples",
        "m": "action_model_info",
        "t": "action_toggle_theme",
        "h": "action_help",
        "q": "_leader_quit",
    }

    def __init__(self, engine: Any) -> None:
        super().__init__()
        self.engine = engine
        self._session: Any = None
        self._pending_plan: Any = None
        self._chat_task: Any = None  # 在途会话 asyncio.Task（Esc 可取消）
        self._leader = False
        self._focus_before_leader: Any = None
        self._reply_seq = 0  # 递增令牌：Esc 后丢弃迟到的回复
        self._sidebar_wanted = True  # 用户的侧栏意图（宽终端时生效）
        self._follow = True  # 会话是否跟随最新（tui-design：follow 显式）

    # -- 布局 ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("任务", classes="side-title")
                yield DataTable(id="tasks-table")
                yield Static("样本", classes="side-title")
                yield DataTable(id="samples-table")
            with Vertical(id="main"):
                yield RichLog(id="conversation", markup=True, wrap=True)
                yield Static("", id="plan-hint")
                yield Input(
                    placeholder="输入分析需求；/ 查看斜杠命令；Enter 发送 · Ctrl+G 引导键",
                    id="prompt",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(_BACMAP_DARK)
        self.register_theme(_BACMAP_LIGHT)
        self.theme = "bacmap-dark"
        tasks = self.query_one("#tasks-table", DataTable)
        tasks.cursor_type = "row"
        tasks.add_columns("task", "state", "step")
        samples = self.query_one("#samples-table", DataTable)
        samples.cursor_type = "row"
        samples.add_columns("sample", "species", "ST")
        self.query_one("#conversation", RichLog).write(_HELP)
        self._apply_sidebar()
        self._show_endpoint()
        self.refresh_data()
        self.set_interval(4.0, self.refresh_tasks)

    async def _on_resize(self, event: Any) -> None:
        # App 在 _on_resize 中 stop 事件，公共 on_resize 不会触发；在此渲染钩子后重排侧栏。
        await super()._on_resize(event)
        self._apply_sidebar()

    def _apply_sidebar(self) -> None:
        visible = self._sidebar_wanted and self.size.width >= _SIDEBAR_MIN_WIDTH
        self.query_one("#sidebar").set_class(not visible, "hidden")

    # -- 状态/渲染 ----------------------------------------------------------

    @work(thread=True, exclusive=False)
    def _show_endpoint(self) -> None:
        from bacmap.interfaces.assistant import endpoint_status

        try:
            status = endpoint_status(self.engine)
        except Exception as exc:  # noqa: BLE001
            status = f"检查失败（{type(exc).__name__}）"
        self.call_from_thread(self._chat_append, f"[#8b949e]LLM 端点：{status}[/]")
        self.call_from_thread(setattr, self, "sub_title", f"LLM · {status}")

    @work(thread=True, exclusive=True)
    def refresh_data(self) -> None:
        from bacmap.interfaces.views import sample_rows

        tasks = self.engine.list_tasks(50)
        samples = sample_rows(self.engine)
        self.call_from_thread(self._render_tasks, tasks)
        self.call_from_thread(self._render_samples, samples)

    @work(thread=True, exclusive=False)
    def refresh_tasks(self) -> None:
        self.call_from_thread(self._render_tasks, self.engine.list_tasks(50))

    def _render_tasks(self, tasks: list[dict[str, Any]]) -> None:
        table = self.query_one("#tasks-table", DataTable)
        prev = self._selected_key(table)
        table.clear()
        for t in tasks:
            table.add_row(
                t["task_id"][:10], t["state"], t.get("current_step") or "", key=t["task_id"]
            )
        self._restore_selection(table, prev)

    def _render_samples(self, rows: list[dict[str, Any]]) -> None:
        table = self.query_one("#samples-table", DataTable)
        prev = self._selected_key(table)
        table.clear()
        for r in rows:
            table.add_row(r["sample_id"], r["verdict"], str(r["st"]), key=r["sample_id"])
        self._restore_selection(table, prev)

    @staticmethod
    def _selected_key(table: DataTable) -> str | None:
        try:
            if table.row_count == 0:
                return None
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        except Exception:  # noqa: BLE001 —— 空表/无光标
            return None

    @staticmethod
    def _restore_selection(table: DataTable, key: str | None) -> None:
        if key is None:
            return
        try:
            table.move_cursor(row=table.get_row_index(key))
        except Exception:  # noqa: BLE001 —— 行已不存在
            pass

    def _chat_append(self, markup: str) -> None:
        try:
            self.query_one("#conversation", RichLog).write(markup)
        except NoMatches:  # 关闭/卸载中，忽略
            return

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#plan-hint", Static).update(text)
        except NoMatches:
            return

    # -- 动作 ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_toggle_sidebar(self) -> None:
        self._sidebar_wanted = not self._sidebar_wanted
        self._apply_sidebar()

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        self.query_one("#conversation", RichLog).auto_scroll = self._follow
        self._set_hint(f"会话跟随：{'开' if self._follow else '关（滚动回看中）'}")

    def action_clear_conversation(self) -> None:
        self.query_one("#conversation", RichLog).clear()
        self._set_hint("")

    def action_interrupt(self) -> None:
        inp = self.query_one("#prompt", Input)
        inp.value = ""
        self._reply_seq += 1  # 丢弃迟到的回复
        if self._cancel_chat():
            self._chat_append("[#d29922]已取消在途请求[/]")
        if self._leader:
            self._end_leader()
            return
        if self._pending_plan is not None:
            self._pending_plan = None
            self._set_hint("")
            self._chat_append("[#8b949e]已忽略待确认计划[/]")

    def action_leader(self) -> None:
        self._focus_before_leader = self.focused
        # 光标在输入框时，字母键会被 Input 吞掉；Leader 期间把焦点让给 App。
        self.screen.set_focus(None)
        self._leader = True
        self._set_hint(
            "[b #d29922]Leader[/] 已激活：n 新会话 · l 任务 · s 样本 · "
            "m 模型 · t 主题 · h 帮助 · q 退出"
        )

    def _end_leader(self) -> None:
        self._leader = False
        self._set_hint("")
        prior = getattr(self, "_focus_before_leader", None)
        if prior is not None:
            self.screen.set_focus(prior)

    def action_focus_tasks(self) -> None:
        self.query_one("#tasks-table", DataTable).focus()

    def action_focus_samples(self) -> None:
        self.query_one("#samples-table", DataTable).focus()

    def action_model_info(self) -> None:
        self._show_endpoint()

    def action_toggle_theme(self) -> None:
        self.theme = "bacmap-light" if self.theme == "bacmap-dark" else "bacmap-dark"

    def action_help(self) -> None:
        self._chat_append(_HELP)

    def action_new_session(self) -> None:
        self._session = None
        self._pending_plan = None
        self._reply_seq += 1  # 丢弃旧会话迟到的回复
        self._cancel_chat()
        self.action_clear_conversation()
        self._chat_append("[#8b949e]已开始新会话[/]")

    def action_confirm_plan(self) -> None:
        plan = self._pending_plan
        if plan is None:
            self._chat_append("[#8b949e]当前没有待确认的计划[/]")
            return
        # 立即清除待确认计划：防连按 Ctrl+Y 重复提交同一个计划。
        self._pending_plan = None
        self._set_hint("")
        self._do_confirm_plan(plan)

    # -- leader 和弦拦截 ----------------------------------------------------

    def on_key(self, event: Any) -> None:
        if not self._leader:
            return
        handler = getattr(self, self._LEADER_CHORDS.get(event.key, ""), None)
        self._end_leader()
        # 消费该键：leader 模式下任何键都不落回输入框（否则残键会写入 prompt）。
        event.prevent_default()
        event.stop()
        if handler is not None:
            handler()

    def _leader_quit(self) -> None:
        self.exit()

    # -- 输入/命令 ----------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if len(text) > _MAX_PROMPT_LEN:
            self._chat_append(
                f"[#f85149]需求过长（上限 {_MAX_PROMPT_LEN} 字符）[/]"
            )
            return
        if text.startswith("/"):
            self._run_slash(text)
            return
        self._start_chat(text)

    def _run_slash(self, text: str) -> None:
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd in ("help", "?"):
            self.action_help()
        elif cmd in ("quit", "q"):
            self.exit()
        elif cmd in ("new",):
            self.action_new_session()
        elif cmd in ("clear", "cls"):
            self.action_clear_conversation()
        elif cmd in ("tasks",):
            self.action_focus_tasks()
        elif cmd in ("samples",):
            self.action_focus_samples()
        elif cmd in ("model", "endpoint"):
            self.action_model_info()
        elif cmd == "search":
            self._slash_search(arg)
        elif cmd in ("analyze", "curate"):
            self._slash_submit(cmd, arg)
        else:
            self._chat_append(f"[#f85149]未知命令：/{cmd}（输入 /help）[/]")

    @work(thread=True, exclusive=False)
    def _slash_search(self, query: str) -> None:
        from bacmap.interfaces.views import sample_rows, search_rows

        hits = search_rows(sample_rows(self.engine), query=query)
        text = "、".join(r["sample_id"] for r in hits) or "无命中"
        self.call_from_thread(self._chat_append, f"[#8b949e]检索 {_esc(query)!r}：{_esc(text)}[/]")

    @work(thread=True, exclusive=False)
    def _slash_submit(self, task_type: str, arg: str) -> None:
        import json

        from bacmap.tasks.spec import TaskType

        params: dict[str, Any] = {}
        if task_type == "analyze":
            samples = [s.strip() for s in arg.replace(",", " ").split() if s.strip()]
            if not samples:
                self.call_from_thread(self._chat_append, "[#f85149]用法：/analyze <样本ID>[/]")
                return
            params["samples"] = samples
        elif arg:
            try:
                params["scope"] = json.loads(arg)
            except ValueError:
                self.call_from_thread(self._chat_append, "[#f85149]scope 不是合法 JSON[/]")
                return
        try:
            tid = self.engine.submit(TaskType(task_type), params, "tui")
            msg = f"[green]已提交 {_esc(task_type)}：{_esc(tid)}[/green]"
        except (ValueError, NotImplementedError) as exc:
            msg = f"[#f85149]提交失败：{_esc(str(exc))}[/]"
        self.call_from_thread(self._chat_append, msg)
        self.call_from_thread(self.refresh_tasks)

    # -- 会话（LLM 规划） ---------------------------------------------------

    def _start_chat(self, text: str) -> None:
        """启动一轮会话（async worker）；新一轮以 exclusive 取消上一轮在途请求。"""
        self._chat_task = self.run_worker(
            self._chat_async(text), group="chat", exclusive=True, exit_on_error=False
        )

    def _cancel_chat(self) -> bool:
        worker = self._chat_task
        if worker is not None and not worker.is_finished:
            worker.cancel()
            return True
        return False

    async def _chat_async(self, text: str) -> None:
        self._reply_seq += 1
        token = self._reply_seq
        self._chat_append(f"[#79c0ff]你[/] › {_esc(text)}")
        self._set_hint("…思考中（首次调用较慢，Esc 可取消）")
        try:
            if self._session is None:
                from bacmap.interfaces.assistant import build_session

                self._session = build_session(self.engine)
            reply = await self._session.respond_async(text)
        except asyncio.CancelledError:
            self._set_hint("[#d29922]已在途请求已取消[/]")
            raise
        except Exception as exc:  # noqa: BLE001
            self._chat_append(
                f"[#f85149]助手调用失败：{_esc(type(exc).__name__)}: {_esc(str(exc))}[/]"
            )
            self._set_hint("")
            return
        if token != self._reply_seq:  # 已被 Esc 放弃
            return
        self._chat_reply(reply)

    def _chat_reply(self, reply: Any) -> None:
        # 助手文本被视为不可信显示数据：转义 Rich 标记，避免注入改版式/控制序列。
        self._chat_append(f"[#3fb950]bacmap[/] › {_esc(reply.message)}")
        plan = reply.plan
        if plan is not None and plan.tasks:
            from bacmap.interfaces.assistant import format_plan

            self._chat_append("建议计划：\n" + _esc(format_plan(plan)))
            if not plan.needs_clarification:
                self._pending_plan = plan
                self._set_hint("计划待确认：Ctrl+Y 提交 · Esc 忽略")
                return
        self._set_hint("")

    @work(thread=True, exclusive=False)
    def _do_confirm_plan(self, plan: Any) -> None:
        from bacmap.interfaces.assistant import execute_plan

        try:
            results = execute_plan(self.engine, plan, submitted_by="tui")
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(
                self._chat_append,
                f"[#f85149]提交失败：{_esc(type(exc).__name__)}: {_esc(str(exc))}[/]",
            )
            return
        self._pending_plan = None
        self.call_from_thread(self._set_hint, "")
        for r in results:
            mark = "✓" if r["ok"] else "✗"
            self.call_from_thread(
                self._chat_append,
                f"{mark} {_esc(str(r['task_type']))}: "
                f"{_esc(str(r.get('task_id') or r.get('error')))}",
            )
        self.call_from_thread(self.refresh_tasks)
