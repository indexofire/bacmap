"""stdio 入口：python -m bacmap.interfaces.mcp [--home BACMAP_HOME]。"""

from __future__ import annotations

import argparse
from pathlib import Path

from bacmap.config import BACMAP_HOME
from bacmap.interfaces.mcp.server import build_server
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="bacmap MCP server (stdio)")
    parser.add_argument("--home", default=str(BACMAP_HOME), help="BACMAP_HOME 根目录")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="只读模式：不暴露任务提交工具（纯查询）",
    )
    args = parser.parse_args()

    engine = None if args.read_only else DbosTaskEngine(Path(args.home))
    build_server(engine).run(transport="stdio")


if __name__ == "__main__":
    main()
