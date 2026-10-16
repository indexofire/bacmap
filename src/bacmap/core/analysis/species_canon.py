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

import re

SALMONELLA = "Salmonella"
ECOLI = "E. coli"
SHIGELLA = "Shigella"
VPARA = "V. parahaemolyticus"
UNKNOWN = "unknown"

# 视为"无物种结论"的占位（gside 失败/占位输出）
_UNKNOWN_TOKENS = frozenset({"", "unknown", "n/a", "na", "none", "unidentified", "pending_gside"})
# gside D1_marker 的常见病原登记名：Genus_species（可多段，如 Vibrio_cholerae_O1）
_GSIDE_LABEL_RE = re.compile(r"[A-Za-z]+(?:_[A-Za-z0-9]+)+")

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
    """verdict → 规范物种名；not_X 按 ipaH 分流（阳性→Shigella，否则 E. coli）。

    gside 的 D1_marker 覆盖常见病原，登记名为 ``Genus_species``（如
    ``Klebsiella_pneumoniae``）——识别为已知物种并规范化为可读名，避免把
    非四病原的一致结果误判为 unknown（分析结论门/特征库纳入会因此误拒）。
    """
    v = verdict.strip()
    if v.lower() in _UNKNOWN_TOKENS:
        return UNKNOWN
    if v.startswith("not_"):
        return SHIGELLA if "positive" in ipah.lower() else ECOLI
    for needle, canonical in _VERDICT_NEEDLES:
        if needle in v:
            return canonical
    if _GSIDE_LABEL_RE.fullmatch(v):
        return v.replace("_", " ")
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
