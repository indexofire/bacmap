#!/usr/bin/env python3
"""准备 Bacmap 注释数据库（Bakta + eggNOG-mapper）。

用法：
    pixi run python scripts/setup_annotation_dbs.py --bakta-only
    pixi run python scripts/setup_annotation_dbs.py --eggnog-only
    pixi run python scripts/setup_annotation_dbs.py            # 两者

默认写入 `$BACMAP_HOME/refs/bakta` 与 `$BACMAP_HOME/refs/eggnog`
（`BACMAP_HOME` 缺省为 `~/.local/share/bacmap`）。工作流也接受环境变量
`BACMAP_BAKTA_DB` 与 `BACMAP_EGGNOG_DATA_DIR` 覆盖。

注意：eggNOG-mapper 官方 diamond/annotation 数据库约数十 GB；请确保磁盘空间。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("BACMAP_HOME", "~/.local/share/bacmap")).expanduser()


def _refs() -> Path:
    return Path(os.environ.get("BACMAP_REFS_DIR", str(_home() / "refs"))).expanduser()


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def setup_bakta(root: Path, db_type: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"db-{db_type}"
    if (target / "bakta.db").is_file():
        print(f"Bakta DB already present: {target}")
        return
    _run(["bakta_db", "download", "--output", str(root), "--type", db_type])
    if not (target / "bakta.db").is_file():
        raise SystemExit(f"Bakta download finished but {target / 'bakta.db'} is missing")


def setup_eggnog(data_dir: Path, *, accept: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / "eggnog.db").is_file() and (data_dir / "eggnog_proteins.dmnd").is_file():
        print(f"eggNOG DB already present: {data_dir}")
        return
    cmd = ["download_eggnog_data.py", "--data_dir", str(data_dir)]
    if accept:
        cmd.append("-y")
    _run(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bakta-root", type=Path, default=_refs() / "bakta")
    parser.add_argument("--bakta-type", choices=["light", "full"], default="light")
    parser.add_argument("--bakta-only", action="store_true")
    parser.add_argument("--eggnog-dir", type=Path, default=_refs() / "eggnog")
    parser.add_argument("--eggnog-only", action="store_true")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="eggNOG downloader: assume yes (otherwise it may prompt)",
    )
    args = parser.parse_args()
    if args.bakta_only and args.eggnog_only:
        parser.error("--bakta-only and --eggnog-only are mutually exclusive")
    try:
        if not args.eggnog_only:
            setup_bakta(args.bakta_root, args.bakta_type)
        if not args.bakta_only:
            setup_eggnog(args.eggnog_dir, accept=args.yes)
    except subprocess.CalledProcessError as exc:
        print(f"database setup failed: {exc}", file=sys.stderr)
        return exc.returncode or 1
    print("annotation databases ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
