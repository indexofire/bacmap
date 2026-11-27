"""Web/API 权限点（v1.10.x，多用户 RBAC）。

权限在**服务端**按登录主体判定；客户端隐藏导航只是体验，不构成安全边界。
旧模式（bearer/cookie 单令牌）没有主体，保持原有"部署令牌=操作员"语义。
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, Request

from bacmap.interfaces.web.auth import Principal, principal_of
from bacmap.store.users import Role


class Permission(StrEnum):
    DATA_READ = "data.read"  # 读自己可见的数据
    DATA_READ_ALL = "data.read_all"  # 读全库（analyst/admin）
    DATA_EXPORT = "data.export"
    TASK_SUBMIT = "task.submit"
    TASK_CONTROL = "task.control"  # 取消/暂停/恢复（用户仅限自己的任务）
    TASK_APPROVE = "task.approve"
    PLAN_CONFIRM = "plan.confirm"
    RECORD_WRITE = "record.write"
    IMPORT_SUBMIT = "import.submit"
    IMPORT_REVIEW = "import.review"
    SPECIMEN_WRITE = "specimen.write"
    DATA_DELETE = "data.delete"
    RESEARCH_READ = "research.read"
    RESEARCH_WRITE = "research.write"
    SYSTEM_READ = "system.read"
    USER_MANAGE = "user.manage"


_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.ANALYST: frozenset(
        {
            Permission.DATA_READ,
            Permission.DATA_READ_ALL,
            Permission.DATA_EXPORT,
            Permission.TASK_SUBMIT,
            Permission.TASK_CONTROL,
            Permission.TASK_APPROVE,
            Permission.PLAN_CONFIRM,
            Permission.RECORD_WRITE,
            Permission.IMPORT_SUBMIT,
            Permission.IMPORT_REVIEW,
            Permission.SPECIMEN_WRITE,
            Permission.DATA_DELETE,
            Permission.RESEARCH_READ,
            Permission.RESEARCH_WRITE,
            Permission.SYSTEM_READ,
        }
    ),
    Role.USER: frozenset(
        {
            Permission.DATA_READ,
            Permission.TASK_SUBMIT,
            Permission.TASK_CONTROL,
            Permission.IMPORT_SUBMIT,
        }
    ),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return _ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(principal: Principal | None, permission: Permission) -> bool:
    if principal is None:
        return False
    return permission in permissions_for(principal.role)


def require_permission(request: Request, permission: Permission) -> Principal | None:
    """账号模式校验权限；旧令牌模式返回 None（保持兼容，由调用方处理）。"""
    cfg = request.app.state.web_auth
    if not (getattr(cfg, "accounts", False) or getattr(cfg, "personal", False)):
        return principal_of(request)
    principal = principal_of(request)
    if principal is None:
        raise HTTPException(401, "authentication required")
    if not has_permission(principal, permission):
        raise HTTPException(403, f"permission denied: {permission.value}")
    return principal


def require_any(request: Request, *permissions: Permission) -> Principal | None:
    cfg = request.app.state.web_auth
    if not (getattr(cfg, "accounts", False) or getattr(cfg, "personal", False)):
        return principal_of(request)
    principal = principal_of(request)
    if principal is None:
        raise HTTPException(401, "authentication required")
    if not any(has_permission(principal, p) for p in permissions):
        raise HTTPException(403, "permission denied")
    return principal


def scoped_owner(request: Request) -> str | None:
    """普通用户返回自己的 username（用于 SQL owner 过滤）；其他角色返回 None。"""
    principal = principal_of(request)
    if principal is None:
        return None
    return principal.username if principal.role is Role.USER else None


def can_manage(request: Request) -> bool:
    principal = principal_of(request)
    return bool(principal and principal.role in (Role.ADMIN, Role.ANALYST))


def actor(request: Request, fallback: str = "web") -> str:
    """服务端认定的操作者标识（不再信任请求体里的 approver/confirmer）。"""
    principal = principal_of(request)
    if principal is not None:
        return principal.username
    return fallback


def actor_detail(request: Request, fallback: str = "web") -> str:
    principal = principal_of(request)
    if principal is not None:
        return f"web:{principal.username}"
    return fallback


def can_access_owner(request: Request, owner_user_id: str | None) -> bool:
    """主体是否可读某条 owner 的数据；无主数据仅 analyst/admin 可见。"""
    principal = principal_of(request)
    if principal is None:
        return True  # 旧令牌模式
    if principal.role in (Role.ADMIN, Role.ANALYST):
        return True
    return bool(owner_user_id) and owner_user_id == principal.username


def ensure_owner(request: Request, owner_user_id: str | None, *, what: str) -> None:
    if not can_access_owner(request, owner_user_id):
        # 404 而非 403，避免向普通用户泄露他人资源是否存在。
        raise HTTPException(404, f"{what} not found")
