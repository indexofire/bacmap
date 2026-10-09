"""包内数据文件定位（ADR-03：包数据不属于运行时路径推导范畴）。"""

from __future__ import annotations

from pathlib import Path


def pkg_dir() -> Path:
    """bacmap.core 包目录（pathogens.yaml 等随包分发的数据在此）。"""
    return Path(__file__).resolve().parent
