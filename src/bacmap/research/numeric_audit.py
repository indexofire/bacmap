"""数字审计门（P2）：报告文本中的每个数字都必须能回溯到产物或模板常量。

这是"LLM 只能组织语言、不能产生数字"的机器强制点。做法是保守的启发式：

- 先从文本中屏蔽时间戳、内容哈希、十六进制 id（它们不是数据数字）；
- 抽取其余数字 token；
- 每个 token 必须等于某个槽位值（按数值比较）或模板声明的结构常量；
- 否则视为"凭空数字"，报告拒绝生成。

已知局限（有意接受）：与常量数值相同的伪造数字（例如恰好写成 1）无法被
识别——因此 P2 之后仍需"claim → artifact"绑定作为第二道闸。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# ISO 时间戳、sha256/长十六进制 id、Markdown 标题（章节号是结构不是数据）：不参与审计
_HEADING = re.compile(r"(?m)^#{1,6} .*$")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ][0-9:.+\-Z]+")
_HEX = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_NUM = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w.\-])")

# 模板结构常量：章节号、表格/图号、95% CI、α、Haldane 校正、2×2
TEMPLATE_CONSTANTS: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 95.0, 0.05, 0.5)

_MISSING = {"无法估计", "—"}


def mask_non_data(text: str) -> str:
    return _HEX.sub(" ", _ISO.sub(" ", _HEADING.sub(" ", text)))


def numeric_tokens(text: str) -> list[str]:
    """抽取数据数字 token（已屏蔽时间戳/哈希）。"""
    return [m.group(0) for m in _NUM.finditer(mask_non_data(text))]


def _as_floats(values: Iterable[object]) -> set[float]:
    out: set[float] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.add(float(value))
            continue
        if isinstance(value, str):
            if value in _MISSING:
                continue
            text_value = value[1:] if value[:1] in {"<", ">"} else value
            try:
                out.add(float(text_value))
            except ValueError:
                continue
    return out


def audit_numbers(
    text: str,
    slots: dict[str, object],
    *,
    extra_allowed: Iterable[float] = (),
) -> list[str]:
    """返回无法回溯的数字 token（空列表 = 通过）。"""
    allowed = _as_floats(slots.values()) | _as_floats(extra_allowed) | set(TEMPLATE_CONSTANTS)
    violations: list[str] = []
    for token in numeric_tokens(text):
        try:
            value = float(token)
        except ValueError:  # pragma: no cover - 正则保证可解析
            violations.append(token)
            continue
        if value not in allowed:
            violations.append(token)
    return violations
