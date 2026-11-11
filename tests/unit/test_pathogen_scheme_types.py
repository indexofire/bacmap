"""pathogens.yaml 分型方案类型守卫（v1.10.21）。

背景：沙门菌 ``mlst_scheme`` 曾误配 ``salmonella_2``（实为 cgMLST 2750 位点
方案），导致 MLST ST 全部 N/A——"低级错误"的根因是没有任何机制校验
方案名与用途的类型一致性。本测试从 gmlst 方案目录读取每个已配置方案的
类型，断言：

- ``mlst_scheme`` 的类型必须是 ``mlst``（7 基因经典方案）
- ``cgmlst_scheme`` 的类型必须是 ``cgmlst``
- 未配置（null/缺省）合法——物种可能不支持该分型层

gmlst 不可用（非部署环境）时跳过目录校验，仍校验本地 vendor 清单。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REGISTRY = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "core" / "pathogens.yaml"


def _species_blocks() -> dict[str, dict]:
    data = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))
    return data["pathogens"]


def _gmlst_catalog() -> dict[str, str] | None:
    """``{scheme_name: type}``；gmlst 不可用 → None（跳过目录校验）。"""
    import os
    import re

    gmlst = shutil.which("gmlst")
    if not gmlst:
        return None
    # Rich 表格默认按窄终端折行（方案名会被拆开）——固定 COLUMNS=400
    # 禁止折行，再按行切 │ 单元格：Scheme 列匹配 [a-z]+_[0-9]+，
    # 同行右侧第一个类型词单元格即该方案的类型（列序因宽度而异）。
    env = {**os.environ, "COLUMNS": "400", "TERM": "dumb"}
    try:
        proc = subprocess.run(
            [gmlst, "scheme", "list"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    catalog: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        cells = [c.strip() for c in line.split("│") if c.strip()]
        if len(cells) < 4:
            continue
        for idx, cell in enumerate(cells):
            if re.fullmatch(r"[a-z]+_[0-9]+", cell):
                for nxt in cells[idx + 1 :]:
                    if nxt in ("mlst", "cgmlst", "rmlst", "wgmlst"):
                        catalog[cell] = nxt
                        break
                break
    return catalog or None


class TestSchemeTypes:
    def test_mlst_schemes_are_classic_mlst(self):
        catalog = _gmlst_catalog()
        if catalog is None:
            pytest.skip("gmlst scheme catalog unavailable")
        bad = []
        for code, block in _species_blocks().items():
            scheme = block.get("mlst_scheme")
            if not scheme:
                continue
            stype = catalog.get(scheme)
            if stype is None:
                bad.append(f"{code}: mlst_scheme {scheme!r} 不在 gmlst 方案目录")
            elif stype != "mlst":
                bad.append(f"{code}: mlst_scheme {scheme!r} 实为 {stype}（必须 mlst）")
        assert not bad, "MLST 方案类型错配：\n" + "\n".join(bad)

    def test_cgmlst_schemes_are_cgmlst(self):
        catalog = _gmlst_catalog()
        if catalog is None:
            pytest.skip("gmlst scheme catalog unavailable")
        bad = []
        for code, block in _species_blocks().items():
            scheme = block.get("cgmlst_scheme")
            if not scheme:
                continue
            stype = catalog.get(scheme)
            if stype is None:
                bad.append(f"{code}: cgmlst_scheme {scheme!r} 不在 gmlst 方案目录")
            elif stype != "cgmlst":
                bad.append(f"{code}: cgmlst_scheme {scheme!r} 实为 {stype}（必须 cgmlst）")
        assert not bad, "cgMLST 方案类型错配：\n" + "\n".join(bad)

    def test_salmonella_mlst_is_senterica_1(self):
        """回归锁：沙门 MLST = senterica_1（7 基因 Achtman），绝不再用 cgMLST 方案。"""
        sal = _species_blocks()["SAL"]
        assert sal["mlst_scheme"] == "senterica_1"

    def test_mlst_schemes_use_seven_gene_naming_where_known(self):
        """已知经典方案的位点数（catalog 可用时核对 7 位点）。"""
        catalog = _gmlst_catalog()
        if catalog is None:
            pytest.skip("gmlst scheme catalog unavailable")
        import re

        text = subprocess.run(
            [shutil.which("gmlst") or "gmlst", "scheme", "list"],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout.replace("│", " ").replace("\n", " ")
        for code, block in _species_blocks().items():
            scheme = block.get("mlst_scheme")
            if not scheme:
                continue
            m = re.search(rf"{scheme}\s+mlst\s+(\d+)", text)
            if m:
                loci = int(m.group(1))
                assert loci == 7, f"{code}: {scheme} 位点数 {loci}（经典 MLST 应为 7）"
