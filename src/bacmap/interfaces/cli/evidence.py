"""``bacmap run|gom``：运行记录与 GOM 的只读命令（v1.7.1，ADR-18/13）。"""

from __future__ import annotations

import argparse
import json
from typing import Any


def _emit(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    from rich.console import Console
    from rich.table import Table

    c = Console()
    if isinstance(data, list):
        table = Table(show_lines=False)
        cols = list(data[0].keys()) if data else []
        for col in cols:
            table.add_column(col)
        for row in data:
            table.add_row(*(str(row.get(col, "")) for col in cols))
        c.print(table)
        return
    c.print(json.dumps(data, ensure_ascii=False, indent=2))


def run_ls(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import list_runs

    rows = list_runs(args.home, args.limit)
    if args.json:
        _emit(rows, True)
        return
    for r in rows:
        print(
            f"{r['run_id'][:16]}  {r['workflow']:<10} {','.join(r['strain_ids'])[:24]:<24} "
            f"{r['started_at'][:19]}  {r.get('baseline_version') or '-'}"
        )
    if not rows:
        print("（暂无运行记录）")


def run_show(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import run_detail

    data = run_detail(args.home, args.run_id)
    if data is None:
        raise SystemExit(f"运行记录不存在：{args.run_id}")
    _emit(data, args.json)


def run_compare(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import compare_run_records

    data = compare_run_records(args.home, args.run_a, args.run_b)
    if data is None:
        raise SystemExit("运行记录不存在（检查两个 run_id）")
    if args.json:
        _emit(data, True)
        return
    verdict = "来源相同" if data["same_provenance"] else "来源不同"
    print(f"{verdict}；变化类别：{', '.join(data['changed_categories']) or '无'}")
    for d in data["diffs"]:
        print(f"  [{d['category']}] {d['field']}: {d['a']!r} → {d['b']!r}")


def gom_ls(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import list_gom_objects

    rows = list_gom_objects(args.home, args.type, args.limit)
    if args.json:
        _emit(rows, True)
        return
    for o in rows:
        keys = ",".join(o["payload_keys"])[:40]
        print(
            f"{o['object_id'][:20]:<20} v{o['version']:<3} {o['object_type']:<10} "
            f"{o.get('strain_id') or '-':<12} {o['created_at'][:19]}  {keys}"
        )
    if not rows:
        print("（暂无对象）")


def gom_show(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import gom_object

    data = gom_object(args.home, args.object_id, args.version)
    if data is None:
        raise SystemExit(f"GOM 对象不存在：{args.object_id}")
    _emit(data, args.json)


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser("run", help="运行记录（ADR-18 证据链）只读查询")
    r = p.add_subparsers(dest="run_command", required=True)
    ls = r.add_parser("list", aliases=["ls"], help="最近运行记录")
    ls.add_argument("--limit", type=int, default=20)
    add_home(ls)
    add_json(ls)
    ls.set_defaults(func=run_ls)
    show = r.add_parser("show", help="单条运行记录全文（参数/版本/输入哈希/种子）")
    show.add_argument("run_id")
    add_home(show)
    add_json(show)
    show.set_defaults(func=run_show)
    cmp_ = r.add_parser("compare", help="两次运行的来源逐字段比较")
    cmp_.add_argument("run_a")
    cmp_.add_argument("run_b")
    add_home(cmp_)
    add_json(cmp_)
    cmp_.set_defaults(func=run_compare)

    g = sub.add_parser("gom", help="GOM 对象只读查询")
    gs = g.add_subparsers(dest="gom_command", required=True)
    gl = gs.add_parser("list", aliases=["ls"], help="最新版本对象列表")
    gl.add_argument("--type", default=None, help="sample/analysis/report/task/...（默认全部）")
    gl.add_argument("--limit", type=int, default=50)
    add_home(gl)
    add_json(gl)
    gl.set_defaults(func=gom_ls)
    gsh = gs.add_parser("show", help="对象全文（默认最新版本）")
    gsh.add_argument("object_id")
    gsh.add_argument("--version", type=int, default=None)
    add_home(gsh)
    add_json(gsh)
    gsh.set_defaults(func=gom_show)
