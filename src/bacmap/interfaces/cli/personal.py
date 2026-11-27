"""``bacmap personal``：个人模式访问密钥（v1.10.54，P2）。

个人模式是单工作站单用户形态：Web 只有一个 ``owner``（admin，全功能），
登录凭据是一枚访问密钥。密钥明文只在 init/rotate 时打印一次，数据库/配置中
只保存 scrypt 派生值；``personal.json`` 权限 0600。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.store.personal import create_personal, personal_status


def run_init(args: argparse.Namespace) -> None:
    rotate = bool(getattr(args, "rotate", False))
    try:
        key, access = create_personal(Path(args.home), rotate=rotate)
    except FileExistsError as exc:
        raise SystemExit(
            T(
                f"{exc}; rerun with --rotate to replace the current key",
                f"{exc}；如需替换现有密钥请加 --rotate",
            )
        ) from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(
            json.dumps(
                {
                    "status": "rotated" if rotate else "created",
                    "username": access.username,
                    "access_key": key,
                    "path": str(Path(args.home) / "personal.json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(T("personal access key created", "个人模式访问密钥已创建"))
    print(f"  {T('user', '用户')}: {access.username} (admin)")
    print(f"  {T('key', '密钥')}: {key}")
    print(
        T(
            "Store it now; it is not shown again. Start with BACMAP_WEB_AUTH=personal.",
            "请立即保存；此密钥不会再次显示。启动时设置 BACMAP_WEB_AUTH=personal。",
        )
    )


def run_status(args: argparse.Namespace) -> None:
    payload = personal_status(Path(args.home))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not payload["ready"]:
        print(
            T(
                "personal mode is not initialized; run: bacmap personal init",
                "个人模式尚未初始化；请执行：bacmap personal init",
            )
        )
        return
    print(T("personal mode initialized", "个人模式已初始化"))
    print(f"  {T('user', '用户')}: {payload['username']} (admin)")
    print(f"  {T('created', '创建时间')}: {payload['created_at']}")
    if payload["rotated_at"]:
        print(f"  {T('rotated', '轮换时间')}: {payload['rotated_at']}")


def run_rotate(args: argparse.Namespace) -> None:
    args.rotate = True
    run_init(args)


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "personal",
        help=T(
            "personal mode access key (single-user workstation)",
            "个人模式访问密钥（单用户工作站）",
        ),
    )
    p_sub = p.add_subparsers(dest="personal_command", required=True)

    p_init = p_sub.add_parser(
        "init",
        help=T("create the access key and owner account", "创建访问密钥与 owner 账号"),
    )
    add_home(p_init)
    add_json(p_init)
    p_init.add_argument(
        "--rotate",
        action="store_true",
        help=T("replace an existing key", "替换现有密钥"),
    )
    p_init.set_defaults(func=run_init)

    p_status = p_sub.add_parser("status", help=T("show initialization state", "查看初始化状态"))
    add_home(p_status)
    add_json(p_status)
    p_status.set_defaults(func=run_status)

    p_rotate = p_sub.add_parser("rotate", help=T("rotate the access key", "轮换访问密钥"))
    add_home(p_rotate)
    add_json(p_rotate)
    p_rotate.set_defaults(func=run_rotate)


__all__ = ["add_parser"]
