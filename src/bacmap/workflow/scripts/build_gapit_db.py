"""部署期构建 gapit 自定义数据库（ADR-20）。

当前用途：vpara 毒力基因库（tdh/trh/tlh），供 ``vpara_virulence`` 规则筛查。

- 幂等：``<datadir>/<name>/gapit-manifest.json`` 已存在且未 ``--force`` 时跳过；
- 可选 ``--manifest``：把 ``gapit:<name>``（版本 + 校验值）登记进
  ``$BACMAP_HOME/refs/manifest.json``，使运行记录（ADR-18 ``ref_databases``）可追溯；
- 失败显式非 0 退出（不静默降级）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_DESCRIPTION = "V. parahaemolyticus virulence gene markers (tdh/trh/tlh)"


def db_built(datadir: Path, name: str) -> bool:
    return (datadir / name / "gapit-manifest.json").is_file()


def _db_version(datadir: Path, name: str) -> tuple[str, str]:
    """从 gapit manifest 取 (version, sha256)。"""
    manifest = datadir / name / "gapit-manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("unknown", "")
    version = str(
        data.get("upstream_version")
        or (data.get("tool", {}) or {}).get("version")
        or "unknown"
    )
    return (version, str(data.get("sha256", "")))


def register_manifest(manifest_path: Path, name: str, version: str, checksum: str) -> None:
    """在 refs/manifest.json 中 upsert ``gapit:<name>``（保序、去重）。"""
    entry = {"name": f"gapit:{name}", "version": version, "checksum": checksum}
    if manifest_path.is_file():
        try:
            data: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
    else:
        data = None
    databases = data.get("databases") if isinstance(data, dict) else None
    if not isinstance(databases, list):
        databases = []
    databases = [d for d in databases if not (isinstance(d, dict) and d.get("name") == entry["name"])]
    databases.append(entry)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"databases": databases}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build a custom gapit database")
    parser.add_argument("--fasta", required=True)
    parser.add_argument("--name", default="vpara_virulence")
    parser.add_argument("--datadir", required=True)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--manifest", default="", help="refs/manifest.json 路径（可选登记）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    datadir = Path(args.datadir)
    datadir.mkdir(parents=True, exist_ok=True)

    if not db_built(datadir, args.name):
        cmd = [
            "gapit",
            "db",
            "build",
            args.name,
            args.fasta,
            "-D",
            str(datadir),
            "--force",
            "-e",
            args.description,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            print(
                f"ERROR: gapit db build failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}",
                file=sys.stderr,
            )
            return proc.returncode or 1

    version, checksum = _db_version(datadir, args.name)
    if args.manifest:
        register_manifest(Path(args.manifest), args.name, version, checksum)
    print(
        json.dumps(
            {"status": "ok", "name": args.name, "version": version, "datadir": str(datadir)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
