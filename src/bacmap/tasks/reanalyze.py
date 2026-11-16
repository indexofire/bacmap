"""partial reanalyze（v1.10.39）：在既有 run 上补跑指定 stage。

不原地修改 base run：新 task 目录先 hardlink / copy 快照，只删除选中 stage 与
summary/report，再用 Snakemake 只重建这些目标。旧 run 保持不可变，成功后
``link_run_results`` 才把 `<sample>` 别名切到新 run。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from bacmap.core.pipeline.stages import StageSpec, get_stage
from bacmap.store import runs as runs_store
from bacmap.store.results_layout import run_results_dir


class ReanalyzeError(ValueError):
    """base run / 快照不满足补跑条件。"""


def _task_state(home: Path, task_id: str) -> str | None:
    db = home / "tasks.sqlite"
    if not db.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def resolve_base_run(home: Path, samples: list[str], base_run_id: str = "") -> dict[str, Any]:
    """解析 base run；省略 ID 时要求所有样本共享最近一次成功 run。"""
    db = home / "runs.sqlite"
    wanted = set(samples)
    if base_run_id:
        run = runs_store.read_run(base_run_id, db)
        if run is None:
            raise ReanalyzeError(f"base run not found: {base_run_id}")
        if not wanted.issubset(set(run.strain_ids)):
            raise ReanalyzeError("base run does not contain all requested samples")
        candidates = [run.model_dump(mode="json")]
    else:
        candidates = [
            row for row in runs_store.list_runs(db, limit=100_000)
            if wanted.issubset(set(row["strain_ids"]))
        ]
    for row in candidates:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        state = _task_state(home, task_id)
        if state not in (None, "succeeded", "awaiting_approval"):
            continue
        directory = run_results_dir(home, task_id)
        if not directory.is_dir():
            continue
        if all((directory / sample).is_dir() for sample in samples):
            return {
                "run_id": str(row["run_id"]),
                "task_id": task_id,
                "run_dir": directory,
            }
    raise ReanalyzeError(
        "no successful base run contains all requested samples; pass --base-run explicitly"
    )


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _snapshot_tree(source: Path, target: Path) -> None:
    for root, dirs, files in os.walk(source):
        current = Path(root)
        relative = current.relative_to(source)
        if relative.parts and relative.parts[0] == ".snakemake":
            dirs[:] = []
            continue
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in files:
            src = current / name
            dst = destination / name
            if dst.exists():
                continue
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            else:
                _link_or_copy(src, dst)


def snapshot_run(base_run_dir: Path, target: Path) -> None:
    """hardlink 快照；跨文件系统回退 copy。目标必须是空/新建目录。"""
    if target.exists() and any(target.iterdir()):
        raise ReanalyzeError(f"target run directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    _snapshot_tree(base_run_dir, target)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def prepare_reanalysis(
    home: Path,
    samples: list[str],
    steps: list[str],
    task_id: str,
    base_run_id: str = "",
) -> dict[str, Any]:
    """快照 base run 并删除选中阶段/summary/report；返回 base 与新目录。"""
    stages: list[StageSpec] = [get_stage(step) for step in steps]
    base = resolve_base_run(home, samples, base_run_id)
    target = run_results_dir(home, task_id)
    snapshot_run(base["run_dir"], target)
    # 预检 marker 属于 base run 的样本集合，不能带给新任务。
    _remove(target / ".database_preflight.json")
    for sample in samples:
        for stage in stages:
            for relative in stage.removals_for(sample, str(target)):
                _remove(Path(relative))
        # summary/report 必须重算；其余硬链接保持原样。
        _remove(target / sample / "report" / f"{sample}_summary.json")
        _remove(target / sample / "report" / f"{sample}_summary.prelim.json")
        _remove(target / sample / "report" / f"{sample}_report.html")
    return {"base": base, "run_dir": target, "stages": [stage.name for stage in stages]}


def reanalysis_targets(run_dir: Path, samples: list[str], steps: list[str]) -> list[str]:
    stages = [get_stage(step) for step in steps]
    targets: list[str] = []
    for sample in samples:
        for stage in stages:
            targets.extend(stage.targets_for(sample, str(run_dir)))
        targets.append(str(run_dir / sample / "report" / f"{sample}_summary.json"))
    return targets
