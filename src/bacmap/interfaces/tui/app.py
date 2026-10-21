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
import contextlib
import time
from typing import Any, ClassVar

from rich.markup import escape as _esc
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
)

# 侧栏自动折叠阈值（tui-design：窄终端折叠次要面板，恢复时保留选择）
_SIDEBAR_MIN_WIDTH = 96
# 单轮需求文本上限（与 Web 一致，防超大提示词）
_MAX_PROMPT_LEN = 8000
# 流式组件刷新节流（思考/回复增量高频到达，重渲染按帧合并）
_STREAM_FLUSH_S = 0.06
# 思考直播窗口上限（防超长 reasoning 刷爆渲染；完成后全文可经 Ctrl+T 展开）
_THINK_LIVE_LIMIT = 4000

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
#conversation .msg { width: 1fr; margin: 0 0 1 0; }
#plan-hint { padding: 0 2; color: $warning; height: auto; }
#prompt { dock: bottom; border: round $border; }
#prompt:focus { border: round $accent; }
"""

# 思考/活动指示的 spinner 帧（opencode 式 braille throbber）
_SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _default_signature() -> str:
    """签批默认签名：单工作站形态取系统用户名（挖掘门 signed_by 证据）。"""
    import getpass

    with contextlib.suppress(OSError):
        return getpass.getuser()
    return "tui-operator"

_HELP = (
    "[b #3fb950]bacmap 会话助手[/]\n"
    "  输入自然语言分析需求；助手会查询样本、规划任务，写操作需确认后提交。\n"
    "  斜杠命令：/help /new /clear /tasks /samples /search <kw> /result <样本> /model "
    "/approve <ID> [签名] /analyze <样本> /curate [scope] /quit\n"
    "  Leader（Ctrl+G）：n 新会话 · i 输入框 · l 任务 · s 样本 · "
    "m 模型 · t 主题 · a 签批选中任务 · h 帮助 · q 退出\n"
    "  其它：Enter 发送 · Shift/Alt+Enter 换行 · Esc 中断 · Ctrl+Y 确认计划 · "
    "Ctrl+F 跟随开关 · Ctrl+T 展开/收起最近思考 · Ctrl+B 侧栏 · Ctrl+R 刷新 · "
    "Ctrl+L 清屏 · Ctrl+P 命令面板"
)


class BacmapTUI(App[None]):
    """bacmap 会话优先的工作台。"""

    CSS = _CSS
    TITLE = "bacmap"
    BINDINGS: ClassVar[list[Any]] = [
        ("ctrl+c", "quit", "退出"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
        ("ctrl+r", "refresh", "刷新"),
        ("ctrl+l", "clear_conversation", "清屏"),
        ("ctrl+p", "command_palette", "命令面板"),
        ("ctrl+f", "toggle_follow", "跟随"),
        ("ctrl+t", "toggle_thinking", "思考展开"),
        ("ctrl+y", "confirm_plan", "确认计划"),
        ("ctrl+g", "leader", "Leader"),
        ("escape", "interrupt", "中断/清空"),
    ]

    # leader 和弦（Ctrl+G 之后）：键 → 本类同步动作方法
    _LEADER_CHORDS: ClassVar[dict[str, str]] = {
        "n": "action_new_session",
        "i": "action_focus_input",
        "l": "action_focus_tasks",
        "s": "action_focus_samples",
        "m": "action_model_info",
        "t": "action_toggle_theme",
        "h": "action_help",
        "a": "action_approve_task",
        "q": "_leader_quit",
    }

    def __init__(self, engine: Any) -> None:
        super().__init__()
        self.engine = engine
        self._session: Any = None
        self._pending_plan: Any = None
        self._pending_approval: dict[str, str] | None = None  # 待签批任务（Leader a）
        self._chat_task: Any = None  # 在途会话 asyncio.Task（Esc 可取消）
        self._leader = False
        self._focus_before_leader: Any = None
        self._reply_seq = 0  # 递增令牌：Esc 后丢弃迟到的回复
        self._sidebar_wanted = True  # 用户的侧栏意图（宽终端时生效）
        self._follow = True  # 会话是否跟随最新（tui-design：follow 显式）
        self._task_states: dict[str, str] = {}  # 上次渲染看到的任务状态（失败回显去重）
        self._tasks_seeded = False  # 首次渲染只登记、不回显历史失败
        # 流式展示状态（v1.4.32）：spinner/活动文案在提示行；思考与回复作为
        # 会话主区的消息组件**内联流式**（OpenCode 式），完成即折叠/定稿。
        self._spin_i = 0
        self._spin_timer: Any = None
        self._activity = ""
        self._think_w: Static | None = None  # 本轮思考块（内联）
        self._think_buf = ""
        self._reply_w: Static | None = None  # 本轮流式回复块
        self._reply_buf = ""
        self._last_think: tuple[Static, str] | None = None  # 最近完成的思考（Ctrl+T）
        self._think_expanded = False
        self._last_flush = 0.0
        self._cursor_on = True

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
                yield VerticalScroll(id="conversation")
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
        self._chat_append(_HELP)
        self._apply_sidebar()
        self._show_endpoint()
        self.refresh_data()
        self.set_interval(4.0, self.refresh_tasks)
        # 开屏即聚焦输入框：用户可直接输入（否则焦点落在任务表，输入被吞）。
        self.query_one("#prompt", Input).focus()

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
        except Exception as exc:
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
        self._announce_task_failures(tasks)

    def _announce_task_failures(self, tasks: list[dict[str, Any]]) -> None:
        """任务进入 failed/cancelled 时回显到会话区（每个任务只报一次）。

        按 Ctrl+Y 提交后助手回合即结束；任务在后台失败若只变更侧栏表格，用户不会知道。
        首次渲染只登记既有状态，避免启动时把历史失败刷进会话。
        """
        if not self._tasks_seeded:
            self._task_states.update({str(t["task_id"]): str(t["state"]) for t in tasks})
            self._tasks_seeded = True
            return
        for t in tasks:
            tid = str(t["task_id"])
            state = str(t["state"])
            prev = self._task_states.get(tid)
            if state in ("failed", "cancelled") and prev != state:
                msg = (t.get("message") or "").strip()
                detail = f"：{msg[:300]}" if msg else ""
                step = t.get("current_step") or "-"
                self._chat_append(f"[#f85149]任务 {tid[:10]} {state}（{step}）{detail}[/]")
            self._task_states[tid] = state

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
        except Exception:
            return None

    @staticmethod
    def _restore_selection(table: DataTable, key: str | None) -> None:
        if key is None:
            return
        # 行已消失（刷新竞态）：保持无选中即可，不视为错误。
        with contextlib.suppress(Exception):
            table.move_cursor(row=table.get_row_index(key))

    def _chat_append(self, markup: str) -> None:
        """追加一条会话消息（组件化消息流；不可信文本由调用方 ``_esc`` 转义）。"""
        try:
            conv = self.query_one("#conversation", VerticalScroll)
        except NoMatches:  # 关闭/卸载中，忽略
            return
        conv.mount(Static(markup, markup=True, classes="msg"))
        if self._follow:
            conv.scroll_end(animate=False)

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#plan-hint", Static).update(text)
        except NoMatches:
            return

    # -- 流式展示（v1.4.32：思考/回复内联主区，提示行只留 spinner/活动）----------

    def _start_busy(self, activity: str) -> None:
        """开始"思考中"动态指示：spinner 定时器 + 提示行活动文案。"""
        self._activity = activity
        self._think_w = None
        self._think_buf = ""
        self._reply_w = None
        self._reply_buf = ""
        self._last_flush = 0.0
        self._spin_i = 0
        if self._spin_timer is None:
            self._spin_timer = self.set_interval(0.12, self._tick_busy)

    def _stop_busy(self) -> None:
        """结束动态指示：停 spinner、清活动文案（思考/回复组件由定稿逻辑处理）。"""
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None
        self._activity = ""
        if not self._pending_plan:
            self._set_hint("")

    def _tick_busy(self) -> None:
        self._spin_i = (self._spin_i + 1) % len(_SPIN_FRAMES)
        self._cursor_on = not self._cursor_on
        self._render_busy()
        self._flush_stream()  # 光标闪烁节奏顺带刷新流式组件

    def _render_busy(self) -> None:
        """渲染提示行（spinner + 活动文案）；思考/回复在会话主区，不在此处。"""
        frame = _SPIN_FRAMES[self._spin_i]
        if self._activity:
            self._set_hint(f"[b #d29922]{frame}[/] {_esc(self._activity)}")
        else:
            self._set_hint(f"[#8b949e]{frame}[/]")

    def _ensure_stream_w(self, which: str) -> Static | None:
        """惰性创建本轮的思考/回复消息组件（首个增量到达时挂载进主区）。"""
        w = self._think_w if which == "think" else self._reply_w
        if w is not None:
            return w
        try:
            conv = self.query_one("#conversation", VerticalScroll)
        except NoMatches:
            return None
        w = Static("", markup=True, classes="msg " + ("thinking" if which == "think" else ""))
        conv.mount(w)
        if which == "think":
            self._think_w = w
        else:
            self._reply_w = w
        return w

    def _flush_stream(self, force: bool = False) -> None:
        """把累计的思考/回复增量刷进内联组件（节流合并高频 delta）。"""
        now = time.monotonic()
        if not force and (now - self._last_flush) < _STREAM_FLUSH_S:
            return
        self._last_flush = now
        if self._think_w is not None and self._think_buf:
            shown = self._think_buf[-_THINK_LIVE_LIMIT:]
            head = "…" if len(self._think_buf) > _THINK_LIVE_LIMIT else ""
            self._think_w.update(f"[i #8b949e]✻ {_esc(head + shown)}[/]")
        if self._reply_w is not None and self._reply_buf:
            cursor = "▌" if self._cursor_on else " "
            self._reply_w.update(f"[green]{_esc(self._reply_buf)}{cursor}[/green]")
        self._autoscroll()

    def _autoscroll(self) -> None:
        if not self._follow:
            return
        try:
            self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)
        except NoMatches:
            return

    def _finalize_thinking(self, note: str = "") -> None:
        """本轮思考定稿：**保留全文可见**（用户裁定：完成后不自动消失），Ctrl+T 可折叠。"""
        w, buf = self._think_w, self._think_buf
        self._think_w, self._think_buf = None, ""
        if w is None or not buf:
            return
        self._last_think = (w, buf)
        self._think_expanded = True
        extra = f"（{note}）" if note else ""
        w.update(f"[i #8b949e]✻ 思考{extra}：{_esc(buf)}[/]")

    def action_toggle_thinking(self) -> None:
        """折叠/展开最近一次完成的思考块（默认保留全文，按需收起）。"""
        if self._last_think is None:
            self._set_hint("没有可展开的思考块")
            return
        w, buf = self._last_think
        self._think_expanded = not self._think_expanded
        if self._think_expanded:
            w.update(f"[i #8b949e]✻ 思考：{_esc(buf)}[/]")
        else:
            w.update(f"[#8b949e]✻ 思考 {len(buf)} 字符 · Ctrl+T 展开[/]")
        self._autoscroll()

    # -- 动作 ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_toggle_sidebar(self) -> None:
        self._sidebar_wanted = not self._sidebar_wanted
        self._apply_sidebar()

    def action_toggle_follow(self) -> None:
        self._follow = not self._follow
        self._set_hint(f"会话跟随：{'开' if self._follow else '关（滚动回看中）'}")

    def action_clear_conversation(self) -> None:
        self.query_one("#conversation", VerticalScroll).remove_children()
        self._last_think = None
        self._think_expanded = False
        self._set_hint("")

    def action_interrupt(self) -> None:
        inp = self.query_one("#prompt", Input)
        inp.value = ""
        self._reply_seq += 1  # 丢弃迟到的回复
        self._stop_busy()
        if self._cancel_chat():
            self._chat_append("[#d29922]已取消在途请求[/]")
        if self._leader:
            self._end_leader()
            return
        self._pending_approval = None
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
            "i 输入 · m 模型 · t 主题 · a 签批 · h 帮助 · q 退出"
        )

    def _end_leader(self) -> None:
        self._leader = False
        self._set_hint("")
        prior = getattr(self, "_focus_before_leader", None)
        if prior is not None:
            self.screen.set_focus(prior)

    def action_focus_tasks(self) -> None:
        self.query_one("#tasks-table", DataTable).focus()

    def action_focus_input(self) -> None:
        """回到输入框（表格聚焦后无法直接输入；Leader i 或 Tab 回来）。"""
        self.query_one("#prompt", Input).focus()

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
        self._pending_approval = None
        self._reply_seq += 1  # 丢弃旧会话迟到的回复
        self._cancel_chat()
        self.action_clear_conversation()
        self._chat_append("[#8b949e]已开始新会话[/]")

    def action_confirm_plan(self) -> None:
        if self._pending_plan is None and self._pending_approval is not None:
            # 待签批与待确认计划共用 Ctrl+Y（先到先得；立即清除防连按重复执行）。
            approval, self._pending_approval = self._pending_approval, None
            self._set_hint("")
            self._do_approve(approval)
            return
        plan = self._pending_plan
        if plan is None:
            self._chat_append("[#8b949e]当前没有待确认的计划[/]")
            return
        # 立即清除待确认计划：防连按 Ctrl+Y 重复提交同一个计划。
        self._pending_plan = None
        self._set_hint("")
        self._do_confirm_plan(plan)

    # -- 任务签批（awaiting_approval）-----------------------------------------

    def action_approve_task(self) -> None:
        """签批任务表中选中的任务（Leader a）：Ctrl+Y 确认，Esc 取消。"""
        table = self.query_one("#tasks-table", DataTable)
        key = self._selected_key(table)
        if key is None:
            self._set_hint("先选中任务：Leader l 聚焦任务表，↑↓ 选择，再 Leader a")
            return
        state = self._task_states.get(key, "")
        if state != "awaiting_approval":
            self._set_hint(
                f"任务 {key[:12]} 状态为 {state or '未知'}：仅 awaiting_approval 可签批"
            )
            return
        sig = _default_signature()
        self._pending_approval = {"task_id": key, "signature": sig}
        self._set_hint(f"签批 {key[:12]} · 签名 {sig}：Ctrl+Y 确认 · Esc 取消")

    @work(thread=True, exclusive=False)
    def _do_approve(self, approval: dict[str, str]) -> None:
        from datetime import UTC, datetime

        from bacmap.tasks.spec import Approval

        raw, sig = approval["task_id"], approval["signature"]
        try:
            tid = self.engine.resolve_task_id(raw)
            self.engine.approve(
                tid,
                Approval(
                    approver=sig,
                    decision="approve",
                    signature=sig,
                    comment="TUI 签批",
                    at=datetime.now(UTC),
                ),
            )
            msg = f"[green]已签批 ✓ {str(tid)[:12]}（{sig}）[/green]"
        except Exception as exc:
            msg = (
                f"[#f85149]签批失败 {raw[:12]}：{_esc(type(exc).__name__)}: {_esc(str(exc))}[/]"
            )
        self.call_from_thread(self._chat_append, msg)
        self.call_from_thread(self.refresh_tasks)

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
        elif cmd == "result":
            self._slash_result(arg)
        elif cmd == "approve":
            self._slash_approve(arg)
        elif cmd in ("analyze", "curate"):
            self._slash_submit(cmd, arg)
        else:
            self._chat_append(f"[#f85149]未知命令：/{cmd}（输入 /help）[/]")

    def _slash_result(self, arg: str) -> None:
        """``/result [样本ID]``——渲染已完成样本的关键结果；无参时取样本表选中项。"""
        sample = arg.strip()
        if not sample:
            table = self.query_one("#samples-table", DataTable)
            sample = self._selected_key(table) or ""
        if not sample:
            self._set_hint("用法：/result <样本ID>（或在样本表选中一行后直接 /result）")
            return
        self._result_worker(sample)

    @work(thread=True, exclusive=False)
    def _result_worker(self, sample: str) -> None:
        import json
        from pathlib import Path

        from bacmap.interfaces.views import report_path, sample_digest

        sj = Path(self.engine.home) / "results" / sample / "report" / f"{sample}_summary.json"
        if not sj.is_file():
            self.call_from_thread(
                self._chat_append, f"[#f85149]样本 {sample} 无结果（未完成或不存在）[/]"
            )
            return
        try:
            summary = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.call_from_thread(
                self._chat_append, f"[#f85149]读取失败 {sample}：{_esc(str(exc))}[/]"
            )
            return
        d = sample_digest(summary)
        vpa = summary.get("steps", {}).get("vpa_virulence", {}) or {}
        marks = (
            "  |  VPA 标记: "
            + "".join(k + ("⁺" if vpa.get(k) else "⁻") for k in ("tlh", "tdh", "trh"))
            if vpa
            else ""
        )
        amr = "、".join(sorted(d["card_genes"])[:8]) or "无"
        sero = f"   血清型: {_esc(str(d['serovar']))}" if d.get("serovar") else ""
        lines = [
            f"[b #79c0ff]结果 · {d['sample_id']}[/]",
            f"  物种: {_esc(str(d['verdict']))}   MLST: {_esc(str(d['st']))}{sero}",
            f"  耐药(CARD {d['n_card']}): {amr}",
            f"  毒力: vfdb {d['n_vfdb']}  |  质粒: {d['n_plasmid']}{marks}",
            f"  报告: [underline]{_esc(str(report_path(self.engine, sample)))}[/underline]",
        ]
        self.call_from_thread(self._chat_append, "\n".join(lines))

    def _slash_approve(self, arg: str) -> None:
        """``/approve [任务ID短前缀] [签名]``——无参时签批任务表选中项。"""
        parts = arg.split()
        if not parts:
            self.action_approve_task()
            return
        raw = parts[0]
        sig = parts[1] if len(parts) > 1 else _default_signature()
        self._pending_approval = {"task_id": raw, "signature": sig}
        self._set_hint(f"签批 {raw[:12]} · 签名 {sig}：Ctrl+Y 确认 · Esc 取消")

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
        self._start_busy("思考中（Esc 可取消）")

        async def on_event(kind: str, payload: str) -> None:
            if token != self._reply_seq:
                return  # 已被 Esc 放弃：不再渲染
            if kind == "thinking_delta":
                self._think_buf += payload
                self._ensure_stream_w("think")
                self._flush_stream()
            elif kind in ("text_delta", "reply_delta"):
                self._reply_buf += payload
                self._ensure_stream_w("reply")
                self._flush_stream()
            elif kind == "tool_call":
                self._activity = f"调用 {payload or '工具'}…"
            elif kind == "tool_result":
                self._activity = f"{payload or '工具'} ✓"
            elif kind == "retry":
                self._activity = "请求失败，重试中…"
            self._render_busy()

        try:
            if self._session is None:
                from bacmap.interfaces.assistant import build_session

                self._session = build_session(self.engine)
            reply = await self._session.respond_stream(text, on_event)
        except asyncio.CancelledError:
            self._stop_busy()
            self._finalize_thinking("已中断")
            self._set_hint("[#d29922]已在途请求已取消[/]")
            raise
        except Exception as exc:
            self._stop_busy()
            self._finalize_thinking("失败")
            self._chat_append(
                f"[#f85149]助手调用失败：{_esc(type(exc).__name__)}: {_esc(str(exc))}[/]"
            )
            self._set_hint("")
            return
        if token != self._reply_seq:  # 已被 Esc 放弃
            return
        self._stop_busy()
        self._chat_reply(reply)

    def _chat_reply(self, reply: Any) -> None:
        # 助手文本被视为不可信显示数据：转义 Rich 标记，避免注入改版式/控制序列。
        # 已有流式回复组件则原位定稿（权威文本以 reply.message 为准），否则补一条。
        text = f"[#3fb950]bacmap[/] › {_esc(reply.message)}"
        if self._reply_w is not None:
            self._reply_w.update(text)
        else:
            self._chat_append(text)
        self._finalize_thinking()
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
            # confirmed=True：唯一入口是用户按 Ctrl+Y（_pending_plan 待确认提示）。
            results = execute_plan(self.engine, plan, submitted_by="tui", confirmed=True)
        except Exception as exc:
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
