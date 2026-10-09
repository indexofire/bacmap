"""Shared infrastructure for tool handlers.

Holds config aliases, subprocess helpers, the Biopython availability check,
and the tool_handler catch-all decorator. Submodules import the names they
need so tests can monkeypatch them per-module.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from bacmap.config import (
    DB_PATH as _DEFAULT_DB_PATH,
)
from bacmap.config import (
    RESULTS_DIR as _RESULTS_DIR,
)

# ADR-03：解释器与工具取自当前运行环境（pixi 激活后即正确）。
# 旧名 PIXI_PYTHON/PIXI_BIN 保留（handlers 与测试 monkeypatch 引用），
# _PROJECT_ROOT 已废除——脚本随包分发于 tools/_scripts/。

PIXI_PYTHON = sys.executable
PIXI_BIN = str(Path(PIXI_PYTHON).resolve().parent)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 仓库根，仅供测试兼容

__all__ = [
    "_BIOPYTHON_AVAILABLE",
    "_DEFAULT_DB_PATH",
    "_PIXI_ENV",
    "_PROJECT_ROOT",
    "_RESULTS_DIR",
    "_detect_format",
    "_ensure_biopython",
    "_resolve_path",
    "_validate_sample_id",
    "_run_cmd",
    "_run_project_script",
    "_which_or_error",
    "logger",
    "tool_handler",
]

logger = logging.getLogger(__name__)

_BIOPYTHON_AVAILABLE: bool | None = None


_PIXI_ENV: dict[str, str] = dict(os.environ)
_PIXI_ENV["PATH"] = ":".join([PIXI_BIN, _PIXI_ENV.get("PATH", "")])


def _run_project_script(script_name: str, args: list[str], timeout: int = 3600) -> str:
    """Run a script from scripts/ with pixi PATH injected. Returns stdout or error JSON."""
    env = dict(_PIXI_ENV)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src_root + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [PIXI_PYTHON, str(Path(__file__).resolve().parent / "_scripts" / script_name)] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != 0:
        return json.dumps({"error": f"{script_name} failed", "stderr": result.stderr[-500:]})
    return result.stdout


def _ensure_biopython() -> bool:
    """Return True if Biopython can be imported; try lazy install once."""
    global _BIOPYTHON_AVAILABLE
    if _BIOPYTHON_AVAILABLE is not None:
        return _BIOPYTHON_AVAILABLE
    try:
        import Bio  # noqa: F401

        _BIOPYTHON_AVAILABLE = True
        return True
    except ImportError:
        pass
    try:
        subprocess.run(
            [PIXI_PYTHON, "-m", "pip", "install", "biopython"],
            check=True,
            capture_output=True,
            timeout=120,
        )
        import Bio  # noqa: F401

        _BIOPYTHON_AVAILABLE = True
        return True
    except Exception as e:
        logger.warning("Biopython not available and lazy install failed: %s", e)
    _BIOPYTHON_AVAILABLE = False
    return False


def _which_or_error(cmd: str) -> str | None:
    """Return path to cmd or None. Caller shows a helpful error."""
    return shutil.which(cmd)


def _resolve_path(p: str) -> str:
    """Expand ~ and make absolute."""
    return os.path.abspath(os.path.expanduser(p))


def _detect_format(path: str, hint: str = "auto") -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    aliases = {
        "fa": "fasta",
        "fna": "fasta",
        "ffn": "fasta",
        "faa": "fasta",
        "frn": "fasta",
        "fq": "fastq",
        "gb": "genbank",
        "gbk": "genbank",
    }
    fmt = aliases.get(ext, ext)
    if hint != "auto":
        return hint
    return fmt if fmt else "fasta"


def _run_cmd(cmd: list[str], timeout: int = 3600) -> dict[str, Any]:
    """Run a subprocess, return {returncode, stdout, stderr}."""
    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_PIXI_ENV,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:] if len(proc.stdout) > 8000 else proc.stdout,
        "stderr": proc.stderr[-4000:] if len(proc.stderr) > 4000 else proc.stderr,
    }


def tool_handler[F: Callable[..., str]](func: F) -> F:
    """Catch-all wrapper for tool handlers.

    Handlers with their own try/except keep their error paths; this decorator
    only catches otherwise-unhandled exceptions, logging them and returning
    an {"error": ...} JSON string so a handler never raises into the caller.
    """

    @functools.wraps(func)
    def wrapper(args: dict[str, Any], **kwargs: Any) -> str:
        try:
            return func(args, **kwargs)
        except Exception as e:
            logger.exception("%s failed", func.__name__)
            return json.dumps({"error": f"{func.__name__} failed: {e}"}, ensure_ascii=False)

    return cast(F, wrapper)


# P2-2（安全，沿袭 scripts/_common.validate_sample_name 决策）：LLM 可控的
# sample_id 直接进路径拼接，绝对路径/遍历串可读取任意 *_summary.json 形文件。
# 白名单 ^[A-Za-z0-9._-]+$ 在单一入口收敛全部 summary 读取 handler；
# 路径仍由各 handler 用本模块 _RESULTS_DIR 拼接（保持测试沙箱可注入）。
_SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_sample_id(sample_id: str) -> bool:
    """summary 读取前的 sample_id 白名单校验（不过 → handler 返回错误 JSON）。"""
    return bool(sample_id) and _SAMPLE_ID_RE.match(sample_id) is not None
