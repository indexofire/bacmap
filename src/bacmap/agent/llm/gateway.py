"""LLM 接入门（ADR-08；ADR-02：唯一导入 pydantic-ai 的模块）。

职责（冻结设计 §4.5 调用规则的代码化）：
- 串行/限并发队列（Strata 单槽位：max_concurrency 信号量）
- 数据分级拦截（V9）：cloud 端点收到超限级别即拒绝（不发送、可审计）
- 结构化输出重试 ≤2 次，仍失败抛 LlmUnavailableError → 上层按无 LLM 降级
- 同步 API：与 DBOS 引擎/Web 同步路由协同，避开事件循环（证据 §10.13 教训 4）
"""

from __future__ import annotations

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


class DataClassViolationError(RuntimeError):
    """payload 数据级别超过端点（cloud）允许上限——拒绝发送。"""


class LlmUnavailableError(RuntimeError):
    """重试耗尽仍无法获得合法结构化输出——上层按无 LLM 降级。"""


def _default_agent_factory(endpoint: LlmEndpoint, output_type: type[BaseModel]) -> Any:
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
    return Agent(model, output_type=output_type, retries=MAX_RETRIES)


class LlmGateway:
    """结构化输出统一入口。agent_factory 可注入（测试）。"""

    def __init__(
        self,
        config: LlmConfig,
        agent_factory: Callable[[LlmEndpoint, type[BaseModel]], Any] | None = None,
    ) -> None:
        self._config = config
        self._factory = agent_factory or _default_agent_factory
        self._sems: dict[str, threading.Semaphore] = {
            name: threading.Semaphore(max(ep.max_concurrency, 1))
            for name, ep in config.endpoints.items()
        }
        self._agents: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def _agent_for(self, endpoint: LlmEndpoint, output_type: type[BaseModel]) -> Any:
        key = (endpoint.name, f"{output_type.__module__}.{output_type.__qualname__}")
        with self._lock:
            if key not in self._agents:
                self._agents[key] = self._factory(endpoint, output_type)
            return self._agents[key]

    def structured(
        self,
        purpose: str,
        prompt: str,
        output_type: type[BaseModel],
        data_class: DataClass = DataClass.D0,
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

        agent = self._agent_for(endpoint, output_type)
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
