"""个人模式的访问密钥（v1.10.54，P2）。

个人模式面向单工作站单用户：不建用户名/密码，只用一个**访问密钥**登录。
密钥明文只在创建/轮换时显示一次；``$BACMAP_HOME/personal.json`` 只保存
scrypt 派生值（复用账号模块的实现），文件权限 0600。

登录成功仍走服务端会话表：为内置 ``owner`` 账号创建会话，因此 RBAC、
审计与现有 Web 中间件无需第二套身份体系；``owner`` 固定为 admin（个人模式
等同部署所有者，拥有全部功能）。
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.store.users import Role, UserService, hash_password, verify_password

PERSONAL_FILE = "personal.json"
PERSONAL_USERNAME = "owner"
ACCESS_KEY_PREFIX = "bk_"


@dataclass(frozen=True)
class PersonalAccess:
    version: int
    username: str
    key_hash: str
    created_at: str
    rotated_at: str = ""


def personal_path(home: Path | str) -> Path:
    return Path(home) / PERSONAL_FILE


def _read(home: Path | str) -> dict[str, Any] | None:
    path = personal_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def load_personal(home: Path | str) -> PersonalAccess | None:
    raw = _read(home)
    if raw is None:
        return None
    try:
        return PersonalAccess(
            version=int(raw.get("version") or 1),
            username=str(raw.get("username") or PERSONAL_USERNAME),
            key_hash=str(raw["key_hash"]),
            created_at=str(raw.get("created_at") or ""),
            rotated_at=str(raw.get("rotated_at") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def personal_ready(home: Path | str) -> bool:
    access = load_personal(home)
    return bool(access and access.key_hash)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".personal-",
        suffix=".tmp",
        delete=False,
    ) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
        temp_name = fh.name
    try:
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def ensure_personal_owner(home: Path | str) -> None:
    """确保内置 owner 账号存在且为启用的 admin（个人模式 = 全功能）。

    已存在同名账号但不是 admin/已被停用时**拒绝**而不是静默提权——否则在
    组织部署上误跑 ``personal init`` 会把一个普通 ``owner`` 账号变成管理员。
    """
    db = Path(home) / "data" / "bacmap.sqlite"
    with UserService(db) as users:
        user = users.get_by_username(PERSONAL_USERNAME)
        if user is None:
            users.create(
                PERSONAL_USERNAME,
                secrets.token_urlsafe(32),
                Role.ADMIN,
                "Personal owner",
            )
            return
        if user.role is not Role.ADMIN or user.disabled:
            raise ValueError(
                f"account {PERSONAL_USERNAME!r} already exists "
                f"(role={user.role.value}, disabled={user.disabled}); "
                "refusing to elevate it for personal mode"
            )


def create_personal(
    home: Path | str, *, rotate: bool = False, username: str = PERSONAL_USERNAME
) -> tuple[str, PersonalAccess]:
    """创建/轮换访问密钥；返回 (明文密钥, 记录)。明文不落盘。"""
    path = personal_path(home)
    if path.exists() and not rotate:
        raise FileExistsError(
            "personal access key already exists; use --rotate to replace it"
        )
    ensure_personal_owner(home)
    key = ACCESS_KEY_PREFIX + secrets.token_urlsafe(32)
    encoded = hash_password(key)
    now = datetime.now(UTC).isoformat()
    previous = _read(home) or {}
    payload = {
        "version": 1,
        "username": username or PERSONAL_USERNAME,
        "key_hash": encoded,
        "created_at": str(previous.get("created_at") or now),
        "rotated_at": now if previous else "",
    }
    _atomic_write(path, payload)
    access = PersonalAccess(
        version=1,
        username=str(payload["username"]),
        key_hash=encoded,
        created_at=str(payload["created_at"]),
        rotated_at=str(payload["rotated_at"]),
    )
    return key, access


def verify_access_key(home: Path | str, key: str) -> bool:
    access = load_personal(home)
    if access is None or not key:
        return False
    if not key.startswith(ACCESS_KEY_PREFIX):
        return False
    return verify_password(key, access.key_hash)


def personal_status(home: Path | str) -> dict[str, Any]:
    access = load_personal(home)
    if access is None:
        return {
            "ready": False,
            "username": "",
            "created_at": "",
            "rotated_at": "",
            "mode_hint": "BACMAP_WEB_AUTH=personal",
        }
    return {
        "ready": True,
        "username": access.username,
        "created_at": access.created_at,
        "rotated_at": access.rotated_at,
        "mode_hint": "BACMAP_WEB_AUTH=personal",
    }
