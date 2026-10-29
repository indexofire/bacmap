"""运维命令（v1.7.2）：``bacmap doctor`` / ``backup`` / ``restore`` / ``events prune``。

- doctor：只读体检（目录可写、库版本、沙箱后端、LLM 端点、磁盘），有 fail 项即退出码 1；
- backup：把配置、SQLite 库（用 backup API 取一致快照）、运行清单打进一个 zip；
- restore：从 zip 恢复，拒绝非空目录（除非 --force），并拒绝路径穿越条目；
- events prune：按保留期清理领域事件（管理员操作；审计保留策略见文档）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

_DB_NAMES = (
    "tasks.sqlite",
    "dbos.sqlite",  # DBOS 系统库：工作流/步骤检查点，缺它则运行中任务无法恢复
    "runs.sqlite",
    "gom.sqlite",
    "baseline.sqlite",
    "data/bacmap.sqlite",
    "data/knowledge.sqlite",
)


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def collect_checks(home: Path) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if not home.is_dir():
        return [_check("home", "fail", f"目录不存在：{home}")]
    try:
        probe = home / ".doctor-write-probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append(_check("home", "ok", str(home)))
    except OSError as exc:
        checks.append(_check("home", "fail", f"不可写：{exc}"))

    from bacmap.store.migrations import schema_version
    from bacmap.tasks.spec import TASKS_MIGRATIONS

    db = home / "tasks.sqlite"
    if db.is_file():
        try:
            version = schema_version(db)
            expected = len(TASKS_MIGRATIONS)
            status = "ok" if version == expected else "warn"
            checks.append(_check("database", status, f"tasks.sqlite v{version}（期望 {expected}）"))
        except sqlite3.Error as exc:
            checks.append(_check("database", "fail", f"tasks.sqlite 无法读取：{exc}"))
    else:
        checks.append(_check("database", "warn", "tasks.sqlite 尚未创建（首次运行后生成）"))

    try:
        from bacmap.agent.sandbox import SandboxExecutor

        backend = SandboxExecutor().backend_name()
        status = "ok" if backend not in ("none", "unavailable") else "warn"
        checks.append(_check("sandbox", status, backend))
    except Exception as exc:  # 体检不因探测失败中断
        checks.append(_check("sandbox", "warn", f"探测失败：{type(exc).__name__}"))

    try:
        from bacmap.interfaces.views import endpoint_status

        class _Home:
            def __init__(self, path: Path) -> None:
                self.home = path

        detail = endpoint_status(_Home(home))
        status = "ok" if "已连接" in detail else "warn"
        checks.append(_check("llm", status, detail))
    except Exception as exc:
        checks.append(_check("llm", "warn", f"探测失败：{type(exc).__name__}"))

    usage = shutil.disk_usage(home)
    free_gb = usage.free / (1024**3)
    checks.append(
        _check("disk", "ok" if free_gb >= 1 else "fail", f"可用 {free_gb:.1f} GB")
    )

    missing = [
        t for t in ("gside", "gapit", "gmlst", "snakemake") if shutil.which(t) is None
    ]
    tools_detail = (
        "外部工具缺失：" + ", ".join(missing)
        if missing
        else "gside/gapit/gmlst/snakemake 可用"
    )
    checks.append(_check("tools", "ok" if not missing else "warn", tools_detail))
    return checks


def doctor(args: argparse.Namespace) -> None:
    home = Path(args.home)
    checks = collect_checks(home)
    ok = not any(c["status"] == "fail" for c in checks)
    if args.json:
        print(json.dumps({"home": str(home), "ok": ok, "checks": checks}, ensure_ascii=False))
    else:
        for c in checks:
            mark = {"ok": "✓", "warn": "!", "fail": "✗"}[c["status"]]
            print(f"{mark} {c['name']:<9} {c['detail']}")
        print("全部通过" if ok else "存在失败项")
    if not ok:
        raise SystemExit(1)


def _iter_backup_files(home: Path) -> list[Path]:
    files: list[Path] = []
    cfg = home / "config.toml"
    if cfg.is_file():
        files.append(cfg)
    files.extend(p for p in (home / n for n in _DB_NAMES) if p.is_file())
    manifest = home / "refs" / "manifest.json"
    if manifest.is_file():
        files.append(manifest)
    runs_dir = home / "runs"
    if runs_dir.is_dir():
        files.extend(p for p in runs_dir.rglob("run_manifest.json") if p.is_file())
    return files


def _snapshot(db: Path, target: Path) -> None:
    with sqlite3.connect(db) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def backup(args: argparse.Namespace) -> None:
    home = Path(args.home)
    out = Path(args.out)
    if not home.is_dir():
        raise SystemExit(f"目录不存在：{home}")
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in _iter_backup_files(home):
            rel = path.relative_to(home).as_posix()
            if path.suffix == ".sqlite":
                with tempfile.TemporaryDirectory() as td:
                    snap = Path(td) / path.name
                    _snapshot(path, snap)
                    z.write(snap, rel)
            else:
                z.write(path, rel)
            count += 1
        if args.with_results:
            results = home / "results"
            if results.is_dir():
                for p in results.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(home).as_posix())
                        count += 1
    print(f"已备份 {count} 个文件 → {out}")


def _safe_extract(z: zipfile.ZipFile, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    for name in z.namelist():
        dest = (target / name).resolve()
        if not str(dest).startswith(str(root) + "/") and dest != root:
            raise SystemExit(f"备份包含非法路径：{name!r}")
    z.extractall(target)


def _verify_dbs(target: Path) -> None:
    for name in _DB_NAMES:
        db = target / name
        if not db.is_file():
            continue
        with sqlite3.connect(db) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise SystemExit(f"恢复后完整性检查失败：{name}")


def restore(args: argparse.Namespace) -> None:
    src = Path(args.from_zip)
    target = Path(args.home)
    if not src.is_file():
        raise SystemExit(f"备份文件不存在：{src}")
    if target.exists() and any(target.iterdir()) and not args.force:
        raise SystemExit(f"目标目录非空：{target}（确认覆盖请加 --force）")
    with zipfile.ZipFile(src) as z:
        _safe_extract(z, target)
    _verify_dbs(target)
    print(f"已恢复 → {target}（SQLite 完整性检查通过）")


def events_prune(args: argparse.Namespace) -> None:
    from bacmap.tasks.events import EventLog

    db = Path(args.home) / "tasks.sqlite"
    if not db.is_file():
        raise SystemExit(f"tasks.sqlite 不存在：{db}")
    pruned = EventLog(db).prune(older_than_days=max(0, args.days))
    if args.json:
        print(json.dumps({"pruned": pruned, "days": args.days}))
    else:
        print(f"已清理 {pruned} 条早于 {args.days} 天的事件")


def results_migrate(args: argparse.Namespace) -> None:
    from bacmap.store.results_layout import flat_result_samples, migrate_flat_results

    home = Path(args.home)
    pending = flat_result_samples(home)
    if args.dry_run:
        print(f"待迁移 {len(pending)} 个扁平结果目录：{', '.join(pending) or '无'}")
        return
    moved = migrate_flat_results(home)
    print(f"已迁移 {moved} 个扁平结果目录到 results/runs/legacy-*/ 并替换为最新运行链接")


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    d = sub.add_parser("doctor", help="只读体检（目录/库/沙箱/LLM/磁盘/外部工具）")
    add_home(d)
    add_json(d)
    d.set_defaults(func=doctor)

    b = sub.add_parser("backup", help="备份配置、SQLite 库与运行清单到一个 zip")
    add_home(b)
    b.add_argument("--out", required=True, help="输出 zip 路径")
    b.add_argument("--with-results", action="store_true", help="连同 results/ 一起备份（可能很大）")
    b.set_defaults(func=backup)

    r = sub.add_parser("restore", help="从 zip 恢复（默认拒绝非空目录）")
    add_home(r)
    r.add_argument("--from", dest="from_zip", required=True, help="备份 zip 路径")
    r.add_argument("--force", action="store_true", help="允许恢复到非空目录（不删除现有文件）")
    r.set_defaults(func=restore)

    res = sub.add_parser("results", help="结果目录维护（P2：run 级布局）")
    rs = res.add_subparsers(dest="results_command", required=True)
    rm = rs.add_parser(
        "migrate", help="旧扁平 results/<name>（样本 + snp/cgmlst）迁入 runs/ 并替换为链接"
    )
    add_home(rm)
    rm.add_argument("--dry-run", action="store_true", help="只列出待迁移目录")
    rm.set_defaults(func=results_migrate)

    e = sub.add_parser("events", help="领域事件维护")
    es = e.add_subparsers(dest="events_command", required=True)
    p = es.add_parser("prune", help="按保留期清理事件（管理员操作）")
    add_home(p)
    add_json(p)
    p.add_argument("--days", type=int, required=True, help="保留最近 N 天（0 = 全部清理）")
    p.set_defaults(func=events_prune)
