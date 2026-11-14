"""``bacmap specimen``：样本实体（v1.10.27，身份模型 P1）。

样本（specimen）是唯一送检编号（如 ``A03-SN-001``），可产出 0..N 个菌株；
编号允许为空（外部未提供时先留空），后续用 ``bacmap specimen import`` 或
``assign`` 补录。样本级测序（mNGS/tNGS）在下一大版本接入。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T


def _service(home: str) -> Any:
    from bacmap.store.specimens import SpecimenService

    return SpecimenService(Path(home) / "data" / "bacmap.sqlite")


def run_ls(args: argparse.Namespace) -> None:
    with _service(args.home) as svc:
        rows = svc.list(args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    if not rows:
        print(T("no specimens registered", "暂无样本登记"))
        return
    for r in rows:
        print(
            f"{r['specimen_id']:<28} isolates={r['n_isolates']:<4}"
            f" origin={r['origin'] or '-'}"
        )


def run_show(args: argparse.Namespace) -> None:
    with _service(args.home) as svc:
        row = svc.get(args.specimen_id)
        isolates = svc.isolates(args.specimen_id) if row else []
    if row is None:
        raise SystemExit(
            T(f"specimen not found: {args.specimen_id}", f"样本不存在：{args.specimen_id}")
        )
    payload = {**row, "isolates": isolates}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"specimen : {row['specimen_id']}")
    print(f"origin   : {row['origin'] or '-'}")
    print(f"isolates : {len(isolates)}")
    for iso in isolates:
        print(f"  - {iso['isolate_id']}")


def _read_assignments(path: Path, by: str) -> dict[str, str]:
    """导入 TSV：`specimen` + (`dataset`|`sample`|`isolate`) 两列。"""
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not lines:
        raise SystemExit(T("empty import file", "导入文件为空"))
    header = [cell.strip().lower() for cell in lines[0].split("\t")]
    key_col = "isolate" if by == "isolate" else None
    if key_col is None:
        for candidate in ("dataset", "sample"):
            if candidate in header:
                key_col = candidate
                break
    if "specimen" not in header or key_col is None:
        raise SystemExit(
            T(
                "import TSV needs a 'specimen' column and a 'dataset'/'sample'"
                " (or 'isolate' when --by isolate) column",
                "导入 TSV 需要 'specimen' 列与 'dataset'/'sample' 列"
                "（--by isolate 时用 'isolate' 列）",
            )
        )
    si, ki = header.index("specimen"), header.index(key_col)
    mapping: dict[str, str] = {}
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= max(si, ki):
            continue
        specimen, key = cells[si].strip(), cells[ki].strip()
        if specimen and key:
            mapping[key] = specimen
    return mapping


def run_import(args: argparse.Namespace) -> None:
    from bacmap.workflow.samples_registry import assign_specimens

    mapping = _read_assignments(Path(args.tsv).expanduser(), args.by)
    if getattr(args, "dry_run", False):
        result: dict[str, Any] = {
            "updated": len(mapping),
            "specimens": sorted(set(mapping.values())),
            "missing": [],
            "by": args.by,
            "dry_run": True,
        }
    else:
        result = assign_specimens(Path(args.home), mapping, by=args.by)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(
        T(
            f"assigned {result['updated']} row(s) across"
            f" {len(result['specimens'])} specimen(s)",
            f"已关联 {result['updated']} 行，涉及 {len(result['specimens'])} 个样本",
        )
    )
    if result.get("missing"):
        print(
            T(
                f"not found: {', '.join(result['missing'])}",
                f"未找到：{', '.join(result['missing'])}",
            )
        )


def run_assign(args: argparse.Namespace) -> None:
    from bacmap.workflow.samples_registry import assign_specimens

    datasets = [v for v in (args.dataset or []) if v]
    isolates = [v for v in (args.isolate or []) if v]
    if not datasets and not isolates:
        raise SystemExit(
            T("give at least one --dataset or --isolate", "至少给一个 --dataset 或 --isolate")
        )
    results = []
    if datasets:
        results.append(
            assign_specimens(
                Path(args.home), {d: args.specimen for d in datasets}, by="dataset"
            )
        )
    if isolates:
        results.append(
            assign_specimens(
                Path(args.home), {i: args.specimen for i in isolates}, by="isolate"
            )
        )
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for r in results:
        print(
            T(
                f"{r['by']}: assigned {r['updated']} row(s)"
                + (f"; not found: {', '.join(r['missing'])}" if r.get("missing") else ""),
                f"{r['by']}：已关联 {r['updated']} 行"
                + (f"；未找到：{', '.join(r['missing'])}" if r.get("missing") else ""),
            )
        )


def run_delete(args: argparse.Namespace) -> None:
    from bacmap.workflow.samples_registry import delete_specimen

    try:
        result = delete_specimen(Path(args.home), args.specimen_id, force=args.force)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not result["deleted"]:
        raise SystemExit(
            T(f"specimen not found: {args.specimen_id}", f"样本不存在：{args.specimen_id}")
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(
        T(
            f"deleted specimen {result['specimen_id']}"
            + (
                f" ({result['unlinked_isolates']} isolate(s) unlinked,"
                f" {result['updated_tsv_rows']} tsv row(s) cleared)"
                if result["unlinked_isolates"] or result["updated_tsv_rows"]
                else ""
            ),
            f"已删除样本 {result['specimen_id']}"
            + (
                f"（解除 {result['unlinked_isolates']} 个菌株关联，清理 "
                f"{result['updated_tsv_rows']} 行 samples.tsv）"
                if result["unlinked_isolates"] or result["updated_tsv_rows"]
                else ""
            ),
        )
    )


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "specimen",
        help=T(
            "sample (specimen) entities: list/show/import/assign/delete",
            "样本实体：列表/详情/导入/关联/删除",
        ),
    )
    s = p.add_subparsers(dest="specimen_command", required=True)

    ls = s.add_parser("list", aliases=["ls"], help=T("list specimens", "列出样本"))
    add_home(ls)
    add_json(ls)
    ls.add_argument("--limit", type=int, default=200)
    ls.set_defaults(func=run_ls)

    show = s.add_parser("show", help=T("show one specimen and its isolates", "查看样本及菌株"))
    show.add_argument("specimen_id")
    add_home(show)
    add_json(show)
    show.set_defaults(func=run_show)

    imp = s.add_parser(
        "import",
        help=T(
            "import specimen↔dataset/isolate mappings from TSV",
            "从 TSV 导入样本↔数据/菌株关联",
        ),
    )
    imp.add_argument("tsv")
    imp.add_argument(
        "--by",
        choices=["dataset", "isolate"],
        default="dataset",
        help=T(
            "match key column (dataset/sample or isolate)",
            "匹配键（dataset/sample 或 isolate）",
        ),
    )
    imp.add_argument("--dry-run", action="store_true")
    add_home(imp)
    add_json(imp)
    imp.set_defaults(func=run_import)

    assign = s.add_parser(
        "assign", help=T("assign datasets/isolates to a specimen", "把数据/菌株关联到样本")
    )
    assign.add_argument("--specimen", required=True)
    assign.add_argument("--dataset", action="append", default=[])
    assign.add_argument("--isolate", action="append", default=[])
    add_home(assign)
    add_json(assign)
    assign.set_defaults(func=run_assign)

    delete = s.add_parser(
        "delete", help=T("delete a specimen (empty by default)", "删除样本（默认仅空样本）")
    )
    delete.add_argument("specimen_id")
    delete.add_argument(
        "--force",
        action="store_true",
        help=T(
            "unlink its isolates (does not delete isolates/data) and delete",
            "先解除菌株关联（不删菌株/数据）再删除",
        ),
    )
    add_home(delete)
    add_json(delete)
    delete.set_defaults(func=run_delete)
