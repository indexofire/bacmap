"""LLM 端点配置（ADR-08/09、冻结设计 §4.5）。

配置源：``$BACMAP_HOME/config.toml`` 的 ``[llm.endpoints.<name>]``、
``[llm.routing]``、``[llm.data_policy]``；无配置时内置 Strata 本地端点。
位置（local/lan/cloud）与能力（T1/T2）是独立维度；位置决定数据分级
上限（ADR-16：cloud 默认 D1，管理员最多放宽到 D2，D3/D4 永不）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bacmap.tools.spec import DataClass

DEFAULT_STRATA_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_STRATA_MODEL = "qwen3.8-flash-next-iq3_xxs"


class LlmEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str = "openai_compatible"
    location: Literal["local", "lan", "cloud"] = "local"
    base_url: str
    model: str
    tier: str = "T2"
    max_concurrency: int = 1
    api_key_env: str | None = None
    enabled: bool = True


class DataPolicy(BaseModel):
    cloud_max_data_class: DataClass = DataClass.D1


class LlmConfig(BaseModel):
    endpoints: dict[str, LlmEndpoint] = Field(default_factory=dict)
    routing: dict[str, str] = Field(default_factory=dict)
    policy: DataPolicy = DataPolicy()

    def resolve(self, purpose: str) -> LlmEndpoint | None:
        name = self.routing.get(purpose)
        if name:
            ep = self.endpoints.get(name)
            return ep if ep and ep.enabled else None
        for ep in self.endpoints.values():
            if ep.enabled:
                return ep
        return None


def default_config() -> LlmConfig:
    return LlmConfig(
        endpoints={
            "strata": LlmEndpoint(
                name="strata",
                base_url=DEFAULT_STRATA_BASE_URL,
                model=DEFAULT_STRATA_MODEL,
                max_concurrency=1,
            )
        },
        routing={
            "intent_classifier": "strata",
            "interpretation": "strata",
        },
    )


def load_llm_config(config_path: Path) -> LlmConfig:
    """从 config.toml 解析 [llm.*]；文件不存在或缺 [llm] 段时返回默认。"""
    if not config_path.is_file():
        return default_config()
    data: dict[str, Any] = tomllib.loads(config_path.read_text(encoding="utf-8"))
    llm = data.get("llm")
    if not isinstance(llm, dict) or not llm.get("endpoints"):
        return default_config()

    endpoints: dict[str, LlmEndpoint] = {}
    for name, raw in llm["endpoints"].items():
        if isinstance(raw, dict):
            endpoints[name] = LlmEndpoint(name=name, **raw)

    routing = dict(llm.get("routing", {}))
    policy_raw = llm.get("data_policy", {})
    raw_limit = policy_raw.get("cloud_max_data_class", "D1")
    if isinstance(raw_limit, str):
        limit = DataClass[raw_limit]  # "D1" 名称查找（§4.5 TOML 字符串形式）
    else:
        limit = DataClass(raw_limit)
    policy = DataPolicy(cloud_max_data_class=limit)
    return LlmConfig(endpoints=endpoints, routing=routing, policy=policy)
