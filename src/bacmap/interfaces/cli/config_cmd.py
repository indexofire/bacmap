"""``bacmap config``：配置模板初始化与路径诊断。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T


def _template_path() -> Path:
    packaged = Path(__file__).resolve().parents[2] / "config.example.toml"
    if packaged.is_file():
        return packaged
    # 源码树布局：configs/config.example.toml（v0.1.4 起模板集中在 configs/）
    return Path(__file__).resolve().parents[4] / "configs" / "config.example.toml"


def _xdg_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "bacmap" / "config.toml"


def _destination(args: argparse.Namespace) -> Path:
    if args.user:
        return _xdg_path()
    if args.project:
        return Path.cwd() / "config.toml"
    return Path(args.home) / "config.toml"


def _emit(data: Any, as_json: bool) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2) if as_json else data)


def config_init(args: argparse.Namespace) -> None:
    dest = _destination(args)
    template = _template_path()
    if not template.is_file():
        raise SystemExit(T(f"template missing: {template}", f"模板缺失：{template}"))
    if dest.exists() and not args.force:
        raise SystemExit(
            T(
                f"config already exists: {dest} (use --force to overwrite)",
                f"配置已存在：{dest}（覆盖请加 --force）",
            )
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    if args.json:
        _emit(
            {
                "created": str(dest),
                "template": str(template),
                "usage": (
                    f'export BACMAP_CONFIG="{dest}"' if args.project else "automatic"
                ),
            },
            True,
        )
        return
    print(T(f"Created {dest}", f"已创建 {dest}"))
    if args.project:
        print(
            T(
                f'set before use: export BACMAP_CONFIG="{dest}"',
                f'使用前设置：export BACMAP_CONFIG="{dest}"',
            )
        )
    elif args.user:
        print(
            T(
                "This path takes effect automatically when BACMAP_CONFIG is unset"
                " and $BACMAP_HOME/config.toml does not exist.",
                "该路径会在未设置 BACMAP_CONFIG 且 $BACMAP_HOME/config.toml 不存在时自动生效。",
            )
        )
    else:
        print(
            T(
                "bacmap reads this path automatically;"
                " use BACMAP_CONFIG to point to another file explicitly.",
                "bacmap 会自动读取该路径；也可用 BACMAP_CONFIG 显式指定其他文件。",
            )
        )


def config_path_cmd(args: argparse.Namespace) -> None:
    from bacmap.config import config_path

    active = config_path(args.home)
    if args.json:
        _emit(
            {
                "path": str(active),
                "exists": active.is_file(),
                "template": str(_template_path()),
                "bacmap_config_env": os.environ.get("BACMAP_CONFIG", ""),
            },
            True,
        )
    else:
        state = (
            T("exists", "存在")
            if active.is_file()
            else T("not found (using defaults)", "不存在（使用默认值）")
        )
        print(f"{active}  {state}")
        print(T(f"template: {_template_path()}", f"模板：{_template_path()}"))


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser("config", help=T("config template and paths", "配置模板与路径"))
    s = p.add_subparsers(dest="config_command", required=True)

    init = s.add_parser(
        "init",
        help=T("create config.toml from template", "从模板创建 config.toml"),
    )
    location = init.add_mutually_exclusive_group()
    location.add_argument(
        "--user", action="store_true",
        help=T(
            "write to the XDG config directory (default ~/.config/bacmap/config.toml)",
            "写入 XDG 配置目录（默认 ~/.config/bacmap/config.toml）",
        ),
    )
    location.add_argument(
        "--project", action="store_true",
        help=T(
            "write config.toml in the current directory (gitignored in a source checkout)",
            "写入当前目录 config.toml（源码检出中已被 gitignore）",
        ),
    )
    init.add_argument(
        "--force", action="store_true",
        help=T("overwrite an existing file", "覆盖已有文件"),
    )
    add_home(init)
    add_json(init)
    init.set_defaults(func=config_init)

    path = s.add_parser("path", help=T("show the active config file", "显示当前生效的配置文件"))
    add_home(path)
    add_json(path)
    path.set_defaults(func=config_path_cmd)
