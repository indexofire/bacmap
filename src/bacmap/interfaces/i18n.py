"""界面层文案双语（``config.toml`` ``[ui] language`` / 环境变量 ``BACMAP_LANG``）。

约定：``T(en, zh)`` 的两个实参分别是英文与中文文案，二者语义必须完全一致
（仅语言不同）；Rich 标记与插值在两份文案中保持等价结构。语言解析见
:func:`bacmap.config.ui_language`（默认 ``en``，仓库文档以英文为默认语言）。
目前用于 CLI（``interfaces.cli``）与 Web 启动校验（``interfaces.web.auth``）；
同层引用，不违反 ADR-02 依赖方向。
"""

from __future__ import annotations

from bacmap.config import ui_language


def T(en: str, zh: str) -> str:
    """按当前显示语言返回文案：默认英文，``zh`` 配置时返回中文。"""
    return zh if ui_language() == "zh" else en


__all__ = ["T"]
