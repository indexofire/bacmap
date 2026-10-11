"""Web 静态资源（本地 CSS/图标，零外联，ADR-16）。

StaticFiles 挂载点：create_app 里 `app.mount("/static", StaticFiles(directory=STATIC_DIR))`。
本包内只允许自包含资源——任何 CDN/外链都会违反数据红线。
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).parent

__all__ = ["STATIC_DIR"]
