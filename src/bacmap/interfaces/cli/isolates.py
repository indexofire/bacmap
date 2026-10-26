"""``bacmap isolate``：菌株实体与传代谱系（v1.8.2，I3）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _service(home: str) -> Any:
    from bacmap.store.isolates import IsolateService

    return IsolateService(Path(home) / "data" / "bacmap.sqlite")


def run_ls(args: argparse.Namespace) -> None:
    with _service(args.home) as svc:
        rows = svc.list()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        lineage = r["lineage_id"] or "-"
        passage = "-" if r["passage"] is None else r["passage"]
        print(f"{r['isolate_id']:<28} lineage={lineage:<20} passage={passage}")


def run_show(args: argparse.Namespace) -> None:
    with _service(args.home) as svc:
        row = svc.get(args.isolate_id)
    if row is None:
        raise SystemExit(f"isolate 不存在：{args.isolate_id}")
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    print(f"isolate : {row['isolate_id']}")
    print(f"lineage : {row['lineage_id'] or '-'}")
    print(f"passage : {'-' if row['passage'] is None else row['passage']}")


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser("isolate", help="菌株实体与传代谱系（I3）")
    s = p.add_subparsers(dest="isolate_command", required=True)
    ls = s.add_parser("list", aliases=["ls"], help="列出已登记 isolate")
    add_home(ls)
    add_json(ls)
    ls.set_defaults(func=run_ls)
    show = s.add_parser("show", help="查看单个 isolate")
    show.add_argument("isolate_id")
    add_home(show)
    add_json(show)
    show.set_defaults(func=run_show)
