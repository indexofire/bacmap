"""``bacmap imports``：导入/修改提案的列表与保留期清理（v1.10.56，P4）。"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.store.import_jobs import ImportJobService


def _service(home: str) -> ImportJobService:
    return ImportJobService(Path(home) / "data" / "bacmap.sqlite")


def run_list(args: argparse.Namespace) -> None:
    with _service(args.home) as svc:
        items = svc.list(
            limit=max(1, min(int(args.limit), 500)),
            status=(args.status or "").strip(),
            kind=(args.kind or "").strip(),
        )
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        print(T("no proposals", "暂无提案"))
        return
    for item in items:
        print(
            f"{item['job_id']:<28} {item['kind']:<6} {item['status']:<14}"
            f" {item['created_by']:<16} {item['filename']}"
        )


def run_prune(args: argparse.Namespace) -> None:
    days = max(0, int(args.days))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    dry_run = bool(args.dry_run)
    with _service(args.home) as svc:
        jobs = svc.terminal_before(cutoff)
        expired = (
            svc.count_pending_before(cutoff) if dry_run else svc.expire_pending(cutoff)
        )
        removed = 0
        freed = 0
        for job in jobs:
            raw = str(job.get("file_path") or "")
            path = Path(raw) if raw else None
            allowed_root = Path(args.home) / "imports" / str(job["job_id"])
            if path is not None and path.is_file() and allowed_root in path.parents:
                freed += path.stat().st_size
                if not dry_run:
                    shutil.rmtree(allowed_root, ignore_errors=True)
            elif path is not None and path.is_dir() and path == allowed_root:
                freed += sum(
                    f.stat().st_size for f in path.rglob("*") if f.is_file()
                )
                if not dry_run:
                    shutil.rmtree(path, ignore_errors=True)
            if not dry_run and svc.delete(str(job["job_id"])):
                removed += 1
    payload = {
        "days": days,
        "dry_run": dry_run,
        "expired_pending": expired,
        "removed_terminal": len(jobs) if dry_run else removed,
        "freed_bytes": freed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    prefix = T("dry-run: would", "dry-run：将")
    print(
        T(
            f"{prefix} expire {expired} pending proposal(s), "
            f"remove {len(jobs)} terminal proposal(s) older than {days} day(s), "
            f"free {freed} byte(s)",
            f"{prefix}过期 {expired} 个待审核提案，"
            f"删除 {len(jobs)} 个超过 {days} 天的终态提案，释放 {freed} 字节",
        )
    )


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "imports",
        help=T("list or prune import proposals", "列出或清理导入/修改提案"),
    )
    p_sub = p.add_subparsers(dest="imports_command", required=True)

    p_list = p_sub.add_parser("list", aliases=["ls"], help=T("list proposals", "列出提案"))
    add_home(p_list)
    add_json(p_list)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--status", default="")
    p_list.add_argument("--kind", choices=["import", "edit"], default="")
    p_list.set_defaults(func=run_list)

    p_prune = p_sub.add_parser(
        "prune",
        help=T("expire and delete old proposals", "过期并删除旧提案"),
    )
    add_home(p_prune)
    add_json(p_prune)
    p_prune.add_argument("--days", type=int, default=30)
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.set_defaults(func=run_prune)


__all__ = ["add_parser"]
