"""bacmap 控制台命令（CLI）。

子命令：
- ``bacmap mcp``       MCP 服务器：stdio（默认）或 Streamable HTTP（Bearer 鉴权，ADR-12）
- ``bacmap web``       Web 控制台（默认 127.0.0.1:8800，ADR-16 只绑本机）
- ``bacmap tui``       全屏 TUI（Textual；监控 + 写操作 + 智能体对话）
- ``bacmap console``   交互式菜单（面向不使用子命令的用户）
- ``bacmap overview``  系统概览
- ``bacmap task ls|show|submit|approve|cancel``   任务查询与写操作
- ``bacmap sample ls|show``                        样本查询
- ``bacmap search``                                样本检索
- ``bacmap version``   版本号

所有查询子命令支持 ``--json`` 便于脚本消费。
"""

from __future__ import annotations

import argparse
import json as _json
import os
import sys
from datetime import UTC, datetime
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from bacmap.config import BACMAP_HOME

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _warn_if_exposed(host: str) -> None:
    if host not in _LOCAL_HOSTS:
        print(
            f"[bacmap] 警告：绑定非本机地址 {host!r}（ADR-16 默认只绑本机；"
            "跨机访问请确认网络边界与鉴权）",
            file=sys.stderr,
        )


def _engine(home: str) -> Any:
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    return DbosTaskEngine(Path(home))


