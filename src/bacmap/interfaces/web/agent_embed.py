"""智能体对话嵌入配置（v1.10.24）。

bacmap 控制台内嵌本地智能体的 web UI（DSH / Hermes Dashboard / opencode
serve 等），单窗口完成"对话 + 结果查看"。配置来自 ``config.toml``：

    [[web.agent_embed]]
    name = "DSH"
    url = "http://127.0.0.1:3080/?token=<dsh-token>"   # DSH 需带 browser-trust token

    [[web.agent_embed]]
    name = "Hermes"
    url = "http://127.0.0.1:56791"

约束（ADR-16）：仅允许 ``http://127.0.0.1`` / ``http://localhost`` 回环
地址——嵌入目标是本机智能体进程，不经此面外发数据；云托管智能体前端
不属于本能力。嵌入 origin 会被加入 Web CSP 的 ``frame-src``。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator


class AgentEmbed(BaseModel):
    name: str
    url: str

    @property
    def origin(self) -> str:
        return self.url.split("/", 3)[2] if "://" in self.url else ""

    @field_validator("url")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        head = v.split("/", 3)[2] if "://" in v else ""
        host = head.split(":")[0] if head else ""
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                f"agent_embed 仅允许回环地址（ADR-16），收到 {v!r}；"
                "云托管智能体前端不可嵌入"
            )
        return v


def load_agent_embeds(config_path: Path) -> list[AgentEmbed]:
    """读 ``[[web.agent_embed]]``；无配置/文件缺失 → 空列表（功能隐藏）。"""
    if not config_path.is_file():
        return []
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    raw = data.get("web", {}).get("agent_embed", [])
    if not isinstance(raw, list):
        return []
    out: list[AgentEmbed] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(AgentEmbed(name=str(item.get("name", "")), url=str(item.get("url", ""))))
        except ValueError:
            continue  # 非回环条目跳过：不因单条坏配置阻断整个控制台
    return out


def embeds_payload(embeds: list[AgentEmbed]) -> list[dict[str, Any]]:
    return [{"name": e.name, "url": e.url} for e in embeds]
