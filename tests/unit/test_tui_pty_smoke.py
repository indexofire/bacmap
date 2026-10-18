"""bacmap TUI 的 pty 冒烟测试（"computer use" 式：伪终端驱动真实进程）。

覆盖：渲染出主界面 → 输入斜杠命令并看到输出 → Leader 和弦退出。
无 pty 的平台跳过（Windows/无 posix）。
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "posix", reason="pty 仅在 posix 可用")
def test_tui_pty_smoke(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bacmap.interfaces.tui.pty_smoke",
            "--home",
            str(tmp_path),
            "--timeout",
            "40",
        ],
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert proc.returncode == 0, (
        f"pty smoke failed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-1500:]}"
    )
    assert "✅ input+dispatch" in proc.stdout
