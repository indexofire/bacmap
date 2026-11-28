"""Web 控制台对话配置（config.toml 的 ``[web.chat]`` 段）。

``mode`` 取值：``off``（默认，不启用）/ ``builtin``（内置 pydantic-ai 后端）/
``external``（外部智能体，P2 适配）/ ``both``。外部智能体 URL 与
``agent_embed`` 同纪律：仅允许回环 http(s)、不得含凭据（ADR-16）。
无效的外部条目跳过并告警，不阻断启动。
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

ChatMode = Literal["off", "builtin", "external", "both"]
ExternalProtocol = Literal["acp", "dsh", "pi-rpc", "opencode", "hermes"]

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class BuiltinChatConfig(BaseModel):
    purpose: str = "chat"
    max_history_messages: int = 40
    auto_interpret_milestones: bool = True
    system_prompt_extra: str = ""

    @field_validator("max_history_messages")
    @classmethod
    def _clamp_history(cls, v: int) -> int:
        return max(2, min(v, 200))


class ExternalAgentConfig(BaseModel):
    id: str
    name: str
    protocol: ExternalProtocol = "acp"
    command: list[str] = Field(default_factory=list)
    url: str = ""
    workdir: str = ""
    allowed_roles: list[str] = Field(default_factory=lambda: ["admin"])
    enabled: bool = True
    api_key_env: str = ""
    auto_approve_permissions: bool = False

    @field_validator("url")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        if not v:
            return v
        try:
            parts = urlsplit(v)
            _port = parts.port
        except ValueError as exc:
            raise ValueError(f"外部智能体 URL 解析失败（ADR-16），收到 {v!r}") from exc
        if (
            parts.scheme not in {"http", "https"}
            or parts.username is not None
            or parts.password is not None
            or parts.hostname not in _LOOPBACK_HOSTS
        ):
            raise ValueError(
                f"外部智能体 URL 仅允许回环 http(s) 且不得含凭据（ADR-16），收到 {v!r}"
            )
        return v


class WebChatConfig(BaseModel):
    mode: ChatMode = "off"
    default_backend: str = "builtin"
    builtin: BuiltinChatConfig = Field(default_factory=BuiltinChatConfig)
    external: list[ExternalAgentConfig] = Field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


def load_chat_config(config_path: Path) -> WebChatConfig:
    """从 config.toml 解析 ``[web.chat]``；缺文件/缺段返回默认 off。"""
    if not Path(config_path).is_file():
        return WebChatConfig()
    try:
        data: dict[str, Any] = tomllib.loads(
            Path(config_path).read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning("chat config: %s unreadable; chat disabled", config_path)
        return WebChatConfig()
    web = data.get("web")
    if not isinstance(web, dict) or not isinstance(web.get("chat"), dict):
        return WebChatConfig()
    raw = web["chat"]

    builtin_raw = raw.get("builtin", {})
    builtin = (
        BuiltinChatConfig(**builtin_raw)
        if isinstance(builtin_raw, dict)
        else BuiltinChatConfig()
    )
    externals: list[ExternalAgentConfig] = []
    for entry in raw.get("external", []) or []:
        if not isinstance(entry, dict):
            continue
        try:
            externals.append(ExternalAgentConfig(**entry))
        except ValueError as exc:
            logger.warning(
                "chat config: skipping invalid external agent %r: %s",
                entry.get("id", "?"),
                exc,
            )
    mode = raw.get("mode", "off")
    if mode not in ("off", "builtin", "external", "both"):
        logger.warning("chat config: unknown mode %r; falling back to off", mode)
        mode = "off"
    return WebChatConfig(
        mode=mode,
        default_backend=str(raw.get("default_backend", "builtin")),
        builtin=builtin,
        external=externals,
    )
