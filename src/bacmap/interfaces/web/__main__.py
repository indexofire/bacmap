"""Web 入口：python -m bacmap.interfaces.web [--home H] [--port 8800]。

默认只绑 127.0.0.1（ADR-16）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from bacmap.config import BACMAP_HOME
from bacmap.interfaces.web.app import create_app
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="bacmap Web 任务页")
    parser.add_argument("--home", default=str(BACMAP_HOME))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8800)
    args = parser.parse_args()

    engine = DbosTaskEngine(Path(args.home))
    app = create_app(engine)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
