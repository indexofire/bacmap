"""DEC 致病型判定（gapit `ecoli_dec`，ADR-20：bacmap 只编排 + 适配）。

调 `gapit screen --db ecoli_dec` + `gapit typing -f json`，把
``gapit.typing_result/1`` 原样写入 `--out`（供报告与运行记录溯源）。

**gapit 缺失不静默**：写 `status="skipped"` + reason；screen/typing 失败写
`status="failed"` + stage/error。判定失败不影响其余步骤（`pathotype` 归一为 N/A）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def run(contigs: Path, out: Path, workdir: Path, *, db: str, timeout: int) -> int:
    gapit = shutil.which("gapit")
    if gapit is None:
        out.write_text(
            json.dumps(
                {"status": "skipped", "reason": "gapit not found in PATH", "db": db},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    screen = workdir / f"{db}_screen.tsv"
    screen_proc = subprocess.run(
        [gapit, "screen", str(contigs), "--db", db, "-o", str(screen)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if screen_proc.returncode != 0 or not screen.is_file():
        out.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "stage": "screen",
                    "db": db,
                    "error": (screen_proc.stderr or "")[-500:],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    typing_proc = subprocess.run(
        [gapit, "typing", str(screen), "-f", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if typing_proc.returncode != 0:
        out.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "stage": "typing",
                    "db": db,
                    "error": (typing_proc.stderr or "")[-500:],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0
    try:
        payload = json.loads(typing_proc.stdout)
    except ValueError:
        out.write_text(
            json.dumps(
                {"status": "failed", "stage": "typing", "db": db, "error": "non-JSON output"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    if isinstance(payload, dict):
        payload["status"] = "ran"
        payload["screen_tsv"] = str(screen)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="DEC pathotype via gapit ecoli_dec")
    ap.add_argument("--contigs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--db", default="ecoli_dec")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    return run(
        Path(args.contigs),
        Path(args.out),
        Path(args.workdir),
        db=args.db,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
