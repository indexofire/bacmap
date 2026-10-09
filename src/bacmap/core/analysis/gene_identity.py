"""AMR 基因身份归一（CARD 同基因异名）。

validate_analytical 与 nli_reflector 共用的单一实现（评审 A2：同一 PR 内
两模块不得对基因身份判定不一致）：
- bla 前缀：blaCTX-M-15 ≡ CTX-M-15
- mcr 等位变异后缀：MCR-1.1 ≡ mcr-1（跨家族不归一，mcr-3.2 ↛ mcr-1）
"""

from __future__ import annotations

import re

_MCR_VARIANT_RE = re.compile(r"^(mcr-\d+)\.\d+$")


def normalize_amr(name: str) -> str:
    cf = name.casefold()
    if cf.startswith("bla") and len(cf) > 4:
        return cf[3:]
    m = _MCR_VARIANT_RE.match(cf)
    if m:
        return m.group(1)
    return cf
