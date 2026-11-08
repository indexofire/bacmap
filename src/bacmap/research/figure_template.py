"""B 档自定义图脚本模板（agent 起步脚手架）。

模板是自包含的：只依赖标准库 + matplotlib，不导入 bacmap，因此可以直接在
``bacmap-figures:py312`` 沙箱镜像里经 ``mine`` 开放路径执行。它演示了图片契约的
全部要求：

- 数字只读 ``FigureSpec``（spec.data），不自行改数；
- 输出格式必须在 ``spec.style.formats`` 允许范围内；
- 尊重 ``spec.style``（尺寸、字体、DPI、色盲友好配色）；
- 结束时打印 provenance 摘要，供 ``bacmap research figure attach`` 登记。

bacmap 侧用 ``render_template()``/``write_template()`` 输出该文件；模板内容变更
视为契约变更，需同步升级示例与文档。
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE = '''#!/usr/bin/env python
"""bacmap B-tier custom figure template.

Runs inside the mine sandbox (image ``bacmap-figures:py312``): no network,
bacmap not importable. Numbers come from the FigureSpec only; the output format
must be allowed by spec.style.formats. After rendering, register the figure
with `bacmap research figure attach <session_id> --path <out> --code <this file>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

_COLORS = ["#4c72b0", "#55a868", "#c44e52", "#dd8452"]  # colorblind-safe
_LABELS = [
    ("gene_pos_resistant", "gene+ / resistant"),
    ("gene_pos_susceptible", "gene+ / susceptible"),
    ("gene_neg_resistant", "gene- / resistant"),
    ("gene_neg_susceptible", "gene- / susceptible"),
]


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="figure_spec.json path")
    parser.add_argument("--out", required=True, help="output file (pdf/svg/png)")
    args = parser.parse_args()

    with open(args.spec, encoding="utf-8") as handle:
        spec = json.load(handle)
    if spec.get("schema") != "bacmap.figure_spec/1":
        sys.exit("not a bacmap.figure_spec/1 document")
    style = spec.get("style", {})
    suffix = args.out.rsplit(".", 1)[-1].lower()
    allowed = {str(f).lower() for f in style.get("formats", ["pdf", "svg", "png"])}
    if suffix not in allowed:
        sys.exit(f"output format .{suffix} not allowed by the spec: {sorted(allowed)}")

    # Fail fast on contract violations above; only then load the plotting stack
    # (matplotlib lives in the sandbox image, not in the bacmap environment).
    import matplotlib

    matplotlib.use("Agg")  # sandbox has no display
    import matplotlib.pyplot as plt

    data = spec.get("data", {})
    table = data.get("table", {})
    labels = [label for _, label in _LABELS]
    counts = [int(table.get(key, 0)) for key, _ in _LABELS]

    width_in = float(style.get("width_mm", 180.0)) / 25.4
    height_in = float(style.get("height_mm", 120.0)) / 25.4
    figure, axis = plt.subplots(figsize=(width_in, height_in))
    axis.barh(labels, counts, color=_COLORS)
    axis.set_title(spec.get("title", ""), fontsize=float(style.get("font_size_pt", 8)) + 2)
    axis.set_xlabel("isolates (n)")
    axis.invert_yaxis()
    for spine in ("top", "right"):
        axis.spines[spine].set_visible(False)
    figure.tight_layout()
    figure.savefig(
        args.out,
        format=suffix,
        dpi=int(style.get("dpi", 300)),
    )
    plt.close(figure)

    with open(args.out, "rb") as handle:
        output_sha256 = hashlib.sha256(handle.read()).hexdigest()
    print(
        json.dumps(
            {
                "figure_id": spec.get("figure_id", ""),
                "session_id": spec.get("source", {}).get("session_id", ""),
                "spec_sha256": _sha256_text(_canonical(spec)),
                "data_sha256": _sha256_text(_canonical(spec.get("data", {}))),
                "output_sha256": output_sha256,
                "next": (
                    "bacmap research figure attach <session_id> "
                    f"--path {args.out} --code {sys.argv[0]}"
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
'''


def render_template() -> str:
    """Return the B-tier template script content."""
    return TEMPLATE


def write_template(path: str | Path) -> Path:
    """Write the B-tier template to ``path`` (parent directories are created)."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE, encoding="utf-8")
    return target
