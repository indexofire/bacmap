"""ADR-02 依赖边界中 import-linter 覆盖不到的部分（v1.5 契约化补足）。

- import-linter 不支持外部子包作为禁止目标：``interfaces.mcp`` 只实现 MCP
  服务端，不得导入 ``mcp.client``；
- ``bacmap.workflow`` 是命名空间包（无 ``__init__``），grimp 不可见：其中的
  Python 模块与 Snakemake 脚本不得导入 LLM 库、DBOS、MCP 或上层包。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "bacmap"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _violations(root: Path, forbidden: tuple[str, ...], base: Path = SRC) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for name in _imports(path):
            if any(_matches(name, f) for f in forbidden):
                found.append(f"{path.relative_to(base)} -> {name}")
    return found


def test_mcp_interface_is_server_only():
    assert _violations(SRC / "interfaces" / "mcp", ("mcp.client",)) == []


def test_workflow_namespace_stays_below_agent_tasks_interfaces():
    forbidden = (
        "pydantic_ai",
        "openai",
        "dbos",
        "mcp",
        "bacmap.agent",
        "bacmap.tasks",
        "bacmap.interfaces",
    )
    assert _violations(SRC / "workflow", forbidden) == []


def test_scanner_detects_lazy_import(tmp_path: Path):
    """自检：扫描器能识别函数内的延迟导入（防止规则静默失效）。"""
    pkg = tmp_path / "interfaces" / "mcp"
    pkg.mkdir(parents=True)
    (pkg / "bad.py").write_text("def f():\n    from mcp.client import Client\n", encoding="utf-8")
    assert _violations(pkg, ("mcp.client",), base=tmp_path) == [
        f"{Path('interfaces/mcp/bad.py')} -> mcp.client"
    ]
