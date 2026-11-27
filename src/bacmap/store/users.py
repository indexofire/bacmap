"""本地账号、会话与 API 令牌（v1.10.x，用户账号系统）。

存储位于 ``data/bacmap.sqlite``（与 specimens/isolates 同库，迁移 4）。设计约束：

- 密码只保存 scrypt 派生值（stdlib，无新依赖），格式
  ``scrypt$n$r$p$salt_hex$hash_hex``；校验用常量时间比较。
- 浏览器会话保存**服务端**哈希，cookie 中只有随机令牌——禁用用户/改角色后
  可在下一次请求立即失效（旧的无状态令牌做不到）。
- API 令牌同样只存 SHA-256 哈希，明文只在创建时返回一次。
- 禁止删除/停用最后一个可用管理员（避免把自己锁在系统外）。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from bacmap.store.schema import ensure_data_schema

SESSION_TTL_S = 12 * 3600
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")

class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    USER = "user"


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    role: Role
    display_name: str
    disabled: bool
    created_at: str
    updated_at: str

    @property
    def label(self) -> str:
        return self.display_name or self.username


USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('admin','analyst','user')),
    display_name TEXT NOT NULL DEFAULT '',
    disabled     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
"""

SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS web_sessions (
    session_hash TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    client_ip    TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT ''
)
"""

API_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL DEFAULT '',
    expires_at   TEXT NOT NULL DEFAULT '',
    revoked_at   TEXT NOT NULL DEFAULT ''
)
"""

# 迁移语句在 store/schema.py 的 data_migrations() 中登记（版本 4）。
ACCOUNT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON web_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_tokens_user ON api_tokens(user_id)",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
        maxmem=_SCRYPT_MAXMEM,
    )


