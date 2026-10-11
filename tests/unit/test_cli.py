"""bacmap 控制台命令冒烟（参数解析层，不启动服务器）。"""

from __future__ import annotations

import sys

import pytest

from bacmap.interfaces.cli.main import main


def test_version_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap", "--version"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "bacmap" in capsys.readouterr().out


def test_missing_subcommand_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_mcp_help_lists_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["bacmap", "mcp", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--read-only" in out
    assert "--home" in out
