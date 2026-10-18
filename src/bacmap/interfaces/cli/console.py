"""bacmap 交互式菜单（`bacmap console`）。

面向不使用子命令的用户：编号菜单 + 最少提问，输出与 CLI 子命令一致。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from bacmap.interfaces.cli.main import _safe


def _task_table(tasks: list[dict[str, Any]]) -> Table:
    table = Table(title=f"任务（最近 {len(tasks)}）")
    for col in ("task_id", "type", "state", "step", "submitted_by"):
        table.add_column(col)
    for t in tasks:
        table.add_row(
            t["task_id"][:12], t["task_type"], t["state"],
            _safe(t.get("current_step") or ""), _safe(t.get("submitted_by") or ""),
        )
    return table


def _sample_table(rows: list[dict[str, Any]]) -> Table:
    table = Table(title=f"样本（{len(rows)}）")
    for col in ("sample_id", "species", "ST", "serovar", "AMR", "VF"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["sample_id"], _safe(r["verdict"]), str(r["st"]), _safe(r["serovar"]),
            str(r["n_card"]), str(r["n_vfdb"]),
        )
    return table


def interactive_menu(engine: Any) -> None:
    """交互式主循环（Ctrl-C 或 0 退出）。"""
    from bacmap.interfaces.views import overview_data, sample_rows, search_rows
    from bacmap.tasks.spec import Approval, TaskId, TaskType

    console = Console()
    choices = ["1", "2", "3", "4", "5", "6", "0"]
    while True:
        console.print(
            "\n[bold]bacmap 控制台[/bold]\n"
            "  1) 系统概览   2) 任务列表   3) 提交任务\n"
            "  4) 审批签名   5) 样本列表   6) 检索样本\n"
            "  0) 退出"
        )
        try:
            choice = Prompt.ask("请选择", choices=choices, default="0", console=console)
        except (EOFError, KeyboardInterrupt):
            break

        try:
            if choice == "0":
                break
            if choice == "1":
                data = overview_data(engine)
                console.print(f"BACMAP_HOME: {data['paths']['BACMAP_HOME']}")
                console.print(
                    f"沙箱: {data['sandbox']}  云数据上限: {data['cloud_max_data_class']}"
                )
                console.print(f"任务分布: {data['task_counts'] or '（无）'}")
            elif choice == "2":
                console.print(_task_table(engine.list_tasks(50)))
            elif choice == "3":
                ttype = Prompt.ask("任务类型", choices=["analyze", "curate"], console=console)
                params: dict[str, Any] = {}
                if ttype == "analyze":
                    raw = Prompt.ask("样本 ID（逗号分隔）", console=console)
                    params["samples"] = [s.strip() for s in raw.split(",") if s.strip()]
                tid = engine.submit(TaskType(ttype), params, "console")
                console.print(f"已提交：{tid}")
            elif choice == "4":
                pending = [t for t in engine.list_tasks(50) if t["state"] == "awaiting_approval"]
                if not pending:
                    console.print("没有待审批任务。")
                    continue
                console.print(_task_table(pending))
                tid = Prompt.ask("任务 ID", console=console)
                approver = Prompt.ask("审批人", console=console)
                decision = Prompt.ask("决定", choices=["approve", "reject"], console=console)
                typed_decision: Literal["approve", "reject"] = (
                    "approve" if decision == "approve" else "reject"
                )
                signature = Prompt.ask("签名", console=console)
                engine.approve(
                    TaskId(tid),
                    Approval(
                        approver=approver, decision=typed_decision,
                        signature=signature, at=datetime.now(UTC),
                    ),
                )
                console.print("已处理。")
            elif choice == "5":
                console.print(_sample_table(sample_rows(engine)))
            elif choice == "6":
                query = Prompt.ask(
                    "关键词（物种/血清型/ST/基因，可空）", default="", console=console
                )
                console.print(_sample_table(search_rows(sample_rows(engine), query=query)))
        except (KeyError, ValueError, NotImplementedError) as exc:
            console.print(f"[red]操作失败：{_safe(exc)}[/red]")

    console.print("已退出 bacmap 控制台。")