def hash_password(password: str) -> str:
    """生成 scrypt 密码哈希；空/过短密码直接拒绝（调用方负责提示）。"""
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(password) > 256:
        raise ValueError("password is too long")
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt)
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def validate_username(username: str) -> str:
    value = username.strip()
    if not _USERNAME_RE.match(value):
        raise ValueError(
            "username must be 3-64 chars, start alphanumeric, and contain only "
            "letters, digits, dot, underscore or hyphen"
        )
    return value.lower()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=str(row["user_id"]),
        username=str(row["username"]),
        role=Role(str(row["role"])),
        display_name=str(row["display_name"] or ""),
        disabled=bool(row["disabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class UserService:
    """账号/会话/令牌的持久化服务（上下文管理器，显式关闭连接）。"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        ensure_data_schema(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 30000")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> UserService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 账号 -----------------------------------------------------------------

    def has_users(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return bool(row and int(row[0]) > 0)

    def count_admins(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0"
        ).fetchone()
        return int(row[0]) if row else 0

    def get(self, user_id: str) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        try:
            value = validate_username(username)
        except ValueError:
            return None
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (value,)
        ).fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        rows = self._conn.execute(
            "SELECT * FROM users ORDER BY username"
        ).fetchall()
        return [_row_to_user(r) for r in rows]

    def create(
        self,
        username: str,
        password: str,
        role: Role | str = Role.USER,
        display_name: str = "",
    ) -> User:
        name = validate_username(username)
        role_value = Role(role).value
        now = _now()
        user_id = "u_" + secrets.token_hex(8)
        try:
            self._conn.execute(
                "INSERT INTO users"
                " (user_id, username, password_hash, role, display_name, disabled,"
                "  created_at, updated_at)"
                " VALUES (?,?,?,?,?,0,?,?)",
                (user_id, name, hash_password(password), role_value,
                 display_name.strip()[:120], now, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user already exists: {name}") from exc
        user = self.get(user_id)
        if user is None:  # pragma: no cover — 插入成功却读不到只可能是库损坏
            raise RuntimeError("created user cannot be read back")
        return user

    def set_role(self, user_id: str, role: Role | str) -> User:
        role_value = Role(role).value
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        if user.role is Role.ADMIN and not user.disabled and role_value != Role.ADMIN.value:
            self._guard_last_admin(user)
        cur = self._conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE user_id = ?",
            (role_value, _now(), user_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(user_id)
        return self._require(user_id)

    def set_disabled(self, user_id: str, disabled: bool) -> User:
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        if disabled and not user.disabled:
            self._guard_last_admin(user)
        self._conn.execute(
            "UPDATE users SET disabled = ?, updated_at = ? WHERE user_id = ?",
            (1 if disabled else 0, _now(), user_id),
        )
        self._conn.commit()
        if disabled:
            self.revoke_user_sessions(user_id)
            self.revoke_user_tokens(user_id)
        return self._require(user_id)

    def set_password(self, user_id: str, password: str) -> None:
        encoded = hash_password(password)
        cur = self._conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
            (encoded, _now(), user_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(user_id)
        # 改密后旧会话/令牌全部失效，避免泄露的会话继续可用。
        self.revoke_user_sessions(user_id)
        self.revoke_user_tokens(user_id)

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.get_by_username(username)
        if user is None:
            # 未知用户名也跑一次 scrypt，降低按响应时间枚举用户名的可能。
            verify_password(password, _DUMMY_HASH)
            return None
        try:
            encoded = self._conn.execute(
                "SELECT password_hash FROM users WHERE user_id = ?", (user.user_id,)
            ).fetchone()
        except sqlite3.Error:
            return None
        if encoded is None or not verify_password(password, str(encoded[0])):
            return None
        if user.disabled:
            return None
        return user

    def _guard_last_admin(self, user: User) -> None:
        if user.role is Role.ADMIN and self.count_admins() <= 1:
            raise ValueError("cannot disable or demote the last active administrator")

    def _require(self, user_id: str) -> User:
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    # ---- 浏览器会话 -------------------------------------------------------------

    @staticmethod
    def _session_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_session(
        self,
        user_id: str,
        *,
        ttl_s: int = SESSION_TTL_S,
        client_ip: str = "",
        user_agent: str = "",
    ) -> str:
        user = self.get(user_id)
        if user is None or user.disabled:
            raise ValueError("account is not available")
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self._conn.execute(
            "INSERT INTO web_sessions"
            " (session_hash, user_id, created_at, expires_at, last_seen_at,"
            "  client_ip, user_agent)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                self._session_hash(token),
                user_id,
                now.isoformat(),
                (now + timedelta(seconds=max(60, ttl_s))).isoformat(),
                now.isoformat(),
                client_ip[:128],
                user_agent[:400],
            ),
        )
        self._conn.commit()
        return token

    def resolve_session(self, token: str) -> tuple[User, str] | None:
        """返回 (user, session_hash)；过期/禁用/不存在返回 None。"""
        if not token:
            return None
        digest = self._session_hash(token)
        row = self._conn.execute(
            "SELECT * FROM web_sessions WHERE session_hash = ?", (digest,)
        ).fetchone()
        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(str(row["expires_at"]))
        except ValueError:
            expires = datetime.now(UTC) - timedelta(seconds=1)
        if expires <= datetime.now(UTC):
            self._conn.execute(
                "DELETE FROM web_sessions WHERE session_hash = ?", (digest,)
            )
            self._conn.commit()
            return None
        user = self.get(str(row["user_id"]))
        if user is None or user.disabled:
            self._conn.execute(
                "DELETE FROM web_sessions WHERE session_hash = ?", (digest,)
            )
            self._conn.commit()
            return None
        # 每 60 秒更新一次 last_seen，避免每个请求都写库。
        try:
            last = datetime.fromisoformat(str(row["last_seen_at"]))
            if (datetime.now(UTC) - last).total_seconds() > 60:
                self._conn.execute(
                    "UPDATE web_sessions SET last_seen_at = ? WHERE session_hash = ?",
                    (_now(), digest),
                )
                self._conn.commit()
        except ValueError:
            pass
        return user, digest

    def revoke_session(self, session_hash: str) -> None:
        self._conn.execute(
            "DELETE FROM web_sessions WHERE session_hash = ?", (session_hash,)
        )
        self._conn.commit()

    def revoke_user_sessions(self, user_id: str) -> None:
        self._conn.execute("DELETE FROM web_sessions WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def purge_expired_sessions(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM web_sessions WHERE expires_at <= ?",
            (datetime.now(UTC).isoformat(),),
        )
        self._conn.commit()
        return int(cur.rowcount)

    # ---- API 令牌 ---------------------------------------------------------------

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_api_token(
        self, user_id: str, name: str = "", *, expires_days: int = 0
    ) -> str:
        user = self.get(user_id)
        if user is None or user.disabled:
            raise ValueError("account is not available")
        token = "bm_" + secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = (
            (now + timedelta(days=expires_days)).isoformat() if expires_days > 0 else ""
        )
        self._conn.execute(
            "INSERT INTO api_tokens"
            " (token_hash, user_id, name, created_at, last_used_at, expires_at,"
            "  revoked_at) VALUES (?,?,?,?,?,?, '')",
            (self._token_hash(token), user_id, name.strip()[:120], now.isoformat(),
             "", expires),
        )
        self._conn.commit()
        return token

    def resolve_api_token(self, token: str) -> User | None:
        if not token:
            return None
        digest = self._token_hash(token)
        row = self._conn.execute(
            "SELECT * FROM api_tokens WHERE token_hash = ?", (digest,)
        ).fetchone()
        if row is None or str(row["revoked_at"] or ""):
            return None
        expires = str(row["expires_at"] or "")
        if expires:
            try:
                if datetime.fromisoformat(expires) <= datetime.now(UTC):
                    return None
            except ValueError:
                return None
        user = self.get(str(row["user_id"]))
        if user is None or user.disabled:
            return None
        self._conn.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
            (_now(), digest),
        )
        self._conn.commit()
        return user

    def list_api_tokens(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT token_hash, name, created_at, last_used_at, expires_at, revoked_at"
            " FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": str(r["token_hash"])[:16],
                "name": str(r["name"]),
                "created_at": str(r["created_at"]),
                "last_used_at": str(r["last_used_at"]),
                "expires_at": str(r["expires_at"]),
                "revoked": bool(str(r["revoked_at"] or "")),
            }
            for r in rows
        ]

    def revoke_api_token(self, user_id: str, token_id: str) -> bool:
        rows = self._conn.execute(
            "SELECT token_hash FROM api_tokens WHERE user_id = ?", (user_id,)
        ).fetchall()
        for row in rows:
            digest = str(row["token_hash"])
            if digest.startswith(token_id):
                self._conn.execute(
                    "UPDATE api_tokens SET revoked_at = ? WHERE token_hash = ?",
                    (_now(), digest),
                )
                self._conn.commit()
                return True
        return False

    def revoke_user_tokens(self, user_id: str) -> None:
        self._conn.execute(
            "UPDATE api_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at = ''",
            (_now(), user_id),
        )
        self._conn.commit()


# 未知用户名的等时校验占位（不可用密码登录，仅消耗相近时间）。
_DUMMY_HASH = (
    "scrypt$16384$8$1$00000000000000000000000000000000$"
    + "00" * 32
)
