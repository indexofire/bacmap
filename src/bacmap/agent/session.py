"""会话式分析助手（ADR-10 规划型 + ADR-11 开放路径）。

把用户的自然语言分析需求转成**可执行的分析计划**：

- 多轮对话：``message_history`` 续接上下文；
- 只读工具：从工具注册表白名单构建（pydantic-ai ``Tool.from_schema``），
  使 LLM 能先"看现状"（样本清单/结果/元数据/任务状态）再规划；
- 结构化输出 ``AnalysisPlan``（封闭任务类型 + 参数 + 理由），
  复杂需求可产出**多个顺序任务**（如先统计、再比较、再绘图）；
- 简单需求 → ``analyze``（Snakemake 确定性路径）；深度挖掘 → ``mine``
  （写脚本，沙箱执行，过挖掘门）；
- **执行由接口层在用户确认后经 ``DbosTaskEngine`` 完成**（本模块只规划、不写）。

无 LLM（``LlmUnavailableError``）时返回降级回复（C3）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from bacmap.agent.llm.gateway import LlmGateway, LlmUnavailableError
from bacmap.tools.spec import DataClass

# 只读工具白名单（规划所需的最小集；与 assistant.role.yaml 一致）
READ_TOOL_NAMES: tuple[str, ...] = (
    "bio_list_samples",
    "bio_get_result",
    "bio_search_samples",
    "bio_query_metadata",
    "bio_review_flags",
    "bio_inspect_dataset",
    "bio_diagnose",
    "bio_compare_runs",
)

# 助手可能读到 D4（元数据）——本地端点无碍；cloud 端点会被 ADR-16 拦截（助手仅 local/lan）。
_ASSISTANT_DATA_CLASS = DataClass.D4


class PlannedTask(BaseModel):
    """计划中的单个任务（封闭任务类型 + 参数）。"""

    task_type: Literal["analyze", "curate", "mine", "write"]
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    requires_confirmation: bool = True  # 写操作一律需确认（分级确认的写侧）


class AnalysisPlan(BaseModel):
    """助手对一次 user turn 的结构化产出。"""

    reply: str = Field(description="给用户看的自然语言回复；需澄清时即提问")
    needs_clarification: bool = False
    tasks: list[PlannedTask] = Field(default_factory=list)


class AgentReply(BaseModel):
    message: str
    plan: AnalysisPlan | None = None
    degraded: bool = False


def build_read_tools(names: tuple[str, ...] = READ_TOOL_NAMES) -> list[Any]:
    """从注册表构建 pydantic-ai 只读工具（legacy JSON Schema → Tool.from_schema）。"""
    from pydantic_ai import Tool

    from bacmap.tools import registry

    tools: list[Any] = []
    for name in names:
        spec = registry.get(name)
        handler = spec.legacy_handler
        if handler is None:
            continue
        schema = (spec.legacy_schema or {}).get("parameters") or {
            "type": "object",
            "properties": {},
        }

        async def _call(_handler: Any = handler, **kwargs: Any) -> str:
            # 工具是同步 handler（文件/DB IO）：在线程中执行，避免阻塞事件循环（异步会话）。
            import anyio

            return str(await anyio.to_thread.run_sync(lambda: _handler(kwargs)))

        tools.append(
            Tool.from_schema(
                _call, name=spec.name, description=spec.description, json_schema=schema
            )
        )
    return tools


def _build_prompt(text: str, home: Path | None) -> str:
    ctx = f"\n（当前 BACMAP_HOME：{home}）" if home else ""
    return f"用户请求：{text}{ctx}"


class AgentSession:
    """多轮会话：``respond`` 规划一次，接口层确认后执行。"""

    def __init__(
        self,
        gateway: LlmGateway,
        *,
        home: Path | None = None,
        role: str = "assistant",
        tools: list[Any] | None = None,
        extra_tools: list[Any] | None = None,
        purpose: str = "intent_classifier",
    ) -> None:
        self._gateway = gateway
        self._home = home
        self._role = role
        self._purpose = purpose
        base = build_read_tools() if tools is None else tools
        self._tools = list(base) + list(extra_tools or [])
        self._history: list[Any] = []

    @property
    def history_length(self) -> int:
        return len(self._history)

    def respond(self, text: str) -> AgentReply:
        """一轮：用户文本 → 计划（多轮历史自动续接）。无 LLM 时降级。"""
        try:
            result = self._gateway.run_agent(
                purpose=self._purpose,
                prompt=_build_prompt(text, self._home),
                output_type=AnalysisPlan,
                tools=self._tools,
                data_class=_ASSISTANT_DATA_CLASS,
                role=self._role,
                message_history=self._history or None,
            )
        except LlmUnavailableError as exc:
            return self._degraded(exc)
        return self._to_reply(result)

    async def respond_async(self, text: str) -> AgentReply:
        """``respond`` 的异步版：可被取消（TUI 用），工具在线程中执行不阻塞事件循环。"""
        try:
            result = await self._gateway.run_agent_async(
                purpose=self._purpose,
                prompt=_build_prompt(text, self._home),
                output_type=AnalysisPlan,
                tools=self._tools,
                data_class=_ASSISTANT_DATA_CLASS,
                role=self._role,
                message_history=self._history or None,
            )
        except LlmUnavailableError as exc:
            return self._degraded(exc)
        return self._to_reply(result)

    def _to_reply(self, result: Any) -> AgentReply:
        self._history = list(result.all_messages())
        plan = result.output
        if not isinstance(plan, AnalysisPlan):
            plan = AnalysisPlan.model_validate(plan)
        return AgentReply(message=plan.reply, plan=plan)

    @staticmethod
    def _degraded(exc: Exception) -> AgentReply:
        return AgentReply(
            message=(
                f"内置助手暂不可用（{exc}）。可改用确定性路径："
                "`bacmap task submit --type analyze --samples <ID>`。"
            ),
            degraded=True,
        )
