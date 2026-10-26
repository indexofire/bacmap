"""bacmap 全屏 TUI（Textual）——只读任务台 + 运维命令台。

v1.6（ADR-21）：对话交互已外置到外部 Harness（Hermes / Pi / DSH，经 MCP），
内置会话助手移除；本界面因此不再是"会话优先工作台"，而是一个**只读任务台**：

- 侧栏：任务表（状态/步骤）与样本表（物种/ST），``Ctrl+B`` 折叠，窄终端自动折叠；
- 主区：操作日志（任务失败回显、检索结果、样本结果摘要、帮助）；
- 底部：命令输入框，只接受斜杠命令（``/help`` 列出全部）；
- 写操作仍只有两种：提交任务（``/analyze``、``/curate``）与任务签批（``Ctrl+Y`` 确认），
  与 Web/CLI/MCP 走同一任务引擎与门。

对话、规划与计划确认请使用外部 Harness + ``bacmap plan``/Web ``/plans``。
"""

from __future__ import annotations

import contextlib
from typing import Any, ClassVar

from rich.markup import escape as _esc
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import DataTable, Footer, Header, Input, Static

# 侧栏自动折叠阈值（窄终端折叠次要面板，恢复时保留选择）
_SIDEBAR_MIN_WIDTH = 96
# 单条命令长度上限（防粘贴巨量文本卡住界面）
_MAX_INPUT_LEN = 4000

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


class _CommandInput(Input):
    """命令输入框：leader 模式下的按键交给 App 处理（否则 Input 会吞掉可打印字符）。"""

    async def _on_key(self, event: events.Key) -> None:
        if getattr(self.app, "_leader", False):
            handle = getattr(self.app, "handle_leader_key", None)
            if handle is not None:
                handle(event)
            return
        await super()._on_key(event)


def _default_signature() -> str:
    """签批默认签名：单工作站形态取系统用户名（挖掘门 signed_by 证据）。"""
    import getpass

    with contextlib.suppress(OSError):
        return getpass.getuser()
    return "tui-operator"


_HELP = (
    "[b #3fb950]bacmap 任务台[/]\n"
    "  本界面只做任务/样本查看与签批；对话与计划请用外部 Harness（Hermes / Pi / DSH）经 MCP，"
    "计划在 `bacmap plan` 或 Web /plans 确认。\n"
    "  斜杠命令：/help /clear /tasks /samples /search <kw> /result <样本> /model "
    "/approve <ID> [签名] /analyze <样本> /curate [scope] /quit\n"
    "  Leader（Ctrl+G）：i 输入框 · l 任务 · s 样本 · m 端点 · t 主题 · a 签批选中任务 · "
    "h 帮助 · q 退出\n"
    "  其它：Enter 执行命令 · Ctrl+Y 确认签批 · Ctrl+B 侧栏 · Ctrl+R 刷新 · Ctrl+L 清屏"
)


