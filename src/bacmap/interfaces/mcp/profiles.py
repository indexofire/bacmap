"""MCP Profile：按数据级别裁剪对外工具带（v1.5，ADR-12/ADR-16）。

MCP 客户端背后的模型位置不可验证（外部 Harness 可能接云端模型），因此
默认按最不利假设处理：``cloud`` Profile 只暴露 ``output_data_class`` 不超过
``[llm.data_policy].cloud_max_data_class``（默认 D1，管理员最多放宽到 D2）的工具。
``local-trusted`` 可见至 D4，但必须由管理员在 ``config.toml`` 中显式开启：

    [mcp]
    allow_local_trusted = true

MCP 2026-07-28 起协议无状态、工具列表不随连接变化——因此 **一个服务实例
只绑定一个 Profile**（stdio 由启动参数固定；HTTP 每个 Profile 单独起实例并配
独立 token），客户端无法在请求中自我升级。
"""

from __future__ import annotations

import getpass
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from bacmap.tools.spec import DataClass


class McpProfile(StrEnum):
    CLOUD = "cloud"
    LOCAL_TRUSTED = "local-trusted"


class ProfileNotAllowedError(RuntimeError):
    """请求的 Profile 未被管理员开启。"""


@dataclass(frozen=True)
class ProfileSpec:
    """一个 MCP 服务实例的权限上下文（服务端决定，客户端不可改）。"""

    profile: McpProfile
    max_data_class: DataClass
    actor: str  # 任务提交者身份：由传输层/启动配置决定，不接受客户端自填

    def allows(self, data_class: DataClass) -> bool:
        return data_class <= self.max_data_class


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _local_trusted_enabled(config: dict[str, Any]) -> bool:
    section = config.get("mcp")
    return isinstance(section, dict) and section.get("allow_local_trusted") is True


def _cloud_ceiling(config_path: Path) -> DataClass:
    # 与 LLM 网关共用同一数据策略（单一事实来源）；load_llm_config 已强制 ≤ D2。
    from bacmap.agent.llm.endpoints import load_llm_config

    return load_llm_config(config_path).policy.cloud_max_data_class


def resolve_profile(name: str, home: Path, transport: str) -> ProfileSpec:
    """解析启动参数中的 Profile；``local-trusted`` 未开启时拒绝启动。"""
    profile = McpProfile(name)
    config_path = Path(home) / "config.toml"
    if profile is McpProfile.LOCAL_TRUSTED:
        if not _local_trusted_enabled(_read_toml(config_path)):
            raise ProfileNotAllowedError(
                "MCP Profile 'local-trusted' 未开启：管理员需在 "
                f"{config_path} 中设置 [mcp] allow_local_trusted = true（ADR-16）"
            )
        ceiling = DataClass.D4
    else:
        ceiling = _cloud_ceiling(config_path)
    return ProfileSpec(profile=profile, max_data_class=ceiling, actor=_actor(profile, transport))


def _actor(profile: McpProfile, transport: str) -> str:
    if transport == "stdio":
        # stdio 由本机进程启动：以启动它的操作系统账户为主体。
        try:
            user = getpass.getuser()
        except OSError:  # 无 USER/LOGNAME 且无 passwd 条目（极简容器）
            user = "unknown"
        return f"mcp-stdio:{profile.value}:{user}"
    return f"mcp-http:{profile.value}"
