"""`bacmap start web -D/--daemon` 守护进程模式（v1.10.19）。

只测纯逻辑与 CLI 面（fork/uvicorn 的 e2e 由真实启动冒烟覆盖）：
- `_pid_alive`：存活/不存在/无权限三分支
- argparse：-D/--daemon 开关存在且置位
- 已运行检测：PID 文件存活 → SystemExit；陈旧 → 放行
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from bacmap.interfaces.cli.main import _pid_alive, _run_web


class TestPidAlive:
    def test_self_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_missing_pid_dead(self):
        assert _pid_alive(999_999_999) is False


class TestDaemonFlag:
    def test_flag_parses_and_sets_true(self):
        from bacmap.interfaces.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["start", "web", "-D"])
        assert args.daemon is True
        args_long = parser.parse_args(["start", "web", "--daemon"])
        assert args_long.daemon is True

    def test_default_foreground(self):
        from bacmap.interfaces.cli.main import build_parser

        args = build_parser().parse_args(["start", "web"])
        assert args.daemon is False


class TestAlreadyRunningGuard:
    def _args(self, tmp_path: Path) -> argparse.Namespace:
        return argparse.Namespace(
            daemon=True,
            host="127.0.0.1",
            port=18899,
            home=str(tmp_path),
            token_env="BACMAP_WEB_TOKEN",
        )

    def test_live_pidfile_refuses_to_start(self, tmp_path):
        (tmp_path / "web.pid").write_text(f"{os.getpid()}\n")  # 本测试进程 = 存活
        with pytest.raises(SystemExit, match="already running"):
            _run_web(self._args(tmp_path))

    def test_stale_pidfile_proceeds(self, tmp_path, monkeypatch):
        (tmp_path / "web.pid").write_text("999999999\n")  # 不存在的 PID
        monkeypatch.setattr(
            "bacmap.interfaces.cli.main._daemonize",
            lambda log, pid: (_ for _ in ()).throw(SystemExit(0)),  # 到 fork 即止
        )
        with pytest.raises(SystemExit):
            _run_web(self._args(tmp_path))
        # 陈旧 PID 文件被放行后仍保留（由新 daemon 覆盖）
        assert (tmp_path / "web.pid").exists()
