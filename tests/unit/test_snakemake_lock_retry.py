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
        runner = _FakeRunner(
            [
                _proc(1, "LockException: Directory cannot be locked"),
                _proc(0),
            ]
        )
        # _run_snakemake 函数内 from bacmap.workflow.runner import ...：patch 源模块
        monkeypatch.setattr("bacmap.workflow.runner.WorkflowRunner", lambda **kw: runner)
        monkeypatch.setattr("bacmap.workflow.runner.deploy", lambda: tmp_path)
        monkeypatch.setattr("time.sleep", lambda s: None)
        result = eng._run_snakemake({"home": str(tmp_path), "samples": ["S1"]})
        assert result.returncode == 0
        assert runner.calls == 2  # 锁一次 + 成功一次

    def test_non_lock_error_fails_fast(self, tmp_path, monkeypatch):
        runner = _FakeRunner([_proc(1, "Error: rule qc_fastp failed")])
        monkeypatch.setattr("bacmap.workflow.runner.WorkflowRunner", lambda **kw: runner)
        monkeypatch.setattr("bacmap.workflow.runner.deploy", lambda: tmp_path)
        result = eng._run_snakemake({"home": str(tmp_path), "samples": ["S1"]})
        assert result.returncode == 1
        assert runner.calls == 1  # 非锁错误不重试
