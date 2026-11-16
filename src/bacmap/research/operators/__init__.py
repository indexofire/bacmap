"""研究算子包：导入即注册内置算子。"""

from __future__ import annotations

from bacmap.research.operators import builtin as _builtin  # noqa: F401 — 注册副作用
from bacmap.research.operators.spec import (
    Operator,
    OperatorContext,
    OperatorError,
    OperatorSpec,
    PortType,
    ResourceSpec,
    catalog,
    get_operator,
    list_operators,
    operator,
    register,
    unregister,
)

__all__ = [
    "Operator",
    "OperatorContext",
    "OperatorError",
    "OperatorSpec",
    "PortType",
    "ResourceSpec",
    "catalog",
    "get_operator",
    "list_operators",
    "operator",
    "register",
    "unregister",
]