def _emit_json(data: Any) -> None:
    print(_json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _console() -> Any:
    from rich.console import Console

    return Console()


# ---------------------------------------------------------------------------
# mcp / web / tui / console
# ---------------------------------------------------------------------------


def _run_mcp(args: argparse.Namespace) -> None:
    from bacmap.interfaces.mcp.server import build_server

    engine = None if args.read_only else _engine(args.home)
    server = build_server(engine)

    if args.transport == "stdio":
        server.run(transport="stdio")
        return

    from bacmap.interfaces.mcp.http import run_http

    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(
            f"HTTP 传输需要 Bearer token（ADR-12）：请先设置环境变量 {args.token_env}"
        )
    _warn_if_exposed(args.host)
    run_http(server, token=token, host=args.host, port=args.port, uds=(args.uds or None))


def _run_web(args: argparse.Namespace) -> None:
    import uvicorn

    from bacmap.interfaces.web.app import create_app

    token = os.environ.get(args.token_env, "")
    _warn_if_exposed(args.host)
    engine = _engine(args.home)
    uvicorn.run(create_app(engine, auth_token=token or None), host=args.host, port=args.port)


def _run_tui(args: argparse.Namespace) -> None:
    from bacmap.interfaces.tui.app import BacmapTUI

    BacmapTUI(_engine(args.home)).run()


def _run_console(args: argparse.Namespace) -> None:
    from bacmap.interfaces.cli.console import interactive_menu

    interactive_menu(_engine(args.home))


# ---------------------------------------------------------------------------
# overview / task / sample / search
# ---------------------------------------------------------------------------


def _run_overview(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import overview_data

    data = overview_data(_engine(args.home))
    if args.json:
        _emit_json(data)
        return
    c = _console()
    c.print("[bold]bacmap 系统概览[/bold]")
    c.print(f"  BACMAP_HOME : {data['paths']['BACMAP_HOME']}")
    c.print(f"  数据策略     : cloud ≤ {data['cloud_max_data_class']}（ADR-16）")
    c.print(f"  沙箱后端     : {data['sandbox']}")
    c.print(f"  组件版本     : {', '.join(f'{k} {v}' for k, v in data['versions'].items())}")
    if data["task_counts"]:
        c.print(f"  任务分布     : {data['task_counts']}")
    for ep in data["endpoints"]:
        flag = "" if ep["enabled"] else "（禁用）"
        c.print(f"  LLM 端点     : {ep['name']} [{ep['location']}] {ep['model']}{flag}")


def _run_task_ls(args: argparse.Namespace) -> None:
    tasks = _engine(args.home).list_tasks(args.limit)
    if args.json:
        _emit_json(tasks)
        return
    from rich.table import Table

    c = _console()
    table = Table(title=f"任务（最近 {len(tasks)}）", show_lines=False)
    for col in ("task_id", "type", "state", "step", "submitted_by", "updated_at"):
        table.add_column(col)
    for t in tasks:
        table.add_row(
            t["task_id"][:12],
            t["task_type"],
            t["state"],
            t.get("current_step") or "",
            t.get("submitted_by") or "",
            t.get("updated_at") or "",
        )
    c.print(table)


def _run_task_show(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import TaskId

    try:
        st = _engine(args.home).status(TaskId(args.task_id))
    except KeyError as exc:
        raise SystemExit(f"任务不存在：{args.task_id}") from exc
    if args.json:
        _emit_json(st.model_dump())
        return
    c = _console()
    c.print(f"[bold]{st.task_id}[/bold]  state={st.state.value}  step={st.current_step or '-'}")
    if st.message:
        c.print(f"  message: {st.message}")


def _run_task_submit(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import TaskType

    if args.type not in ("analyze", "curate"):
        raise SystemExit("task submit 仅支持 analyze|curate（mine/write 属开放路径）")
    params: dict[str, Any] = {}
    if args.samples:
        params["samples"] = [s.strip() for s in args.samples.split(",") if s.strip()]
    if args.scope:
        try:
            params["scope"] = _json.loads(args.scope)
        except ValueError as exc:
            raise SystemExit(f"scope 不是合法 JSON: {exc}") from exc
    try:
        tid = _engine(args.home).submit(TaskType(args.type), params, args.by)
    except (ValueError, NotImplementedError) as exc:
        raise SystemExit(f"提交失败：{exc}") from exc
    if args.json:
        _emit_json({"task_id": tid, "state": "running"})
    else:
        _console().print(
            f"已提交任务 [bold]{tid}[/bold]（{args.type}）；用 `bacmap task show {tid}` 轮询"
        )


def _run_task_approve(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import Approval, TaskId

    approval = Approval(
        approver=args.approver,
        decision=args.decision,
        signature=args.signature,
        comment=args.comment,
        at=datetime.now(UTC),
    )
    try:
        _engine(args.home).approve(TaskId(args.task_id), approval)
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"审批失败：{exc}") from exc
    _console().print(f"任务 {args.task_id} 已{('通过' if args.decision == 'approve' else '拒绝')}")


def _run_task_cancel(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import TaskId

    try:
        _engine(args.home).cancel(TaskId(args.task_id))
    except KeyError as exc:
        raise SystemExit(f"任务不存在：{args.task_id}") from exc
    except ValueError as exc:
        raise SystemExit(f"取消失败：{exc}") from exc
    _console().print(f"任务 {args.task_id} 已取消")


def _run_sample_ls(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows

    rows = sample_rows(_engine(args.home))
    if args.json:
        _emit_json(rows)
        return
    from rich.table import Table

    c = _console()
    table = Table(title=f"样本（{len(rows)}）")
    for col in ("sample_id", "species", "ST", "serovar", "AMR", "VF", "plasmid"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["sample_id"], r["verdict"], str(r["st"]), r["serovar"],
            str(r["n_card"]), str(r["n_vfdb"]), str(r["n_plasmid"]),
        )
    c.print(table)


def _run_sample_show(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows

    rows = sample_rows(_engine(args.home))
    row = next((r for r in rows if r["sample_id"] == args.sample_id), None)
    if row is None:
        raise SystemExit(f"样本不存在: {args.sample_id}")
    if args.json:
        _emit_json(row)
        return
    c = _console()
    c.print(
        f"[bold]{row['sample_id']}[/bold]  物种={row['verdict']}  "
        f"ST={row['st']}  血清型={row['serovar']}"
    )
    c.print(f"  毒力/耐药基因: {', '.join(row['card_genes'] + row['vfdb_genes']) or '无'}")
    c.print(f"  质粒: {', '.join(row['plasmids']) or '无'}")


def _run_search(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows, search_rows

    hits = search_rows(
        sample_rows(_engine(args.home)),
        query=args.query,
        serotype=args.serotype,
        mlst_st=args.st,
        amr_gene=args.gene,
    )
    if args.json:
        _emit_json(hits)
        return
    from rich.table import Table

    c = _console()
    table = Table(title=f"检索命中（{len(hits)}）")
    for col in ("sample_id", "species", "ST", "serovar"):
        table.add_column(col)
    for r in hits:
        table.add_row(r["sample_id"], r["verdict"], str(r["st"]), r["serovar"])
    c.print(table)


# ---------------------------------------------------------------------------
# 会话式助手（LLM 规划 → 确认 → 提交）
# ---------------------------------------------------------------------------


def _present_and_execute(args: argparse.Namespace, engine: Any, reply: Any) -> None:
    from rich.markup import escape as _esc
    from rich.prompt import Confirm

    from bacmap.interfaces.assistant import execute_plan, format_plan

    c = _console()
    if reply.message:
        c.print(_esc(reply.message))
    plan = reply.plan
    if plan is None or not plan.tasks:
        return
    c.print("建议执行的分析计划：")
    c.print(_esc(format_plan(plan)))
    if plan.needs_clarification:
        return
    if not args.yes and not Confirm.ask("确认提交该计划？", default=False, console=c):
        c.print("已取消。")
        return
    results = execute_plan(engine, plan, submitted_by=args.by)
    for r in results:
        mark = "✓" if r["ok"] else "✗"
        c.print(f"{mark} {r['task_type']}: {r.get('task_id') or r.get('error')}")


def _run_ask(args: argparse.Namespace) -> None:
    from bacmap.interfaces.assistant import build_session

    engine = _engine(args.home)
    reply = build_session(engine).respond(args.text)
    if args.json:
        _emit_json(
            {
                "message": reply.message,
                "degraded": reply.degraded,
                "plan": reply.plan.model_dump() if reply.plan else None,
            }
        )
        return
    _present_and_execute(args, engine, reply)


def _run_chat(args: argparse.Namespace) -> None:
    from rich.prompt import Prompt

    from bacmap.interfaces.assistant import build_session

    engine = _engine(args.home)
    session = build_session(engine)
    c = _console()
    c.print("[bold]bacmap 会话助手[/bold]（Ctrl-C 或空行退出）")
    while True:
        try:
            text = Prompt.ask("[cyan]你[/cyan]", console=c)
        except (EOFError, KeyboardInterrupt):
            break
        if not text.strip():
            break
        _present_and_execute(args, engine, session.respond(text))


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _add_home(p: argparse.ArgumentParser) -> None:
    p.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="以 JSON 输出（脚本友好）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bacmap", description="bacmap 本地病原菌基因组分析系统（architecture-frozen-v1）"
    )
    parser.add_argument("--version", action="version", version=f"bacmap {pkg_version('bacmap')}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_mcp = sub.add_parser("mcp", help="启动 MCP 服务器（stdio 或 Streamable HTTP）")
    _add_home(p_mcp)
    p_mcp.add_argument("--read-only", action="store_true", help="只读模式（不暴露任务提交工具）")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="传输")
    p_mcp.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址（默认仅本机）")
    p_mcp.add_argument("--port", type=int, default=8765, help="HTTP 端口（默认 8765）")
    p_mcp.add_argument("--uds", default="", help="改用 unix socket 路径")
    p_mcp.add_argument("--token-env", default="BACMAP_MCP_TOKEN", help="Bearer token 环境变量名")
    p_mcp.set_defaults(func=_run_mcp)

    p_web = sub.add_parser("web", help="启动 Web 控制台")
    _add_home(p_web)
    p_web.add_argument("--host", default="127.0.0.1", help="绑定地址（默认仅本机）")
    p_web.add_argument("--port", type=int, default=8800, help="端口（默认 8800）")
    p_web.add_argument("--token-env", default="BACMAP_WEB_TOKEN", help="Bearer token 环境变量名")
    p_web.set_defaults(func=_run_web)

    p_tui = sub.add_parser("tui", help="启动全屏 TUI（Textual）")
    _add_home(p_tui)
    p_tui.set_defaults(func=_run_tui)

    p_console = sub.add_parser("console", help="启动交互式菜单")
    _add_home(p_console)
    p_console.set_defaults(func=_run_console)

    p_ov = sub.add_parser("overview", help="系统概览")
    _add_home(p_ov)
    _add_json(p_ov)
    p_ov.set_defaults(func=_run_overview)

    p_task = sub.add_parser("task", help="任务查询与写操作")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)

    t_ls = task_sub.add_parser("ls", help="列出最近任务")
    _add_home(t_ls)
    _add_json(t_ls)
    t_ls.add_argument("--limit", type=int, default=50)
    t_ls.set_defaults(func=_run_task_ls)

    t_show = task_sub.add_parser("show", help="查看任务状态")
    t_show.add_argument("task_id")
    _add_home(t_show)
    _add_json(t_show)
    t_show.set_defaults(func=_run_task_show)

    t_sub = task_sub.add_parser("submit", help="提交 analyze/curate 任务")
    t_sub.add_argument("--type", choices=["analyze", "curate"], required=True)
    t_sub.add_argument("--samples", default="", help="样本 ID，逗号分隔（analyze）")
    t_sub.add_argument(
        "--scope", default="", help='筛选 JSON（curate，如 {"pathogen":"Salmonella"}）'
    )
    t_sub.add_argument("--by", default="cli", help="提交者")
    _add_home(t_sub)
    _add_json(t_sub)
    t_sub.set_defaults(func=_run_task_submit)

    t_appr = task_sub.add_parser("approve", help="审批签名（awaiting_approval 任务）")
    t_appr.add_argument("task_id")
    t_appr.add_argument("--approver", required=True)
    t_appr.add_argument("--decision", choices=["approve", "reject"], required=True)
    t_appr.add_argument("--signature", required=True)
    t_appr.add_argument("--comment", default=None)
    _add_home(t_appr)
    t_appr.set_defaults(func=_run_task_approve)

    t_cancel = task_sub.add_parser("cancel", help="取消任务")
    t_cancel.add_argument("task_id")
    _add_home(t_cancel)
    t_cancel.set_defaults(func=_run_task_cancel)

    p_sample = sub.add_parser("sample", help="样本查询")
    sample_sub = p_sample.add_subparsers(dest="sample_command", required=True)
    s_ls = sample_sub.add_parser("ls", help="列出已完成样本")
    _add_home(s_ls)
    _add_json(s_ls)
    s_ls.set_defaults(func=_run_sample_ls)
    s_show = sample_sub.add_parser("show", help="查看样本详情")
    s_show.add_argument("sample_id")
    _add_home(s_show)
    _add_json(s_show)
    s_show.set_defaults(func=_run_sample_show)

    p_search = sub.add_parser("search", help="样本检索")
    p_search.add_argument("--query", default="", help="关键词（物种/血清型/ST/基因）")
    p_search.add_argument("--serotype", default="", help="血清型过滤")
    p_search.add_argument("--st", default="", help="MLST ST 过滤")
    p_search.add_argument("--gene", default="", help="基因过滤（AMR/毒力）")
    _add_home(p_search)
    _add_json(p_search)
    p_search.set_defaults(func=_run_search)

    p_ask = sub.add_parser("ask", help="自然语言分析请求（LLM 规划 → 确认 → 提交）")
    p_ask.add_argument("text", help="自然语言分析需求，如：跑 SAM-001 的分析并比较去年暴发株")
    p_ask.add_argument("--by", default="cli", help="提交者")
    p_ask.add_argument("--yes", action="store_true", help="跳过交互确认直接提交")
    _add_home(p_ask)
    _add_json(p_ask)
    p_ask.set_defaults(func=_run_ask)

    p_chat = sub.add_parser("chat", help="多轮对话式分析助手")
    p_chat.add_argument("--by", default="cli", help="提交者")
    p_chat.add_argument("--yes", action="store_true", help="跳过交互确认直接提交")
    _add_home(p_chat)
    p_chat.set_defaults(func=_run_chat)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)
