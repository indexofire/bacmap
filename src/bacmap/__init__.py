"""bacmap — 本地病原基因组分析系统。

架构依据 docs/architecture-frozen-v1.md（ADR-01..20）。
分层：interfaces / tasks / agent / workflow / tools / core / store，
依赖方向只能自上而下（ADR-02，import-linter 在 CI 强制）。
"""

__version__ = "0.1.0"
