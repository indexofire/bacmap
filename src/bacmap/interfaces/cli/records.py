"""``bacmap record``：元数据 / 化验结果 / 文献知识库的记录任务（v1.7）。

写操作仍只经任务层（ADR-07）：本命令只把一条类型化记录提交为 ``record`` 任务，
由任务引擎写入 store 并留下任务/事件审计。知识库导入只入暂存，需再提交
``knowledge-approve`` 完成人审（引用门只认已审核条目）。
"""

from __future__ import annotations

import argparse
import json
from typing import Any


def _parse_fields(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in pairs:
        if "=" not in raw:
            raise SystemExit(f"--field 需要 k=v 形式：{raw!r}")
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            raise SystemExit(f"--field 键为空：{raw!r}")
        out[key] = value.strip()
    return out


def submit_record(args: argparse.Namespace, params: dict[str, Any]) -> None:
    from bacmap.interfaces.cli.main import _engine
    from bacmap.tasks.spec import TaskType

    params = {**params, "kind": args.kind_value}
    try:
        tid = _engine(args.home).submit(TaskType.RECORD, params, args.by)
    except ValueError as exc:
        raise SystemExit(f"提交失败：{exc}") from exc
    if args.json:
        print(json.dumps({"task_id": tid, "state": "running", "kind": params["kind"]}))
        return
    print(f"已提交记录任务 {tid}（{params['kind']}）；用 `bacmap task show {tid}` 查看结果")


def run_record(args: argparse.Namespace) -> None:
    kind = args.record_command
    if kind == "metadata":
        params: dict[str, Any] = {
            "strain_id": args.strain_id,
            "sample_id": args.sample_id or args.strain_id,
            "fields": _parse_fields(args.field),
        }
        args.kind_value = "metadata"
    elif kind == "lab":
        params = {
            "strain_id": args.strain_id,
            "category": args.category,
            "test_name": args.test_name,
            "result": args.result,
            "unit": args.unit,
            "method": args.method,
            "interpretation": args.interpretation,
            "standard": args.standard,
            "tested_date": args.tested_date,
            "tested_by": args.tested_by,
            "lab": args.lab,
            "notes": args.notes,
        }
        args.kind_value = "lab_result"
    elif kind == "knowledge-import":
        params = {
            "title": args.title,
            "authors": args.authors,
            "year": args.year,
            "source": args.source,
            "identifier": args.identifier,
            "content": args.content,
            "entry_kind": args.entry_kind,
        }
        params = {k: v for k, v in params.items() if v not in ("", None)}
        args.kind_value = "knowledge_import"
    else:  # knowledge-approve
        params = {"entry_id": args.entry_id}
        args.kind_value = "knowledge_approve"
    submit_record(args, params)


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser("record", help="记录元数据/化验/文献知识库（经任务层，v1.7）")
    rec = p.add_subparsers(dest="record_command", required=True)

    m = rec.add_parser("metadata", help="录入/更新菌株元数据")
    m.add_argument("--strain-id", required=True)
    m.add_argument("--sample-id", default="", help="默认与 strain-id 相同")
    m.add_argument(
        "--field",
        action="append",
        default=[],
        help="字段 k=v，可重复（如 --field province=Guangdong）",
    )
    m.add_argument("--by", default="cli", help="提交者")
    add_home(m)
    add_json(m)
    m.set_defaults(func=run_record)

    lab = rec.add_parser("lab", help="录入一条化验结果")
    lab.add_argument("--strain-id", required=True)
    lab.add_argument("--category", required=True)
    lab.add_argument("--test-name", required=True)
    lab.add_argument("--result", required=True)
    lab.add_argument("--unit", default="")
    lab.add_argument("--method", default="")
    lab.add_argument("--interpretation", default="")
    lab.add_argument("--standard", default="")
    lab.add_argument("--tested-date", default="")
    lab.add_argument("--tested-by", default="")
    lab.add_argument("--lab", default="")
    lab.add_argument("--notes", default="")
    lab.add_argument("--by", default="cli", help="提交者")
    add_home(lab)
    add_json(lab)
    lab.set_defaults(func=run_record)

    ki = rec.add_parser("knowledge-import", help="文献入暂存区（待审核）")
    ki.add_argument("--title", required=True)
    ki.add_argument("--authors", default="")
    ki.add_argument("--year", type=int, default=None)
    ki.add_argument("--source", default="")
    ki.add_argument("--identifier", default="", help="如 PMID:12345678")
    ki.add_argument("--content", default="")
    ki.add_argument(
        "--entry-kind", choices=["literature", "method", "report"], default="literature"
    )
    ki.add_argument("--by", default="cli", help="提交者")
    add_home(ki)
    add_json(ki)
    ki.set_defaults(func=run_record)

    ka = rec.add_parser("knowledge-approve", help="审核知识库条目（引用门只认已审核）")
    ka.add_argument("entry_id", type=int)
    ka.add_argument("--by", default="cli", help="审批者")
    add_home(ka)
    add_json(ka)
    ka.set_defaults(func=run_record)


__all__ = ["add_parser", "run_record"]
