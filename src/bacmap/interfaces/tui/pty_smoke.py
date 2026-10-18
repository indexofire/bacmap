"""bacmap TUI 的 pty 冒烟 —— "computer use" 式测试。

在**伪终端**里启动真实的 `bacmap tui` 进程，像用户一样按键（输入斜杠命令、Leader 和弦），
抓取终端帧并断言关键内容出现；最后用 Leader+q 退出。全程无 GUI、可离线运行。

用法：
    python -m bacmap.interfaces.tui.pty_smoke --home <dir> [--timeout 40]
退出码 0 = 关键帧齐全且进程正常退出；非 0 = 缺帧（打印已捕获内容便于诊断）。
"""

from __future__ import annotations

import argparse
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
# 每个动作：等待秒数后发送的字节。Ctrl+G = 0x07（Leader）；q 触发退出。
_ACTIONS: list[tuple[float, bytes, str]] = [
    (3.0, b"/search zzz\r", "检索"),  # 斜杠命令 + 输入 → 输出应含"无命中"
    (1.5, b"\x07", "leader"),  # Ctrl+G 激活 Leader
    (1.5, b"q", "quit"),  # Leader 和弦 q
]


def _render(raw: bytes) -> str:
    return _ANSI.sub(b"", raw).decode("utf-8", errors="replace")


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def run(home: str, timeout: float = 40.0, rows: int = 45, cols: int = 140) -> int:
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
    action_idx = 0
    next_action = start + _ACTIONS[0][0]
    exited = False

    try:
        while time.monotonic() - start < timeout:
            now = time.monotonic()
            if action_idx < len(_ACTIONS) and now >= next_action:
                _t, keys, _label = _ACTIONS[action_idx]
                os.write(fd, keys)
                action_idx += 1
                if action_idx < len(_ACTIONS):
                    next_action = now + _ACTIONS[action_idx][0]
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                captured.extend(chunk)
            wpid, _status = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                exited = True
                break
        if not exited:
            wpid, _status = os.waitpid(pid, os.WNOHANG)
            exited = wpid == pid
    finally:
        if not exited:
            os.kill(pid, signal.SIGTERM)
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
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
    ap.add_argument("--timeout", type=float, default=40.0)
    args = ap.parse_args()
    return run(args.home, timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
