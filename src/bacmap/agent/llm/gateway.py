"""LLM 接入门（ADR-08；ADR-02：唯一导入 pydantic-ai 的模块）。

职责（冻结设计 §4.5 调用规则的代码化）：
- 串行/限并发队列（Strata 单槽位：max_concurrency 信号量）
- 数据分级拦截（V9）：cloud 端点收到超限级别即拒绝（不发送、可审计）
- 结构化输出重试 ≤2 次，仍失败抛 LlmUnavailableError → 上层按无 LLM 降级
- 同步 API：与 DBOS 引擎/Web 同步路由协同，避开事件循环（证据 §10.13 教训 4）
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.tools.spec import DataClass

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # 首次 + 2 次重试（ADR-08）

_TIER_RANK = {"T0": 0, "T1": 1, "T2": 2}


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(str(tier).upper(), 2)


def _build_role_instructions(role: str | None) -> str | None:
    if not role:
        return None
    from bacmap.agent.roledef import build_system_prompt

    return build_system_prompt(role)


class DataClassViolationError(RuntimeError):
    """payload 数据级别超过端点（cloud）允许上限——拒绝发送。"""


class LlmUnavailableError(RuntimeError):
    """重试耗尽仍无法获得合法结构化输出——上层按无 LLM 降级。"""


def _default_agent_factory(
    endpoint: LlmEndpoint, output_type: type[BaseModel], instructions: str | None = None
) -> Any:
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    api_key = "local"
    if endpoint.api_key_env:
        api_key = os.environ.get(endpoint.api_key_env, "missing")
    model = OpenAIChatModel(
        endpoint.model,
        provider=OpenAIProvider(base_url=endpoint.base_url, api_key=api_key),
    )
    return Agent(
        model,
        output_type=output_type,
        retries=MAX_RETRIES,
        instructions=instructions,
    )


class LlmGateway:
    """结构化输出统一入口。agent_factory 可注入（测试）。

    role 参数（ADR-10 三文件体系）：给定角色时经 roledef.build_system_prompt
    组装 system instructions 注入该角色的临时智能体实例（缓存按角色隔离）。
    """

    def __init__(
        self,
        config: LlmConfig,
        agent_factory: Callable[
            [LlmEndpoint, type[BaseModel], str | None], Any
        ] | None = None,
    ) -> None:
        self._config = config
        self._factory = agent_factory or _default_agent_factory
        self._sems: dict[str, threading.Semaphore] = {
            name: threading.Semaphore(max(ep.max_concurrency, 1))
            for name, ep in config.endpoints.items()
        }
        self._agents: dict[tuple[str, str, str, str], Any] = {}
        self._lock = threading.Lock()

    def _agent_for(
        self,
        endpoint: LlmEndpoint,
        output_type: type[BaseModel],
        role: str | None = None,
        instructions: str | None = None,
    ) -> Any:
        key = (
            endpoint.name,
            f"{output_type.__module__}.{output_type.__qualname__}",
            role or "",
            # 说明书纳入键：同一 (端点, 输出类型, 角色) 但 instructions 不同时不串用。
            hashlib.sha256((instructions or "").encode("utf-8")).hexdigest()[:12],
        )
        with self._lock:
            if key not in self._agents:
                self._agents[key] = self._factory(endpoint, output_type, instructions)
            return self._agents[key]

    def structured(
        self,
        purpose: str,
        prompt: str,
        output_type: type[BaseModel],
        data_class: DataClass = DataClass.D0,
        role: str | None = None,
    ) -> BaseModel:
        endpoint = self._config.resolve(purpose)
        if endpoint is None:
            raise LlmUnavailableError(f"no enabled endpoint for purpose {purpose!r}")

        if (
            endpoint.location == "cloud"
            and data_class > self._config.policy.cloud_max_data_class
        ):
            logger.warning(
                "data class violation: purpose=%s endpoint=%s payload=%s limit=%s",
                purpose,
                endpoint.name,
                data_class.name,
                self._config.policy.cloud_max_data_class.name,
            )
            raise DataClassViolationError(
                f"payload {data_class.name} exceeds cloud limit "
                f"{self._config.policy.cloud_max_data_class.name}"
            )

        instructions = None
        if role:
            from bacmap.agent import roledef

            try:
                rd = roledef.load_role_def(role)
                instructions = roledef.build_system_prompt(role)
            except (OSError, ValueError) as exc:
                raise LlmUnavailableError(f"role {role!r} unavailable: {exc}") from exc
            if endpoint.location not in rd.allowed_locations:
                raise DataClassViolationError(
                    f"role {role!r} forbids endpoint location {endpoint.location!r}"
                )
            if data_class > DataClass[rd.max_data_class]:
                raise DataClassViolationError(
                    f"payload {data_class.name} exceeds role {role!r} "
                    f"data class ceiling {rd.max_data_class}"
                )
            # ADR-09：端点能力档位不得低于角色的 min_model_tier（档位单调 T0<T1<T2）。
            if _tier_rank(endpoint.tier) < _tier_rank(rd.min_model_tier):
                raise LlmUnavailableError(
                    f"role {role!r} requires >= {rd.min_model_tier} but endpoint "
                    f"{endpoint.name!r} is {endpoint.tier}"
                )
        agent = self._agent_for(endpoint, output_type, role, instructions)
        sem = self._sems.get(endpoint.name)
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                if sem is not None:
                    with sem:
                        result = agent.run_sync(prompt)
                else:
                    result = agent.run_sync(prompt)
                return result.output
            except Exception as exc:  # noqa: BLE001 —— 校验/网络异常统一重试
                last_exc = exc
                logger.warning(
                    "structured attempt %d/%d failed on %s: %s",
                    attempt + 1,
                    MAX_RETRIES + 1,
                    endpoint.name,
                    exc,
                )
        raise LlmUnavailableError(
            f"structured output failed after {MAX_RETRIES + 1} attempts on {endpoint.name}"
        ) from last_exc
