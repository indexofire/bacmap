"""``bacmap plan``：计划的查看、确认与拒绝（v1.5.1，ADR-21 可信确认面）。

外部 Harness 经 MCP 创建/修订计划；人在这里看到完整参数后确认，确认绑定
``(plan_id, version, plan_hash)``，并以确定性 task_id 提交（重复确认幂等）。
"""

from __future__ import annotations

import argparse
import getpass
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bacmap.application.errors import ApplicationError
from bacmap.application.plans import PlanRecord, PlanService


def _actor() -> str:
    try:
        return f"cli:{getpass.getuser()}"
    except OSError:  # 无 USER/LOGNAME 且无 passwd 条目（极简容器）
        return "cli:unknown"


def _service(args: argparse.Namespace) -> PlanService:
    from bacmap.interfaces.cli.main import _engine

    engine = _engine(args.home)
    return PlanService(engine, Path(args.home) / "tasks.sqlite")


def _run(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except ApplicationError as exc:
        raise SystemExit(f"[{exc.code.value}] {exc.message}") from exc


def _as_json(rec: PlanRecord) -> dict[str, Any]:
    return rec.model_dump(mode="json")


def _print(rec: PlanRecord) -> None:
    from rich.console import Console
    from rich.markup import escape

    c = Console()
    c.print(
        f"[bold]plan {rec.plan_id}[/bold]  v{rec.version}  state={rec.state.value}  "
        f"hash={rec.short_hash}"
    )
    c.print(f"  created by {escape(rec.created_by)} at {rec.created_at}")
    if rec.rationale:
        c.print(f"  rationale: {escape(rec.rationale)}")
    for i, task in enumerate(rec.tasks):
        params = json.dumps(task.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
        c.print(f"  [{i}] {escape(params)}")
    for path, fp in rec.inputs.items():
        c.print(f"  input {escape(path)} → {fp[:32]}…")
    if rec.task_ids:
        c.print(f"  tasks: {', '.join(rec.task_ids)}")
    if rec.message:
        c.print(f"  message: {escape(rec.message)}")


def run_ls(args: argparse.Namespace) -> None:
    plans = _run(lambda: _service(args).list_plans(args.limit))
    if args.json:
        print(json.dumps([_as_json(p) for p in plans], ensure_ascii=False, indent=2))
        return
    for p in plans:
        kinds = ",".join(t.task_type for t in p.tasks)
        print(f"{p.plan_id}  v{p.version}  {p.state.value:<22} {kinds:<16} {p.updated_at}")


def run_show(args: argparse.Namespace) -> None:
    rec = _run(lambda: _service(args).get(args.plan_id, args.version))
    if args.json:
        print(json.dumps(_as_json(rec), ensure_ascii=False, indent=2))
        return
    _print(rec)
    if rec.state.value == "awaiting_confirmation":
        print(
            f"\n确认：bacmap plan confirm {rec.plan_id} --version {rec.version} "
            f"--hash {rec.short_hash}"
        )


def run_confirm(args: argparse.Namespace) -> None:
    service = _service(args)
    rec = _run(lambda: service.get(args.plan_id, args.version))
    expected = args.hash
    if not expected:
        # 交互确认：先展示被确认的确切版本，再以其哈希确认（人看到什么就确认什么）。
        from rich.prompt import Confirm

        _print(rec)
        if not Confirm.ask(f"确认并提交 plan {rec.plan_id} v{rec.version}？", default=False):
            raise SystemExit("已取消")
        expected = rec.plan_hash
    out = _run(lambda: service.confirm(args.plan_id, rec.version, expected, _actor()))
    if args.json:
        print(json.dumps(_as_json(out), ensure_ascii=False, indent=2))
        return
    _print(out)
    if out.state.value == "failed":
        raise SystemExit(1)


def run_reject(args: argparse.Namespace) -> None:
    out = _run(
        lambda: _service(args).reject(args.plan_id, args.version, args.reason, _actor())
    )
    print(f"plan {out.plan_id} v{out.version} 已拒绝")


def add_parser(
    sub: Any,
    add_home: Callable[[argparse.ArgumentParser], None],
    add_json: Callable[[argparse.ArgumentParser], None],
) -> None:
    p_plan = sub.add_parser("plan", help="分析计划：查看 / 确认提交 / 拒绝（v1.5）")
    plan_sub = p_plan.add_subparsers(dest="plan_command", required=True)

    ls = plan_sub.add_parser("list", aliases=["ls"], help="列出最近计划（各取最新版本）")
    ls.add_argument("--limit", type=int, default=20)
    add_home(ls)
    add_json(ls)
    ls.set_defaults(func=run_ls)

    show = plan_sub.add_parser("show", help="查看计划完整参数、哈希与状态")
    show.add_argument("plan_id")
    show.add_argument("--version", type=int, default=None, help="默认最新版本")
    add_home(show)
    add_json(show)
    show.set_defaults(func=run_show)

    confirm = plan_sub.add_parser(
        "confirm", help="确认并提交计划（省略 --hash 时先展示计划再交互确认）"
    )
    confirm.add_argument("plan_id")
    confirm.add_argument("--version", type=int, default=None, help="默认最新版本")
    confirm.add_argument("--hash", default="", help="plan show 给出的哈希（≥12 位前缀）")
    add_home(confirm)
    add_json(confirm)
    confirm.set_defaults(func=run_confirm)

    reject = plan_sub.add_parser("reject", help="拒绝计划（Harness 可据此修订）")
    reject.add_argument("plan_id")
    reject.add_argument("--version", type=int, required=True)
    reject.add_argument("--reason", required=True)
    add_home(reject)
    reject.set_defaults(func=run_reject)
