"""默认 samples.tsv 模板：新部署不应播种任何样例/测试数据（v1.10.34）。"""

from __future__ import annotations

from bacmap.workflow.runner import WORKFLOW_PKG_DIR


def test_shipped_samples_template_has_no_preregistered_rows():
    lines = [
        line
        for line in (WORKFLOW_PKG_DIR / "config" / "samples.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert lines and lines[0].split("\t")[0] == "sample"
    assert lines[1:] == []
