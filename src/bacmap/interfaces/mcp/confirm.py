"""计划确认的三种便捷通道（v1.9.0，A/B/C）。

A. Web 确认链接：`confirm_url`（默认 `BACMAP_WEB_URL` 或 http://127.0.0.1:8800）；
B. 本地系统对话框：stdio 会话下由服务端弹窗，人的点击才是确认事实；
C. 低风险预授权：仅 analyze、无脚本、样本数受限时可由策略自动确认，并留审计 actor。

共同不变量：绑定 `(plan_id, version, plan_hash)`、一次性、过期/修订后失效；
模型无法通过任何通道自证"用户已确认"。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

AUTO_ACTOR = "policy:auto-confirm"
DIALOG_ACTOR = "local-dialog"


def web_base_url() -> str:
    return (os.environ.get("BACMAP_WEB_URL") or "http://127.0.0.1:8800").rstrip("/")


def confirm_url(plan_id: str, version: int) -> str:
    return f"{web_base_url()}/plans/{plan_id}?version={version}"


def _read_config(home: Path) -> dict[str, Any]:
    p = Path(home) / "config.toml"
    if not p.is_file():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def auto_confirm_allows(home: Path, tasks: list[Any]) -> bool:
    """C：`[plans.auto_confirm] enabled=true` 且任务全是受限 analyze 时允许自动确认。"""
    cfg = _read_config(home).get("plans", {}).get("auto_confirm", {})
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return False
    try:
        limit = int(cfg.get("max_samples", 20))
    except (TypeError, ValueError):
        return False  # 配置坏 → 安全回退为"需人工确认"
    for t in tasks:
        if getattr(t, "task_type", "") != "analyze":
            return False
        # 目录直入（fasta_dir/fastq_dir）是数据登记写路径，且 samples 为空会绕过
        # max_samples（0 ≤ 上限）——预授权只接受已登记样本的分析（v1.9.2）。
        if getattr(t, "fasta_dir", None) or getattr(t, "fastq_dir", None):
            return False
        samples = getattr(t, "samples", []) or []
        if not samples or len(samples) > limit:
            return False
    return True


def _dialog_command(prompt: str) -> list[str] | None:
    if shutil.which("zenity"):
        return ["zenity", "--question", "--title", "bacmap 计划确认", "--text", prompt,
                "--ok-label", "确认并提交", "--cancel-label", "取消"]
    if shutil.which("kdialog"):
        return ["kdialog", "--yesno", prompt, "--title", "bacmap 计划确认"]
    return None


def ask_local_confirmation(prompt: str, timeout: int = 120) -> bool | None:
    """B：本机弹窗；无图形环境/无工具时返回 None（由调用方回退到 Web 链接）。"""
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return None
    cmd = _dialog_command(prompt)
    if cmd is None:
        return None
    try:
        return subprocess.run(cmd, timeout=timeout, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
