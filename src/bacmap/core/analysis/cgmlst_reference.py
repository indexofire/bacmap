"""cgMLST 参考库定位（**按 scheme 命名**，单一实现）。

约定：``<ref_dir>/cgmlst/<scheme>/reference_profiles.tsv``（scheme 如
``senterica_2``）。理由：物种键曾有四种写法（`Salmonella` / `E.coli` /
`Escherichia coli` / 码 `ECO`），各写各的目录名导致三处别名表；按 **scheme**
命名后与物种口径彻底解耦（scheme 是 gmlst 的稳定标识符，全系统唯一）。

参考库由运维构建（与 `vendor_cgmlst_schemes.py` 的 scheme 目录约定一致）；缺失时
调用方按"无参考库"降级，不猜测。
"""

from __future__ import annotations

from pathlib import Path

from bacmap.core.analysis.cgmlst_types import CgmlstProfile
from bacmap.core.utils import parse_cgmlst_profiles


def reference_profiles_path(scheme: str, *, ref_dir: Path) -> Path:
    return Path(ref_dir) / "cgmlst" / scheme / "reference_profiles.tsv"


def load_reference_profiles(scheme: str, *, ref_dir: Path) -> list[CgmlstProfile] | None:
    """读取参考库；scheme 为空 / 文件缺失 / 解析失败 → None（调用方降级）。"""
    if not scheme:
        return None
    path = reference_profiles_path(scheme, ref_dir=ref_dir)
    if not path.is_file():
        return None
    try:
        return parse_cgmlst_profiles(path.read_text())
    except (ValueError, OSError):
        return None
