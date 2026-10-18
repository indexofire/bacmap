"""重组检测（Gubbins，ADR-20：bacmap 只编排 + 适配）。

对某 cohort 的 core SNP 比对跑 `run_gubbins.py`，产出重组预测（GFF）与
重组剔除后的比对/树；把摘要写成 JSON 供报告与运行记录消费。

**工具缺失不静默**：`run_gubbins.py` 不在 PATH 时写 `status="skipped"` +
`reason`（判定不受影响），规则仍产出 `--out`。

用法：
    python run_recombination.py --alignment core_snps.fasta --out recombination.json \
        --workdir <gubbins 输出目录> [--threads 4] [--seed 42] [--timeout 3600]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_GUBBINS = "run_gubbins.py"


def _gubbins_version(runner: str) -> str:
    try:
        proc = subprocess.run(
            [runner, "--version"], capture_output=True, text=True, timeout=60
        )
        return (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.stdout or proc.stderr else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _count_predictions(gff: Path) -> int:
    """GFF 中非注释行的数量 = 预测的重组区块数。"""
    if not gff.is_file():
        return 0
    n = 0
    for line in gff.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip() and not line.startswith("#"):
            n += 1
    return n


def run(alignment: Path, out: Path, workdir: Path, *, threads: int, seed: int, timeout: int) -> int:
    runner = shutil.which(_GUBBINS) or shutil.which("gubbins")
    if runner is None:
        out.write_text(
            json.dumps(
                {
                    "tool": "gubbins",
                    "status": "skipped",
                    "reason": f"{_GUBBINS} not found in PATH（安装：pixi run -e recomb gubbins）",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    workdir.mkdir(parents=True, exist_ok=True)
    prefix = workdir / "gubbins"
    cmd = [
        runner,
        str(alignment),
        "--prefix",
        str(prefix),
        "--threads",
        str(threads),
        "--seed",
        str(seed),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        out.write_text(
            json.dumps(
                {"tool": "gubbins", "status": "failed", "error": f"timeout after {timeout}s"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0

    gff = Path(f"{prefix}.recombination_predictions.gff")
    tree = Path(f"{prefix}.node_labelled.final_tree.tre")
    payload = {
        "tool": "gubbins",
        "version": _gubbins_version(runner),
        "status": "ran" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "n_recombinations": _count_predictions(gff),
        "recombination_predictions": str(gff) if gff.is_file() else None,
        "final_tree": str(tree) if tree.is_file() else None,
    }
    if proc.returncode != 0:
        payload["error"] = (proc.stderr or "").strip()[-500:]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Recombination detection via Gubbins")
    ap.add_argument("--alignment", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()
    return run(
        Path(args.alignment),
        Path(args.out),
        Path(args.workdir),
        threads=args.threads,
        seed=args.seed,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
