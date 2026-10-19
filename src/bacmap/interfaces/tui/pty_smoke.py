"""bacmap TUI 的 pty 冒烟 —— "computer use" 式测试。

在**伪终端**里启动真实的 `bacmap tui` 进程，像用户一样按键（输入斜杠命令、Leader 和弦），
抓取终端帧并断言关键内容出现；最后用 Leader+q 退出。全程无 GUI、可离线运行。

与固定 sleep 不同，这里**等标记**（就绪 → 命令输出 → Leader 提示 → 退出），
避免在慢机器/高负载下因时序抖动偶发失败。

用法：
    python -m bacmap.interfaces.tui.pty_smoke --home <dir> [--timeout 60]
退出码 0 = 关键帧齐全且进程正常退出；非 0 = 缺帧（打印已捕获内容便于诊断）。
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time

_ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")
# (按键, 发送后应出现的标记)。最后一条为退出，不需要标记。
_STEPS: list[tuple[bytes, str | None]] = [
    (b"/search zzz\r", "无命中"),  # 斜杠命令 + 输入 → 输出含"无命中"
    (b"\x07", "已激活"),  # Ctrl+G 激活 Leader（提示栏出现 "Leader 已激活"）
    (b"q", None),  # Leader 和弦 q → 退出
]


def _render(raw: bytes) -> str:
    return _ANSI.sub(b"", raw).decode("utf-8", errors="replace")


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def run(home: str, timeout: float = 60.0, rows: int = 45, cols: int = 140) -> int:
    pid, fd = pty.fork()
    if pid == 0:  # 子进程：exec 真实 TUI
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("COLUMNS", None)
        os.environ.pop("LINES", None)
        os.execvp(
            sys.executable,
            [sys.executable, "-m", "bacmap.interfaces.cli", "tui", "--home", home],
        )
        os._exit(127)

    _set_winsize(fd, rows, cols)
    os.set_blocking(fd, False)
    captured = bytearray()
    start = time.monotonic()
    exited = False

    def _drain() -> bool:
        """读一次；返回 False 表示 EOF。"""
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return False
        if not chunk:
            return False
        captured.extend(chunk)
        return True

    def _wait_marker(marker: str | None, until: float) -> bool:
        while time.monotonic() < until:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r and not _drain():
                return False
            if marker is None:
                continue
            if marker in _render(bytes(captured)):
                return True
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                return False
        return marker is None

    def _wait_exit(until: float) -> bool:
        while time.monotonic() < until:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                _drain()
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                return True
        return False

    try:
        # 1) 等界面就绪（帮助横幅出现）
        ready = _wait_marker("斜杠命令", start + timeout * 0.5)
        # 2) 逐步发送按键并等标记（最后一步等退出）
        for keys, marker in _STEPS:
            if not ready:
                break
            os.write(fd, keys)
            if marker is None:
                exited = _wait_exit(time.monotonic() + timeout * 0.5)
            else:
                ready = _wait_marker(marker, time.monotonic() + timeout * 0.5)
        if not exited:
            exited = _wait_exit(time.monotonic() + 2)
    finally:
        if not exited:
            os.kill(pid, signal.SIGTERM)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)
        os.close(fd)

    frame = _render(bytes(captured))
    checks = {
        "title/bacmap": "bacmap" in frame,
        "sidebar/footer": "侧栏" in frame or "任务" in frame,
        "input+dispatch": "无命中" in frame,
        "clean_exit": exited,
    }
    for name, ok in checks.items():
        print(f"{'✅' if ok else '❌'} {name}")
    if not all(checks.values()):
        print("--- captured frame (tail) ---")
        print(frame[-3000:])
        return 1
    print("--- captured frame (tail) ---")
    print(frame[-1200:])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="bacmap TUI pty smoke")
    ap.add_argument("--home", required=True)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    return run(args.home, timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
