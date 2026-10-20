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
    "bio_list_reference_genomes",
    "bio_diagnose",
    "bio_compare_runs",
)

# 助手可能读到 D4（元数据）——本地/局域网端点无碍。云端端点按 ADR-16 裁剪工具带：
# 高于云端上限（管理员最多放宽到 D2）的工具不进会话，会话数据级别由实际工具带派生
# （v1.4.28：助手可上云，D3/D4 工具永不路由到 cloud——红线不放松，能力做裁剪）。
_ASSISTANT_DATA_CLASS = DataClass.D4


def session_belt(limit: DataClass) -> tuple[tuple[str, ...], DataClass]:
    """按数据级别上限裁剪只读工具带，返回 (工具名, 会话数据级别)。

    工具的 ``output_data_class`` 取自注册表元数据；会话级别 = 工具带中最高级别
    （工具结果会回流进模型上下文，会话级别必须覆盖全部工具输出）。
    沙箱工具（sandbox_run/sandbox_shell）输出无界（可 cat 原始数据），不在此列——
    云端会话由 build_session 整体排除。
    """
    from bacmap.tools import registry

    names = tuple(
        n for n in READ_TOOL_NAMES if registry.get(n).output_data_class <= limit
    )
    data_class = max(
        (registry.get(n).output_data_class for n in names), default=DataClass.D0
    )
    return names, data_class

# 单轮提示词上限（字符）与保留的历史轮数上限（防无界上下文增长）。
_MAX_PROMPT_CHARS = 8000
_MAX_HISTORY_TURNS = 12


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
    # 上限防超大提示词（Web/TUI 在入口已限长；CLI ask/chat 依赖此处兜底）。
    bounded = text if len(text) <= _MAX_PROMPT_CHARS else text[:_MAX_PROMPT_CHARS]
    ctx = f"\n（当前 BACMAP_HOME：{home}）" if home else ""
    return f"用户请求：{bounded}{ctx}"


def _is_user_prompt(message: Any) -> bool:
    """该消息是否以用户请求开头（pydantic-ai ModelRequest 含 user-prompt part）。"""
    parts = getattr(message, "parts", None)
    if not parts:
        return False
    return any(getattr(p, "part_kind", "") == "user-prompt" for p in parts)


def _trim_history(messages: list[Any], max_turns: int = _MAX_HISTORY_TURNS) -> list[Any]:
    """只保留最近 ``max_turns`` 个用户轮次起的全部消息。

    按"用户请求"边界裁剪，避免把 tool-call 与其 tool-return **拆散**（否则续接会
    因消息配对缺失而报错）——这是无界历史的安全上界。
    """
    starts = [i for i, m in enumerate(messages) if _is_user_prompt(m)]
    if len(starts) <= max_turns:
        return messages
    return messages[starts[-max_turns]:]


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
        data_class: DataClass = _ASSISTANT_DATA_CLASS,
    ) -> None:
        self._gateway = gateway
        self._home = home
        self._role = role
        self._purpose = purpose
        self._data_class = data_class
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
                data_class=self._data_class,
                role=self._role,
                message_history=self._history or None,
            )
        except LlmUnavailableError as exc:
            return self._degraded(exc)
        return self._to_reply(result)

    async def respond_async(self, text: str) -> AgentReply:
        """``respond`` 的异步版：可被取消（TUI 用），工具在线程中执行不阻塞事件循环。"""
        return await self.respond_stream(text)

    async def respond_stream(
        self,
        text: str,
        on_event: Any | None = None,
    ) -> AgentReply:
        """流式版 ``respond_async``（v1.4.31）：过程事件经 ``on_event(kind, payload)``
        回调（可 async），见 ``LlmGateway.run_agent_events_async``；无事件回调时
        行为与 ``respond_async`` 一致。降级语义（LlmUnavailableError → C3）不变。
        """
        try:
            result = await self._gateway.run_agent_events_async(
                purpose=self._purpose,
                prompt=_build_prompt(text, self._home),
                output_type=AnalysisPlan,
                tools=self._tools,
                data_class=self._data_class,
                role=self._role,
                message_history=self._history or None,
                on_event=on_event,
            )
        except LlmUnavailableError as exc:
            return self._degraded(exc)
        return self._to_reply(result)

    def _to_reply(self, result: Any) -> AgentReply:
        self._history = _trim_history(list(result.all_messages()))
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
