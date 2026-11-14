#!/usr/bin/env python3
"""下载进化分析参考基因组（SNP / 重组，部署期，NCBI）。

真正的取回逻辑在 ``src/bacmap/workflow/scripts/fetch_reference_genomes.py``；
本脚本只负责补默认路径、串联 accession 核验，方便运维直接运行：

    pixi run python scripts/fetch_reference_genomes.py            # 全部组
    pixi run python scripts/fetch_reference_genomes.py --only salmonella,vpara
    pixi run python scripts/fetch_reference_genomes.py --verify --strict

默认路径：
    参考 FASTA   $BACMAP_DATA_DIR/reference/genomes/   (默认 $BACMAP_HOME/data/...)
    manifest     $BACMAP_HOME/refs/manifest.json
    accession 表 src/bacmap/workflow/config/reference_accessions.yaml

已存在的参考默认跳过；``--force`` 重取。``--verify`` 先用 NCBI esummary 核对
accession 与物种是否匹配（防止张冠李戴的参考污染 SNP 树）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_FETCH = _REPO / "src" / "bacmap" / "workflow" / "scripts" / "fetch_reference_genomes.py"
_VERIFY = _REPO / "src" / "bacmap" / "workflow" / "scripts" / "verify_reference_accessions.py"
_DEFAULT_MANIFEST = _REPO / "src" / "bacmap" / "workflow" / "config" / "reference_accessions.yaml"


def _home() -> Path:
    return Path(os.environ.get("BACMAP_HOME", "~/.local/share/bacmap")).expanduser()


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch bacmap reference genomes (NCBI)")
    ap.add_argument("--home", default=str(_home()), help="BACMAP_HOME（默认 ~/.local/share/bacmap）")
    ap.add_argument("--data-dir", default="", help="覆盖 BACMAP_DATA_DIR")
    ap.add_argument("--refs-dir", default="", help="覆盖 BACMAP_REFS_DIR")
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST), help="reference_accessions.yaml")
    ap.add_argument("--only", default="", help="只处理这些组（逗号分隔）")
    ap.add_argument("--force", action="store_true", help="已存在也重取")
    ap.add_argument("--verify", action="store_true", help="下载前先核验 accession")
    ap.add_argument("--strict", action="store_true", help="任一失败即非零退出")
    ap.add_argument("--email", default="", help="NCBI 建议的联络邮箱")
    args = ap.parse_args()

    home = Path(args.home).expanduser()
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else home / "data"
    refs_dir = Path(args.refs_dir).expanduser() if args.refs_dir else home / "refs"
    out_dir = data_dir / "reference" / "genomes"

    if args.verify:
        cmd = [
            sys.executable,
            str(_VERIFY),
            "--manifest",
            args.manifest,
        ]
        if args.email:
            cmd += ["--email", args.email]
        if args.strict:
            cmd.append("--strict")
        if subprocess.call(cmd) != 0 and args.strict:
            return 1

    cmd = [
        sys.executable,
        str(_FETCH),
        "--manifest",
        args.manifest,
        "--out-dir",
        str(out_dir),
        "--refs-dir",
        str(refs_dir),
    ]
    if args.only:
        cmd += ["--only", args.only]
    if args.force:
        cmd.append("--force")
    if args.strict:
        cmd.append("--strict")
    if args.email:
        cmd += ["--email", args.email]

    print(f"→ {out_dir}", file=sys.stderr)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
