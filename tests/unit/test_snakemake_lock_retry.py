"""snakemake 目录锁的退避重试（v1.4.39）：并发 analyze 不因 LockException 直接失败。"""

from __future__ import annotations

from types import SimpleNamespace

import bacmap.tasks.engine.dbos_engine as eng


class _FakeRunner:
    def __init__(self, results: list) -> None:
        self._results = iter(results)
        self.calls = 0

    def run(self, targets=None, cores=None, config_overrides=None, timeout=None):
        self.calls += 1
        return next(self._results)


def _proc(rc: int, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout="", stderr=stderr)


class TestSnakemakeLockRetry:
    def test_lock_then_success_retries(self, tmp_path, monkeypatch):
        """v1.10.23 两阶段：prelim 撞锁→清锁重试成功；final 直接成功。"""
        runner = _FakeRunner(
            [
                _proc(1, "LockException: Directory cannot be locked"),
                _proc(0),
                _proc(0),
            ]
        )
        # _run_snakemake 函数内 from bacmap.workflow.runner import ...：patch 源模块
        monkeypatch.setattr("bacmap.workflow.runner.WorkflowRunner", lambda **kw: runner)
        monkeypatch.setattr("bacmap.workflow.runner.deploy", lambda: tmp_path)
        monkeypatch.setattr("time.sleep", lambda s: None)
        monkeypatch.setattr(eng, "_clear_stale_snakemake_locks", lambda home: False)
        monkeypatch.setattr(
            "bacmap.store.results_layout.link_run_results", lambda *a, **k: None
        )
        result = eng._run_snakemake({"home": str(tmp_path), "samples": ["S1"], "task_id": "t1"})
        assert result.returncode == 0
        assert runner.calls == 3  # prelim：锁一次+成功一次；final：成功一次

    def test_non_lock_error_fails_fast(self, tmp_path, monkeypatch):
        """v1.10.23 两阶段：prelim 非锁失败不重试、不阻断；final 的结果定成败。"""
        runner = _FakeRunner([_proc(1, "Error: rule qc_fastp failed"), _proc(0)])
        monkeypatch.setattr("bacmap.workflow.runner.WorkflowRunner", lambda **kw: runner)
        monkeypatch.setattr("bacmap.workflow.runner.deploy", lambda: tmp_path)
        monkeypatch.setattr(
            "bacmap.store.results_layout.link_run_results", lambda *a, **k: None
        )
        result = eng._run_snakemake({"home": str(tmp_path), "samples": ["S1"], "task_id": "t1"})
        assert result.returncode == 0  # prelim 失败被容忍，final 成功
        assert runner.calls == 2  # 非锁错误不重试（各阶段各一次）
