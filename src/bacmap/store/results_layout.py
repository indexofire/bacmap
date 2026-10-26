"""run 级结果目录（v1.8.1，P2 方案 A）。

物理布局：``results/runs/<task_id>/<sample>/...``（一次执行的全部产物，永不覆盖）。
兼容别名：``results/<sample>``、``results/snp``、``results/cgmlst`` 指向**最新一次运行**的
相对符号链接——读方（视图、工具、报告脚本、测试夹具）无需改路径即可透明获得"最新结果"，
而历史运行仍完整保留在 runs/<task_id>/ 下。

旧扁平目录用 ``migrate_flat_results`` 搬入 ``runs/legacy-<sample>/`` 后立即替换为符号链接
（不保留第二份数据）。
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

RUNS_DIRNAME = "runs"
COHORT_DIRS = ("snp", "cgmlst")


def results_root(home: Path | str) -> Path:
    return Path(home) / "results"


def run_results_dir(home: Path | str, task_id: str) -> Path:
    return results_root(home) / RUNS_DIRNAME / task_id


def _relative_target(link: Path, target: Path) -> str:
    return os.path.relpath(target, start=link.parent)


def _link(link: Path, target: Path) -> None:
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        raise RuntimeError(
            f"refusing to replace real directory {link}; run `bacmap results migrate` first"
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(_relative_target(link, target), target_is_directory=True)


def link_run_results(home: Path | str, task_id: str, samples: Iterable[str]) -> None:
    """把扁平别名指向本次运行：每个样本一条，外加队列目录 snp/cgmlst（若存在）。"""
    home = Path(home)
    rd = run_results_dir(home, task_id)
    root = results_root(home)
    for sample in samples:
        if (rd / sample).is_dir():
            _link(root / sample, rd / sample)
    for name in COHORT_DIRS:
        if (rd / name).is_dir():
            _link(root / name, rd / name)


def _flat_sample_dirs(home: Path) -> list[Path]:
    root = results_root(home)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.name in (RUNS_DIRNAME, *COHORT_DIRS):
            continue
        if p.is_dir() and not p.is_symlink():
            out.append(p)
    return out


def flat_result_samples(home: Path | str) -> list[str]:
    """尚未迁移的旧扁平样本目录名（供 dry-run / doctor 使用）。"""
    return [p.name for p in _flat_sample_dirs(Path(home))]


def migrate_flat_results(home: Path | str) -> int:
    """旧扁平 ``results/<sample>/`` → ``runs/legacy-<sample>/<sample>/`` 并替换为链接。"""
    home = Path(home)
    moved = 0
    for flat in _flat_sample_dirs(home):
        target_root = run_results_dir(home, f"legacy-{flat.name}")
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / flat.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(flat), str(target))
        _link(flat, target)
        moved += 1
    # 队列目录若为旧扁平实体（非链接），保持原样（跨运行聚合语义），迁移不处理。
    return moved
