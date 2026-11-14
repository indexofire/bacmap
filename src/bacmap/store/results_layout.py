"""run 级结果目录（v1.8.1，P2 方案 A）。

物理布局：``results/runs/<task_id>/<sample>/...``（一次执行的全部产物，永不覆盖）。
兼容别名：``results/<sample>``、``results/snp``、``results/cgmlst`` 指向**最新一次运行**的
相对符号链接——读方（视图、工具、报告脚本、测试夹具）无需改路径即可透明获得"最新结果"，
而历史运行仍完整保留在 runs/<task_id>/ 下。

旧扁平目录用 ``migrate_flat_results`` 搬入 ``runs/legacy-<sample>/`` 后立即替换为符号链接
（不保留第二份数据）。
"""

from __future__ import annotations

import gzip
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

RUNS_DIRNAME = "runs"
COHORT_DIRS = ("snp", "cgmlst")

# ---------------------------------------------------------------------------
# 冷产物压缩（v1.10.20）：run 结束后无人再读的大文件 → gzip；需要时展开。
# 实测单株 ~89MB 中 ~85MB 是 Bakta 导出（embl/gbff/gff3/ffn/fna/faa）、合并
# annotation.json 与 eggNOG 中间表——全部只被管线在运行期消费。Web/报告/GOM
# 热路径只读 summary.json、gspec/*.json、report.html、mlst/species/quast tsv。
# -----------------------------------------------------------------------------

#: 冷目录：整个子目录 gzip（文件级，保留目录结构）
_COLD_DIRS = ("annotation/bakta", "annotation/eggnog")
#: 冷文件（相对样本目录）
_COLD_FILES = ("annotation/annotation.json",)
#: quast 中保留明文的两个小表（人类可读 + 备用核对）
_QUAST_KEEP = {"report.tsv", "transposed_report.tsv"}


def _gzip_file(path: Path) -> int:
    """单文件 → path.gz（原文件删除）；返回释放字节数。已是 .gz 或缺失则 0。

    先写 .tmp 再 ``os.replace``——进程中断不留下半截 .gz（此前实测到
    压缩中崩溃后恢复任务读到损坏产物）。
    """
    if path.suffix == ".gz" or not path.is_file():
        return 0
    gz = path.with_suffix(path.suffix + ".gz")
    tmp = gz.with_name(gz.name + ".tmp")
    try:
        with open(path, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, gz)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    size = path.stat().st_size
    path.unlink()
    return size


def _gunzip_file(path: Path) -> bool:
    if path.suffix != ".gz" or not path.is_file():
        return False
    out = path.with_suffix("")
    tmp = out.with_name(out.name + ".tmp")
    try:
        with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    path.unlink()
    return True


def compact_run_artifacts(run_dir: Path | str, samples: Iterable[str] | None = None) -> dict:
    """把 run 目录中的冷产物 gzip 压缩（幂等；返回 {files, bytes_saved, samples}）。

    热路径文件不动：summary/report/gspec/typing/species/amr/contigs 与
    quast 的 report.tsv / transposed_report.tsv。需要原始文件时用
    :func:`expand_run_artifacts` 展开或手工 ``gunzip``。
    """
    run_dir = Path(run_dir)
    names = list(samples) if samples else [p.name for p in run_dir.iterdir() if p.is_dir()]
    files = 0
    saved = 0
    for sample in names:
        base = run_dir / sample
        if not base.is_dir():
            continue
        cold: list[Path] = []
        for rel in _COLD_DIRS:
            sub = base / rel
            if sub.is_dir():
                cold.extend(p for p in sub.rglob("*") if p.is_file())
        for rel in _COLD_FILES:
            p = base / rel
            if p.is_file():
                cold.append(p)
        quast = base / "assembly" / "quast"
        if quast.is_dir():
            cold.extend(
                p for p in quast.rglob("*") if p.is_file() and p.name not in _QUAST_KEEP
            )
        for path in cold:
            freed = _gzip_file(path)
            if freed:
                files += 1
                saved += freed
    return {"files": files, "bytes_saved": saved, "samples": names}


def repair_flat_aliases(home: Path | str) -> dict:
    """v1.10.24 别名自愈：把指向"无最终报告 run"的样本别名重指到最新完整 run。

    场景（实测）：被取消的批次在 prelim 阶段成功时抢占了扁平别名，随后
    中断——别名从此指向无报告的残缺 run，控制台"完整报告"按钮消失、
    报告 iframe 404。规则：别名指向的 run 缺 `<sample>_report.html` 时，
    按 mtime 找**最新含最终报告** 的 run 重指；没有完整 run 时保持
    原状（至少 prelim 可见）。
    """
    home = Path(home)
    runs_root = results_root(home) / RUNS_DIRNAME
    if not runs_root.is_dir():
        return {"repaired": 0}
    # 每个 run 目录的修改时间（最终 summary 写入时间）作排序键
    run_dirs = sorted(
        (p for p in runs_root.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    repaired = 0
    for link in results_root(home).iterdir():
        if link.name in COHORT_DIRS or not link.is_symlink():
            continue
        sample = link.name
        target = link.resolve()
        if (target / "report" / f"{sample}_report.html").is_file():
            continue  # 指向的 run 已有完整报告——无需修复
        for run in run_dirs:
            candidate = run / sample
            if (candidate / "report" / f"{sample}_report.html").is_file():
                _link(link, candidate)
                repaired += 1
                break
    return {"repaired": repaired}


def expand_run_artifacts(run_dir: Path | str, samples: Iterable[str] | None = None) -> int:
    """展开 compact 压缩的冷产物（幂等；返回展开文件数）。

    展开范围与压缩范围严格对称（冷目录 + annotation.json.gz + quast）：
    不能整树扫 ``*.gz``——assembly/ 下可能存在管线原生的 .gz 产物
    （如 Flye/Unicycler 导出的 .fasta.gz），误解压会破坏产物。
    """
    run_dir = Path(run_dir)
    names = list(samples) if samples else [p.name for p in run_dir.iterdir() if p.is_dir()]
    count = 0
    for sample in names:
        base = run_dir / sample
        if not base.is_dir():
            continue
        cold: list[Path] = []
        for rel in _COLD_DIRS:
            sub = base / rel
            if sub.is_dir():
                cold.extend(sub.rglob("*.gz"))
        ann = base / "annotation" / "annotation.json.gz"
        if ann.is_file():
            cold.append(ann)
        quast = base / "assembly" / "quast"
        if quast.is_dir():
            cold.extend(quast.rglob("*.gz"))
        for p in cold:
            count += _gunzip_file(p)
    return count


def results_root(home: Path | str) -> Path:
    return Path(home) / "results"


def run_results_dir(home: Path | str, task_id: str) -> Path:
    return results_root(home) / RUNS_DIRNAME / task_id


def _relative_target(link: Path, target: Path) -> str:
    return os.path.relpath(target, start=link.parent)


def _link(link: Path, target: Path) -> None:
    if link.exists() and not link.is_symlink():
        raise RuntimeError(
            f"refusing to replace real directory {link}; run `bacmap results migrate` first"
        )
    link.parent.mkdir(parents=True, exist_ok=True)
    # 同目录临时链接 + os.replace 原子切换：读者要么命中旧链要么命中新链，
    # 不存在 unlink→symlink_to 窗口期的 ENOENT（流式两阶段重链时并发读实测触发）。
    tmp = link.with_name(f".{link.name}.link-tmp")
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(_relative_target(link, target), target_is_directory=True)
    os.replace(tmp, link)


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
