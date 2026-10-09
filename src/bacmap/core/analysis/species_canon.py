"""物种判决规范化 —— 共享单一实现（评审 A5：消除同 PR 内 ≥4 份拷贝）。

- ``canonical_from_verdict(verdict, ipah)``：管线 verdict → 规范物种名。
  not_ 前缀按 ipaH 分流（Shigella/E. coli）；供 nli_reflector / validate
  类消费者使用。
- ``collapse_binomial(verdict)``：二名形/别名 → verify_species 期望的 token。
  not_ 前缀原样保留（维持 Layer 2 报错信息可读）；供 deterministic_verifier
  使用。
- 规范名常量：各模块的文本提取表 / gold 前缀表的值必须引用这些常量，
  新增病原只改本模块一处。
"""

from __future__ import annotations

SALMONELLA = "Salmonella"
ECOLI = "E. coli"
SHIGELLA = "Shigella"
VPARA = "V. parahaemolyticus"
UNKNOWN = "unknown"

# 子串 → 规范名（顺序敏感：物种专名先于属名缩写）
_VERDICT_NEEDLES: tuple[tuple[str, str], ...] = (
    ("Salmonella", SALMONELLA),
    ("parahaemolyticus", VPARA),
    ("Shigella", SHIGELLA),
    ("E. coli", ECOLI),
    ("E.coli", ECOLI),
    ("DEC", ECOLI),
)


def canonical_from_verdict(verdict: str, ipah: str = "") -> str:
    """verdict → 规范物种名；not_X 按 ipaH 分流（阳性→Shigella，否则 E. coli）。"""
    v = verdict.strip()
    if not v:
        return UNKNOWN
    if v.startswith("not_"):
        return SHIGELLA if "positive" in ipah.lower() else ECOLI
    for needle, canonical in _VERDICT_NEEDLES:
        if needle in v:
            return canonical
    return UNKNOWN


def collapse_binomial(verdict: str) -> str:
    """二名形/别名 → verify_species 期望 token；not_ 前缀原样保留。"""
    v = verdict.strip()
    if v.startswith("not_"):
        return v
    for needle, canonical in _VERDICT_NEEDLES:
        if needle in v:
            return canonical
    return v
