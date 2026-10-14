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

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    # 冻结设计 §4.5 声明的能力/管理字段（此前缺失，extra="forbid" 会拒绝按
    # 文档编写的 config.toml——修复为可解析；默认值对齐 §4.5 示例）。
    supports_tools_with_schema: bool = False
    constrained_decoding: bool = False
    request_timeout_s: int = 300
    admin_url: str | None = None  # Strata /load、/unload 管理端点（ADR-17）


class LlmResources(BaseModel):
    """资源仲裁配置（冻结设计 §4.5/ADR-17）。"""

    model_config = ConfigDict(extra="forbid")

    co_located: bool = True
    min_free_ram_gb_for_heavy_steps: float = 24.0


class DataPolicy(BaseModel):
    cloud_max_data_class: DataClass = DataClass.D1

    @field_validator("cloud_max_data_class")
    @classmethod
    def _clamp_cloud_limit(cls, v: DataClass) -> DataClass:
        """ADR-16 红线：cloud 端点最多放宽到 D2；D3/D4 永不，配置层直接拒绝。"""
        if v > DataClass.D2:
            raise ValueError(
                f"cloud_max_data_class 最多可放宽到 D2（ADR-16），收到 {v.name}"
            )
        return v


class LlmConfig(BaseModel):
    endpoints: dict[str, LlmEndpoint] = Field(default_factory=dict)
    routing: dict[str, str] = Field(default_factory=dict)
    policy: DataPolicy = DataPolicy()
    resources: LlmResources = LlmResources()

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
    if not isinstance(llm, dict):
        return default_config()

    resources_raw = llm.get("resources", {})
    resources = (
        LlmResources(**resources_raw) if isinstance(resources_raw, dict) else LlmResources()
    )

    if not llm.get("endpoints"):
        # 无端点段时端点/路由取默认，但 resources 独立生效（ADR-17）。
        return default_config().model_copy(update={"resources": resources})

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
    return LlmConfig(endpoints=endpoints, routing=routing, policy=policy, resources=resources)
