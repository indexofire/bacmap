"""Hermes 插件适配器（ADR-15）。

从 bacmap.tools.registry 生成 Hermes 插件注册；修正 entry-point 组名为
``hermes_agent.plugins``（旧声明 ``hermes.plugins`` 不生效，证据 §2.2）。
经 MCP 接入为首选通道，本插件为第二渠道。
"""

from __future__ import annotations

import logging
from typing import Any

from bacmap.tools import registry

logger = logging.getLogger(__name__)


def register(ctx: Any) -> None:
    for name, schema, handler in registry.legacy_table():
        ctx.register_tool(name=name, toolset="bioinfo", schema=schema, handler=handler)

    logger.info("bacmap hermes adapter registered %d tools", len(registry.list_specs()))