class BacmapTUI(App[None]):
    """bacmap 只读任务台 + 运维命令台（无内置对话）。"""

    CSS = _CSS
    TITLE = "bacmap"
    BINDINGS: ClassVar[list[Any]] = [
        ("ctrl+c", "quit", "退出"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
        ("ctrl+r", "refresh", "刷新"),
        ("ctrl+l", "clear_log", "清屏"),
        ("ctrl+y", "confirm_approval", "确认签批"),
        ("ctrl+g", "leader", "Leader"),
        ("escape", "interrupt", "取消"),
    ]

    # leader 和弦（Ctrl+G 之后）：键 → 本类同步动作方法
    _LEADER_CHORDS: ClassVar[dict[str, str]] = {
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
        self._pending_approval: dict[str, str] | None = None  # 待签批任务（Leader a）
        self._leader = False
        self._focus_before_leader: Any = None
        self._sidebar_wanted = True  # 用户的侧栏意图（宽终端时生效）
        self._task_states: dict[str, str] = {}  # 上次渲染看到的任务状态（失败回显去重）
        self._tasks_seeded = False  # 首次渲染只登记、不回显历史失败

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
                yield _CommandInput(placeholder="输入命令；/help 查看全部；Enter 执行", id="prompt")
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
        self._logline(_HELP)
        self._apply_sidebar()
        self._show_endpoint()
        self.refresh_data()
        self.set_interval(4.0, self.refresh_tasks)
        # 开屏即聚焦输入框：用户可直接输入命令（否则焦点落在任务表，输入被吞）。
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
        from bacmap.interfaces.views import endpoint_status

        try:
            status = endpoint_status(self.engine)
        except Exception as exc:
            status = f"检查失败（{type(exc).__name__}）"
        self.call_from_thread(self._logline, f"[#8b949e]LLM 端点：{status}[/]")
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
        """任务进入 failed/cancelled 时回显到日志区（每个任务只报一次）。

        任务在后台失败若只变更侧栏表格，用户不会知道；首次渲染只登记既有状态，
        避免启动时把历史失败刷进日志。
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
                self._logline(f"[#f85149]任务 {tid[:10]} {state}（{step}）{detail}[/]")
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

    def _logline(self, markup: str) -> None:
        """追加一条日志消息（组件化消息流；不可信文本由调用方 ``_esc`` 转义）。"""
        try:
            conv = self.query_one("#conversation", VerticalScroll)
        except NoMatches:  # 关闭/卸载中，忽略
            return
        conv.mount(Static(markup, markup=True, classes="msg"))
        conv.scroll_end(animate=False)

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#plan-hint", Static).update(text)
        except NoMatches:
            return

    # -- 动作 ---------------------------------------------------------------

    def action_refresh(self) -> None:
        self.refresh_data()
        self._show_endpoint()

    def action_toggle_sidebar(self) -> None:
        self._sidebar_wanted = not self._sidebar_wanted
        self._apply_sidebar()

    def action_clear_log(self) -> None:
        self.query_one("#conversation", VerticalScroll).remove_children()
        self._logline(_HELP)

    def action_interrupt(self) -> None:
        if self._pending_approval is not None:
            self._pending_approval = None
            self._set_hint("已取消待签批")
            return
        if self._leader:
            self._end_leader()
            return
        self.query_one("#prompt", Input).focus()

    def action_leader(self) -> None:
        if self._leader:
            self._end_leader()
            return
        try:
            self._focus_before_leader = self.focused
        except Exception:
            self._focus_before_leader = None
        self._leader = True
        self._set_hint(
            "Leader 已激活：i 输入 · l 任务 · s 样本 · m 端点 · t 主题 · a 签批 · h 帮助 · q 退出"
        )

    def _end_leader(self) -> None:
        self._leader = False
        self._set_hint("")
        restore = self._focus_before_leader
        self._focus_before_leader = None
        if restore is not None:
            with contextlib.suppress(Exception):
                restore.focus()

    def action_focus_tasks(self) -> None:
        self.query_one("#tasks-table", DataTable).focus()

    def action_focus_input(self) -> None:
        self.query_one("#prompt", Input).focus()

    def action_focus_samples(self) -> None:
        self.query_one("#samples-table", DataTable).focus()

    def action_model_info(self) -> None:
        self._show_endpoint()

    def action_toggle_theme(self) -> None:
        self.theme = "bacmap-light" if self.theme == "bacmap-dark" else "bacmap-dark"

    def action_help(self) -> None:
        self._logline(_HELP)

    def action_confirm_approval(self) -> None:
        pending = self._pending_approval
        if pending is None:
            self._set_hint("无待确认签批（Leader a 或 /approve 选择任务）")
            return
        self._pending_approval = None
        self._approve(pending)

    def action_approve_task(self) -> None:
        """签批任务表选中项：Leader a 进入待签批，Ctrl+Y 确认（两步防误签）。"""
        table = self.query_one("#tasks-table", DataTable)
        tid = self._selected_key(table)
        if not tid:
            self._set_hint("请先在任务表选中一行")
            return
        self._pending_approval = {"task_id": tid, "signature": _default_signature()}
        self._pending_approval["decision"] = "approve"
        self._set_hint(
            f"签批 {tid[:10]} · 签名 {self._pending_approval['signature']}：Ctrl+Y 确认 · Esc 取消"
        )

    @work(thread=True, exclusive=False)
    def _approve(self, pending: dict[str, str]) -> None:
        from datetime import UTC, datetime

        from bacmap.tasks.spec import Approval, TaskId

        try:
            approval = Approval(
                approver=pending["signature"],
                decision="approve",
                signature=pending["signature"],
                at=datetime.now(UTC),
            )
            self.engine.approve(TaskId(pending["task_id"]), approval)
            msg = f"[green]已签批 {_esc(pending['task_id'][:10])}[/green]"
        except (KeyError, ValueError) as exc:
            msg = f"[#f85149]签批失败：{_esc(str(exc))}[/]"
        self.call_from_thread(self._logline, msg)
        self.call_from_thread(self.refresh_tasks)

    def handle_leader_key(self, event: Any) -> None:
        """Leader 和弦的唯一入口（App.on_key 与 _CommandInput 都转发到这里）。"""
        if not self._leader:
            return
        key = str(getattr(event, "key", "")).lower()
        action = self._LEADER_CHORDS.get(key)
        self._end_leader()
        # 消费该键：leader 模式下任何键都不落回输入框（否则残键会写入 prompt）。
        event.prevent_default()
        event.stop()
        if action is None:
            return
        if action == "_leader_quit":
            self.exit()
            return
        getattr(self, action)()

    def on_key(self, event: Any) -> None:
        self.handle_leader_key(event)

    def _leader_quit(self) -> None:  # pragma: no cover - 由 handle_leader_key 分派
        self.exit()

    # -- 命令台 -------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if len(text) > _MAX_INPUT_LEN:
            self._logline(f"[#f85149]命令过长（上限 {_MAX_INPUT_LEN} 字符）[/]")
            return
        if not text.startswith("/"):
            self._set_hint("本界面只接受斜杠命令（/help）；对话请用外部 Harness（ADR-21）")
            return
        self._run_slash(text)

    def _run_slash(self, text: str) -> None:
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd in ("help", "?"):
            self.action_help()
        elif cmd in ("quit", "q"):
            self.exit()
        elif cmd in ("clear", "cls"):
            self.action_clear_log()
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
            self._logline(f"[#f85149]未知命令：/{_esc(cmd)}（输入 /help）[/]")

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
                self._logline, f"[#f85149]样本 {_esc(sample)} 无结果（未完成或不存在）[/]"
            )
            return
        try:
            summary = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.call_from_thread(
                self._logline, f"[#f85149]读取失败 {_esc(sample)}：{_esc(str(exc))}[/]"
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
            f"[b #79c0ff]结果 · {_esc(str(d['sample_id']))}[/]",
            f"  物种: {_esc(str(d['verdict']))}   MLST: {_esc(str(d['st']))}{sero}",
            f"  耐药(CARD {d['n_card']}): {_esc(amr)}",
            f"  毒力: vfdb {d['n_vfdb']}  |  质粒: {d['n_plasmid']}{marks}",
            f"  报告: [underline]{_esc(str(report_path(self.engine, sample)))}[/underline]",
        ]
        self.call_from_thread(self._logline, "\n".join(lines))

    def _slash_approve(self, arg: str) -> None:
        """``/approve [任务ID短前缀] [签名]``——无参时签批任务表选中项。"""
        parts = arg.split()
        if not parts:
            self.action_approve_task()
            return
        raw = parts[0]
        sig = parts[1] if len(parts) > 1 else _default_signature()
        self._pending_approval = {"task_id": raw, "signature": sig, "decision": "approve"}
        self._set_hint(f"签批 {raw[:12]} · 签名 {sig}：Ctrl+Y 确认 · Esc 取消")

    @work(thread=True, exclusive=False)
    def _slash_search(self, query: str) -> None:
        from bacmap.interfaces.views import sample_rows, search_rows

        hits = search_rows(sample_rows(self.engine), query=query)
        text = "、".join(r["sample_id"] for r in hits) or "无命中"
        self.call_from_thread(self._logline, f"[#8b949e]检索 {_esc(query)!r}：{_esc(text)}[/]")

    @work(thread=True, exclusive=False)
    def _slash_submit(self, task_type: str, arg: str) -> None:
        import json

        from bacmap.tasks.spec import TaskType

        params: dict[str, Any] = {}
        if task_type == "analyze":
            samples = [s.strip() for s in arg.replace(",", " ").split() if s.strip()]
            if not samples:
                self.call_from_thread(self._logline, "[#f85149]用法：/analyze <样本ID>[/]")
                return
            params["samples"] = samples
        elif arg:
            try:
                params["scope"] = json.loads(arg)
            except ValueError:
                self.call_from_thread(self._logline, "[#f85149]scope 不是合法 JSON[/]")
                return
        try:
            tid = self.engine.submit(TaskType(task_type), params, "tui")
            msg = f"[green]已提交 {_esc(task_type)}：{_esc(tid)}[/green]"
        except (ValueError, NotImplementedError) as exc:
            msg = f"[#f85149]提交失败：{_esc(str(exc))}[/]"
        self.call_from_thread(self._logline, msg)
        self.call_from_thread(self.refresh_tasks)
