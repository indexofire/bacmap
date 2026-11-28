"""管线步级实时产物监听（StepWatcher）。

动机：Snakemake 以整包阻塞方式运行，物种鉴定/MLST/耐药等快步骤几分钟内就落盘，
但用户此前要等整条管线结束才能在 Web 看到任何结果。本模块在引擎执行
``runner.run()`` 期间用一个 daemon 线程轮询 run 目录的产物文件，每发现一个
**新且稳定**的产物就写一条富化的 ``task.step`` 事件（payload 含 sample 与
轻量结果摘要），前端经 SSE 渐进渲染结果卡片。

设计约束：

- 事件是观察、不是真相：解析失败/丢失只影响展示，绝不影响分析本身；
  所有异常吞掉并告警日志。
- ``bacmap.workflow`` 不能导入 tasks（ADR-02），故解析器在
  ``bacmap.workflow.progress``（纯函数），事件写入在本模块（tasks 层）。
- 幂等以"首次发现"为准：同一 (step, subject) 在一次任务内只推一次；
  引擎重启重放时重复推送是可接受的观察噪声（客户端按 step 覆盖式合并）。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from bacmap.workflow.progress import parse_step_result

logger = logging.getLogger(__name__)

# (step_key, 中文标签, run_dir 相对 glob，作用域)
# <sample> 占位符按任务样本展开；cgmlst 为 cohort 级。
STEP_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("species", "物种鉴定", "{sample}/species/species_id.json", "sample"),
    ("assembly", "组装质控", "{sample}/assembly/assembly_stats.tsv", "sample"),
    ("mlst", "MLST 分型", "{sample}/typing/mlst.json", "sample"),
    ("serotype", "血清型/基因型", "{sample}/gspec/typing.json", "sample"),
    ("amr", "耐药检测", "{sample}/amr/amrfinderplus.tsv", "sample"),
    ("vfdb", "毒力基因筛查", "{sample}/gspec/vfdb.json", "sample"),
    ("card", "耐药基因筛查", "{sample}/gspec/card.json", "sample"),
    ("plasmid", "质粒筛查", "{sample}/gspec/plasmidfinder.json", "sample"),
    ("prelim_summary", "初步汇总", "{sample}/report/{sample}_summary.prelim.json", "sample"),
    ("final_summary", "最终汇总", "{sample}/report/{sample}_summary.json", "sample"),
    ("report", "完整报告", "{sample}/report/{sample}_report.html", "sample"),
    ("cgmlst", "cgMLST 队列", "cgmlst/*/cgmlst_summary.json", "cohort"),
)

STEP_LABELS: dict[str, str] = {key: label for key, label, _, _ in STEP_SPECS}


class StepWatcher:
    """run 目录产物轮询器：发现新稳定产物即写步级结果事件。"""

    def __init__(
        self,
        home: Path,
        task_id: str,
        run_dir: Path,
        samples: list[str] | tuple[str, ...],
        interval: float = 1.5,
        since: float | None = None,
    ) -> None:
        self._home = Path(home)
        self._task_id = str(task_id or "")
        self._run_dir = Path(run_dir)
        self._samples = [str(s) for s in samples]
        self._interval = max(0.1, float(interval))
        # 只发射该时间之后写入的产物（epoch 秒；None=不限制）。
        # reanalyze 复用同一 run 目录：原始运行的旧产物不应重推，
        # 只有本次真正重跑再生的产物（新 mtime）才发事件。
        self._since = since
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # (step, subject) 首次发现去重；path → (size, mtime_ns) 稳定性签名
        self._seen: set[tuple[str, str]] = set()
        self._signatures: dict[Path, tuple[int, int]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._task_id) and (self._home / "tasks.sqlite").is_file()

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop,
            name=f"step-watch-{self._task_id[:10]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止轮询并做最后一次扫描（收尾产物大多已完整写盘）。"""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            self._thread = None
        if self.enabled:
            try:
                self.scan(force=True)
            except Exception:
                logger.warning("step watcher final scan failed", exc_info=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception:
                logger.warning("step watcher scan failed", exc_info=True)
            self._stop.wait(self._interval)

    def scan(self, force: bool = False) -> int:
        """扫描一轮产物；``force=True`` 跳过稳定性等待（收尾用）。返回新事件数。"""
        emitted = 0
        for key, _label, pattern, scope in STEP_SPECS:
            if scope == "sample":
                for sample in self._samples:
                    path = self._run_dir / pattern.format(sample=sample)
                    emitted += self._check(key, sample, path, force)
            else:
                if not self._run_dir.is_dir():
                    continue
                for path in sorted(self._run_dir.glob(pattern)):
                    subject = path.parent.name  # cgmlst/<group>/cgmlst_summary.json
                    emitted += self._check(key, subject, path, force)
        return emitted

    def _check(self, key: str, subject: str, path: Path, force: bool) -> int:
        if (key, subject) in self._seen or not path.is_file():
            return 0
        try:
            stat = path.stat()
        except OSError:
            return 0
        if stat.st_size == 0:
            return 0  # 空文件多为写入中途，等下一轮
        if self._since is not None and stat.st_mtime < self._since - 1:
            self._seen.add((key, subject))  # 旧产物直接标记，避免每轮重复 stat 判断
            return 0
        signature = (stat.st_size, stat.st_mtime_ns)
        # 稳定性：同一文件连续两轮签名不变才认为写完（避免半截 JSON/TSV）。
        if not force and self._signatures.get(path) != signature:
            self._signatures[path] = signature
            return 0
        self._seen.add((key, subject))
        self._emit(key, subject, path)
        return 1

    def _emit(self, key: str, subject: str, path: Path) -> None:
        result = parse_step_result(key, path)
        try:
            artifact = str(path.relative_to(self._run_dir))
        except ValueError:
            artifact = path.name
        try:
            from bacmap.tasks.engine._progress import record_step_result

            record_step_result(
                self._home,
                self._task_id,
                key,
                subject=subject,
                result=result,
                artifact=artifact,
                notify=key in {"prelim_summary", "final_summary"},
            )
        except Exception:
            logger.warning(
                "record_step_result failed for %s/%s/%s", self._task_id, key, subject,
                exc_info=True,
            )
