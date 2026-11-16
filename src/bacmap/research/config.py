"""研究编排层的运行配置（P4）：环境构建白名单与代码审核强度。

配置文件与 LLM 端点共用 ``config.toml``：

```toml
[research.env]
allow_network = true
mirrors = ["https://pypi.internal/simple", "https://cran.internal"]
proxy = "http://127.0.0.1:3128"

[research.approval]
code_review = "always"   # always | plan | off
```

约束：这些值只能由本机用户改配置文件决定；MCP/外部 Harness 没有写入口。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CODE_REVIEW_LEVELS = ("always", "plan", "off")


@dataclass(frozen=True)
class EnvBuildConfig:
    allow_network: bool = False
    mirrors: tuple[str, ...] = ()
    proxy: str = ""


@dataclass(frozen=True)
class ApprovalConfig:
    code_review: str = "always"

    def __post_init__(self) -> None:
        if self.code_review not in CODE_REVIEW_LEVELS:
            raise ValueError(
                f"unknown research.approval.code_review: {self.code_review!r}"
                f" (expected one of {', '.join(CODE_REVIEW_LEVELS)})"
            )


@dataclass(frozen=True)
class ResearchConfig:
    env: EnvBuildConfig = field(default_factory=EnvBuildConfig)
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def parse_research_config(data: dict[str, Any]) -> ResearchConfig:
    research = _section(data, "research")
    env = _section(research, "env")
    approval = _section(research, "approval")
    mirrors = env.get("mirrors") or []
    if not isinstance(mirrors, list) or not all(isinstance(m, str) for m in mirrors):
        raise ValueError("research.env.mirrors must be a list of strings")
    return ResearchConfig(
        env=EnvBuildConfig(
            allow_network=bool(env.get("allow_network", False)),
            mirrors=tuple(mirrors),
            proxy=str(env.get("proxy") or ""),
        ),
        approval=ApprovalConfig(code_review=str(approval.get("code_review") or "always")),
    )


def load_research_config(home: Path | str) -> ResearchConfig:
    from bacmap.config import config_path

    path = config_path(home)
    if not path.is_file():
        return ResearchConfig()
    with path.open("rb") as fh:
        return parse_research_config(tomllib.load(fh))
