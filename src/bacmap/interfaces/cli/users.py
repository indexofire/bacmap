"""``bacmap user``：本地账号管理（本机 shell 即管理员）。

Web 端没有"首次无密码安装"入口：首个管理员必须在本机用 CLI 创建，
避免任何能访问登录页的人抢先注册管理员。
"""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.store.users import Role, UserService


def _service(home: str) -> UserService:
    return UserService(Path(home) / "data" / "bacmap.sqlite")


def _payload(user: Any) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role.value,
        "display_name": user.display_name,
        "disabled": user.disabled,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _password(args: argparse.Namespace) -> str:
    value = getattr(args, "password", "") or ""
    if value:
        return value
    first = getpass.getpass(T("Password: ", "密码："))
    second = getpass.getpass(T("Repeat password: ", "再输入一次："))
    if first != second:
        raise SystemExit(T("passwords do not match", "两次密码不一致"))
    return first


def run_list(args: argparse.Namespace) -> None:
    with _service(args.home) as users:
        items = [_payload(u) for u in users.list_users()]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        print(T("no users; create one with: bacmap user create --role admin",
                "暂无用户；请用 bacmap user create --role admin 创建首个管理员"))
        return
    for item in items:
        status = "disabled" if item["disabled"] else "active"
        print(f"{item['username']:<24} {item['role']:<8} {status:<8} {item['display_name']}")


def run_create(args: argparse.Namespace) -> None:
    try:
        with _service(args.home) as users:
            user = users.create(
                args.username,
                _password(args),
                args.role,
                getattr(args, "display_name", "") or "",
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        print(json.dumps(_payload(user), ensure_ascii=False, indent=2))
        return
    print(T(f"created {user.username} ({user.role.value})",
            f"已创建 {user.username}（{user.role.value}）"))


def run_set_role(args: argparse.Namespace) -> None:
    with _service(args.home) as users:
        target = users.get_by_username(args.username)
        if target is None:
            raise SystemExit(T(f"user not found: {args.username}",
                               f"用户不存在：{args.username}"))
        try:
            user = users.set_role(target.user_id, args.role)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    print(T(f"{user.username} is now {user.role.value}",
            f"{user.username} 的角色已改为 {user.role.value}"))


def run_disable(args: argparse.Namespace) -> None:
    with _service(args.home) as users:
        target = users.get_by_username(args.username)
        if target is None:
            raise SystemExit(T(f"user not found: {args.username}",
                               f"用户不存在：{args.username}"))
        try:
            user = users.set_disabled(target.user_id, not args.enable)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    state = T("enabled", "已启用") if not user.disabled else T("disabled", "已停用")
    print(f"{user.username}: {state}")


def run_passwd(args: argparse.Namespace) -> None:
    with _service(args.home) as users:
        target = users.get_by_username(args.username)
        if target is None:
            raise SystemExit(T(f"user not found: {args.username}",
                               f"用户不存在：{args.username}"))
        try:
            users.set_password(target.user_id, _password(args))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    print(T(f"password updated for {args.username}", f"已更新 {args.username} 的密码"))


def run_token(args: argparse.Namespace) -> None:
    with _service(args.home) as users:
        target = users.get_by_username(args.username)
        if target is None:
            raise SystemExit(T(f"user not found: {args.username}",
                               f"用户不存在：{args.username}"))
        if args.token_command == "create":  # noqa: S105 — argparse dest, not a secret
            token = users.create_api_token(
                target.user_id, getattr(args, "name", "") or "",
                expires_days=int(getattr(args, "expires_days", 0) or 0),
            )
            if args.json:
                print(json.dumps({"username": target.username, "token": token},
                                 ensure_ascii=False, indent=2))
            else:
                print(token)
                print(T("store it now; it is not shown again",
                        "请立即保存；此令牌不会再次显示"), flush=True)
        elif args.token_command == "list":  # noqa: S105
            items = users.list_api_tokens(target.user_id)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                for item in items:
                    state = "revoked" if item["revoked"] else "active"
                    print(f"{item['id']}  {state:<8} {item['name']}")
        elif args.token_command == "revoke":  # noqa: S105
            if not users.revoke_api_token(target.user_id, args.token_id):
                raise SystemExit(T("token not found", "令牌不存在"))
            print(T("token revoked", "令牌已吊销"))


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "user",
        help=T("manage local accounts (admin shell command)",
                "管理本地账号（本机管理员命令）"),
    )
    p_sub = p.add_subparsers(dest="user_command", required=True)

    p_ls = p_sub.add_parser("list", aliases=["ls"], help=T("list users", "列出用户"))
    add_home(p_ls)
    add_json(p_ls)
    p_ls.set_defaults(func=run_list)

    p_create = p_sub.add_parser("create", help=T("create a user", "创建用户"))
    add_home(p_create)
    add_json(p_create)
    p_create.add_argument("username")
    p_create.add_argument(
        "--password",
        default="",
        help=T("password (prompted if omitted)", "密码（省略则交互输入）"),
    )
    p_create.add_argument("--role", choices=["admin", "analyst", "user"], default="user")
    p_create.add_argument("--display-name", default="")
    p_create.set_defaults(func=run_create)

    p_role = p_sub.add_parser("set-role", help=T("change a role", "修改角色"))
    add_home(p_role)
    p_role.add_argument("username")
    p_role.add_argument("role", choices=["admin", "analyst", "user"])
    p_role.set_defaults(func=run_set_role)

    p_disable = p_sub.add_parser("disable", help=T("disable a user", "停用用户"))
    add_home(p_disable)
    p_disable.add_argument("username")
    p_disable.add_argument("--enable", action="store_true", help=T("re-enable instead", "改为启用"))
    p_disable.set_defaults(func=run_disable)

    p_passwd = p_sub.add_parser("passwd", help=T("reset a password", "重置密码"))
    add_home(p_passwd)
    p_passwd.add_argument("username")
    p_passwd.add_argument(
        "--password",
        default="",
        help=T("password (prompted if omitted)", "密码（省略则交互输入）"),
    )
    p_passwd.set_defaults(func=run_passwd)

    p_token = p_sub.add_parser("token", help=T("manage personal API tokens", "管理个人 API 令牌"))
    t_sub = p_token.add_subparsers(dest="token_command", required=True)
    for name, help_text in (("create", T("create a token", "创建令牌")),
                            ("list", T("list tokens", "列出令牌"))):
        t = t_sub.add_parser(name, help=help_text)
        add_home(t)
        add_json(t)
        t.add_argument("username")
        if name == "create":
            t.add_argument("--name", default="")
            t.add_argument("--expires-days", type=int, default=0)
        t.set_defaults(func=run_token)
    t_revoke = t_sub.add_parser("revoke", help=T("revoke a token", "吊销令牌"))
    add_home(t_revoke)
    t_revoke.add_argument("username")
    t_revoke.add_argument("token_id")
    t_revoke.set_defaults(func=run_token)


__all__ = ["Role", "add_parser"]
