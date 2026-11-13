"""`bacmap start web -D/--daemon` 守护进程模式（v1.10.19）。

只测纯逻辑与 CLI 面（fork/uvicorn 的 e2e 由真实启动冒烟覆盖）：
- `_pid_alive`：存活/不存在/无权限三分支
- argparse：-D/--daemon 开关存在且置位
- 已运行检测：PID 文件存活 → SystemExit；陈旧 → 放行
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
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


class TestStopCommand:
    def test_stop_when_not_running(self, tmp_path, capsys):
        from bacmap.interfaces.cli.main import _stop_web_daemon

        assert _stop_web_daemon(tmp_path, timeout=1) == 0
        assert "bacmap web" in capsys.readouterr().out

    def test_stop_removes_stale_pidfile(self, tmp_path):
        from bacmap.interfaces.cli.main import _stop_web_daemon

        pidfile = tmp_path / "web.pid"
        pidfile.write_text("999999999\n")
        assert _stop_web_daemon(tmp_path, timeout=1) == 0
        assert not pidfile.exists()

    def test_stop_terminates_running_process(self, tmp_path):
        from bacmap.interfaces.cli.main import _stop_web_daemon

        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            (tmp_path / "web.pid").write_text(f"{proc.pid}\n")
            assert _stop_web_daemon(tmp_path, timeout=5) == 0
            proc.wait(timeout=5)
            assert proc.returncode is not None
            assert not (tmp_path / "web.pid").exists()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


class TestDaemonDiscovery:
    """pidfile 随数据目录被删的场景：按 /proc 发现并停止旧守护进程。"""

    def _spawn_fake(self, home: Path, argv: list[str] | None = None) -> subprocess.Popen:
        """伪造与真实守护同形的 cmdline：python <.../bin/bacmap> start web -D。"""
        script = home.parent / "fakebin" / "bacmap"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        return subprocess.Popen(
            [sys.executable, str(script)]
            + (argv if argv is not None else ["start", "web", "-D"])
            + ["--home", str(home)]
        )

    def test_finds_daemon_without_pidfile(self, tmp_path):
        from bacmap.interfaces.cli.main import _web_daemon_pids

        proc = self._spawn_fake(tmp_path)
        try:
            assert proc.pid in _web_daemon_pids(tmp_path)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_finds_restart_spawned_daemon(self, tmp_path):
        from bacmap.interfaces.cli.main import _web_daemon_pids

        proc = self._spawn_fake(tmp_path, ["restart"])
        try:
            assert proc.pid in _web_daemon_pids(tmp_path)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_ignores_wrapper_without_bacmap_script(self, tmp_path):
        """pixi/bash 包装进程（argv 词元相同但不是控制台脚本）不得误报。"""
        import subprocess
        import sys

        from bacmap.interfaces.cli.main import _web_daemon_pids

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)", "bacmap", "start", "web",
             "--home", str(tmp_path)]
        )
        try:
            assert proc.pid not in _web_daemon_pids(tmp_path)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_stop_kills_pidfileless_daemon(self, tmp_path):
        from bacmap.interfaces.cli.main import _stop_web_daemon

        proc = self._spawn_fake(tmp_path)
        try:
            assert _stop_web_daemon(tmp_path, timeout=5) == 0
            proc.wait(timeout=5)
            assert proc.returncode is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_port_in_use_detects_listener(self):
        import socket

        from bacmap.interfaces.cli.main import _port_in_use

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = server.getsockname()[1]
            assert _port_in_use("127.0.0.1", port) is True
        finally:
            server.close()
        assert _port_in_use("127.0.0.1", port) is False

    def test_start_refuses_when_port_busy(self, tmp_path):
        import socket

        from bacmap.interfaces.cli.main import _run_web

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = server.getsockname()[1]
            args = argparse.Namespace(
                daemon=True,
                host="127.0.0.1",
                port=port,
                home=str(tmp_path),
                token_env="BACMAP_WEB_TOKEN",
            )
            with pytest.raises(SystemExit, match="already in use"):
                _run_web(args)
        finally:
            server.close()

    def test_start_refuses_when_orphan_daemon_running(self, tmp_path):
        from bacmap.interfaces.cli.main import _run_web

        proc = self._spawn_fake(tmp_path)
        try:
            args = argparse.Namespace(
                daemon=True,
                host="127.0.0.1",
                port=18898,
                home=str(tmp_path),
                token_env="BACMAP_WEB_TOKEN",
            )
            with pytest.raises(SystemExit, match="pidfile is missing"):
                _run_web(args)
        finally:
            proc.kill()
            proc.wait(timeout=5)


class TestRestartCommand:
    def _args(self, tmp_path: Path, **overrides) -> argparse.Namespace:
        base = dict(host="", port=0, token_env="", home=str(tmp_path), timeout=1.0)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_daemon_state_roundtrip(self, tmp_path):
        from bacmap.interfaces.cli.main import _load_daemon_state, _save_daemon_state

        _save_daemon_state(
            tmp_path,
            argparse.Namespace(host="192.0.2.10", port=8899, token_env="MY_TOKEN"),
        )
        state = _load_daemon_state(tmp_path)
        assert state == {"host": "192.0.2.10", "port": 8899, "token_env": "MY_TOKEN"}

    def test_missing_state_is_empty(self, tmp_path):
        from bacmap.interfaces.cli.main import _load_daemon_state

        assert _load_daemon_state(tmp_path) == {}

    def test_restart_reuses_saved_options(self, tmp_path, monkeypatch):
        from bacmap.interfaces.cli import main as cli

        calls: list[dict] = []
        monkeypatch.setattr(cli, "_stop_web_daemon", lambda home, timeout: 0)
        monkeypatch.setattr(cli, "_run_web", lambda ns: calls.append(vars(ns)))
        cli._save_daemon_state(
            tmp_path,
            argparse.Namespace(host="192.0.2.10", port=8899, token_env="SAVED_TOKEN"),
        )
        cli._run_restart(self._args(tmp_path))
        assert calls and calls[0]["host"] == "192.0.2.10"
        assert calls[0]["port"] == 8899
        assert calls[0]["token_env"] == "SAVED_TOKEN"
        assert calls[0]["daemon"] is True

    def test_restart_overrides_saved_port(self, tmp_path, monkeypatch):
        from bacmap.interfaces.cli import main as cli

        calls: list[dict] = []
        monkeypatch.setattr(cli, "_stop_web_daemon", lambda home, timeout: 0)
        monkeypatch.setattr(cli, "_run_web", lambda ns: calls.append(vars(ns)))
        cli._save_daemon_state(
            tmp_path,
            argparse.Namespace(host="192.0.2.10", port=8899, token_env="SAVED_TOKEN"),
        )
        cli._run_restart(self._args(tmp_path, port=9001))
        assert calls[0]["port"] == 9001
        assert calls[0]["host"] == "192.0.2.10"  # 未覆盖的字段沿用保存值

    def test_stop_and_restart_parse(self):
        from bacmap.interfaces.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["stop"])
        assert args.func.__name__ == "_run_stop" and args.target == "web"
        args = parser.parse_args(["restart", "web", "--port", "8899", "--timeout", "3"])
        assert args.func.__name__ == "_run_restart"
        assert args.port == 8899 and args.timeout == 3.0
