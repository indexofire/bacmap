"""Snakemake ``script:`` 指令脚本的 ``from __future__`` 禁令（v1.10.19）。

Snakemake 把 preamble（pickle 注入等可执行代码）拼在 ``script:`` 脚本
最前面，``from __future__ import`` 因此不再是文件首条语句 → 编译期
SyntaxError，且发生在任何 try 块之前（无 traceback，极难排查）。

merge_annotation.py 曾带 ``from __future__ import annotations``，自
v1.10.14 潜伏、首次启用注释（BACMAP_ANNOTATION_ENABLED 缺省）时引爆。
本测试锁定：所有经 ``script:`` 指令执行的脚本禁止 ``from __future__``。
"""

from __future__ import annotations

import re
from pathlib import Path

_RULES = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "rules"
_WORKFLOW = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow"

_SCRIPT_DIRECTIVE_RE = re.compile(r"^\s*script:\s*$", re.MULTILINE)
_PATH_RE = re.compile(r'''["']([^"']+)["']''')


def _script_directive_targets() -> list[Path]:
    """收集所有 ``script:`` 指令引用的脚本路径（相对其 .smk 文件解析）。"""
    targets: list[Path] = []
    for smk in sorted(_RULES.glob("*.smk")):
        text = smk.read_text(encoding="utf-8")
        for block in _SCRIPT_DIRECTIVE_RE.split(text)[1:]:
            # 块内第一条非空行应为脚本路径（与 Snakemake 语法一致）
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = _PATH_RE.search(line)
                if m:
                    targets.append((smk.parent / m.group(1)).resolve())
                break
    return targets


class TestScriptDirectiveNoFutureImports:
    def test_collects_script_targets(self):
        targets = _script_directive_targets()
        names = {t.name for t in targets}
        assert "merge_annotation.py" in names
        assert "collect_summary.py" in names

    def test_no_future_imports_in_script_directive_scripts(self):
        offenders: list[str] = []
        for target in _script_directive_targets():
            if not target.is_file():
                continue
            for lineno, line in enumerate(
                target.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if re.match(r"^\s*from __future__ import", line):
                    offenders.append(f"{target.name}:{lineno}")
        assert not offenders, (
            "script: 指令脚本含 from __future__ import（Snakemake preamble 注入后"
            f"触发 SyntaxError）: {offenders}"
        )
