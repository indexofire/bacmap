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
    """把扁平别名指向本次运行：每个样本一条，外加队列目录 snp/cgmlst（若存在）。

    升级后首次运行若仍有旧扁平实体目录，先就地迁移为链接（v1.9.2）：否则
    ``_link`` 会拒绝覆盖真实目录，导致**分析已成功却把任务标成失败**；旧数据
    迁入 ``runs/legacy-*`` 后仍完整保留，绝不删除。
    """
    home = Path(home)
    if _flat_result_dirs(home):
        migrate_flat_results(home)
    rd = run_results_dir(home, task_id)
    root = results_root(home)
    for sample in samples:
        if (rd / sample).is_dir():
            _link(root / sample, rd / sample)
    for name in COHORT_DIRS:
        if (rd / name).is_dir():
            _link(root / name, rd / name)


def _flat_result_dirs(home: Path) -> list[Path]:
    """旧布局下仍是真实目录的扁平项（样本目录与 snp/cgmlst 队列目录）。

    v1.8.1 之前 ``results/snp``、``results/cgmlst`` 也是真实目录；若不迁移，
    新运行建立最新别名时会撞上 ``_link`` 的"拒绝覆盖真实目录"保护。
    """
    root = results_root(home)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.name == RUNS_DIRNAME:
            continue
        if p.is_dir() and not p.is_symlink():
            out.append(p)
    return out


def flat_result_samples(home: Path | str) -> list[str]:
    """尚未迁移的旧扁平结果目录名（样本 + snp/cgmlst；供 dry-run / doctor 使用）。"""
    return [p.name for p in _flat_result_dirs(Path(home))]


def migrate_flat_results(home: Path | str) -> int:
    """旧扁平 ``results/<name>/`` → ``runs/legacy-<name>/<name>/`` 并替换为链接。"""
    home = Path(home)
    moved = 0
    for flat in _flat_result_dirs(home):
        base = run_results_dir(home, f"legacy-{flat.name}")
        target_root, n = base, 2
        while (target_root / flat.name).exists():
            target_root = base.with_name(f"{base.name}-{n}")
            n += 1
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / flat.name
        shutil.move(str(flat), str(target))
        _link(flat, target)
        moved += 1
    return moved
