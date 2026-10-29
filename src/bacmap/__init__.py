"""bacmap — 本地病原基因组分析系统。

架构依据 docs/concepts/frozen-design.zh.md（ADR-01..21，中文权威）。
分层：interfaces / tasks / agent / workflow / tools / core / store，
依赖方向只能自上而下（ADR-02，import-linter 在 CI 强制）。
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bacmap")
except PackageNotFoundError:  # 源码树直接运行且未安装：如实标注未知
    __version__ = "0+unknown"
