"""应用服务的统一错误语义（各接口层映射为 HTTP 状态 / MCP 错误信封 / CLI 退出）。"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"


class ApplicationError(Exception):
    code: ErrorCode = ErrorCode.VALIDATION

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "error": self.message}


class ValidationFailed(ApplicationError):
    code = ErrorCode.VALIDATION


class NotFound(ApplicationError):
    code = ErrorCode.NOT_FOUND


class Conflict(ApplicationError):
    """计划已过期、版本/哈希不匹配、状态不允许该操作、输入目录已变化。"""

    code = ErrorCode.CONFLICT
