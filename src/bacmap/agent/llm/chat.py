"""内置 pydantic-ai 对话后端（ADR-02：本文件是 agent.chat 唯一 LLM 实现）。

职责：
- 端点解析与 ADR-16 数据分级上限（cloud fail-closed，运行时复核 debug 开关）；
- 端点并发信号量（排队时向前端发 bacmap.queue_status 自定义事件）；
- 工具面按角色分层：admin/analyst/legacy 全库只读+计算工具（按数据级别过滤），
  Role.USER 仅 D0 公共工具 + 本人样本/任务（严格 owner 隔离）；
- 计划工具严格遵守 ADR-21：模型只能创建/修订计划，确认永远发生在
  bacmap 自有界面（Web 计划卡片按钮 / CLI）；服务端 auto_confirm 策略
  仅对可确认角色生效；
- 经 ``agent.iter`` 逐节点流式产出 AG-UI 事件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai import (
    Agent,
    CallToolsNode,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRequestNode,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    Tool,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    UserPromptPart,
)

from bacmap.agent.chat.agui import (
    AgUiEvent,
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ThinkingTextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    new_id,
)
from bacmap.agent.chat.config import BuiltinChatConfig
from bacmap.agent.chat.types import ChatRunContext
from bacmap.agent.llm.endpoints import LlmConfig, LlmEndpoint
from bacmap.tasks.params import PlannableTask
from bacmap.tools.spec import DataClass, Effect

if TYPE_CHECKING:
    from bacmap.store.chat import ChatMessage

logger = logging.getLogger(__name__)

_TOOL_RESULT_WIRE_LIMIT = 16_000
_ENDPOINT_SEMS: dict[tuple[str, int, Any], asyncio.Semaphore] = {}


def _endpoint_semaphore(endpoint: LlmEndpoint) -> asyncio.Semaphore:
    """每端点并发信号量；键含当前事件循环，避免跨循环测试共享陈旧绑定。"""
    loop = asyncio.get_running_loop()
    key = (endpoint.name, max(endpoint.max_concurrency, 1), loop)
    sem = _ENDPOINT_SEMS.get(key)
    if sem is None:
        sem = asyncio.Semaphore(max(endpoint.max_concurrency, 1))
        _ENDPOINT_SEMS[key] = sem
    return sem


def _safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:300]


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


class _TaskTooling:
    """任务查询工具面（按角色分层；D2 以下脱敏）。"""

    def __init__(
        self,
        engine: Any,
        home: Path,
        actor: Any,
        ceiling: DataClass,
        side: list[AgUiEvent],
    ) -> None:
        self._engine = engine
        self._home = home
        self._actor = actor
        self._ceiling = ceiling
        self._side = side

    def _redact(self, data: dict[str, Any]) -> dict[str, Any]:
        if self._ceiling < DataClass.D2 and data.get("message"):
            data = dict(data)
            data["message"] = ""
            data["message_withheld"] = True
        return data

    def task_status(self, task_id: str) -> str:
        """查询任务状态（state/step/message）。普通用户仅能查询本人任务。"""
        if not self._actor.can_read_all:
            try:
                task = self._engine.get_task(task_id)
            except KeyError:
                return _dump({"error": "task not found"})
            if task.get("submitted_by") != self._actor.username:
                return _dump({"error": "task not found"})
        try:
            st = self._engine.status(task_id)
        except KeyError:
            return _dump({"error": "task not found"})
        data = self._redact(st.model_dump(mode="json"))
        self._side.append(
            CustomEvent(
                name="bacmap.task_ref",
                value={"task_id": task_id, "state": data.get("state", "")},
            )
        )
        return _dump(data)

    def list_tasks(self, limit: int = 20, task_type: str = "") -> str:
        """列出最近的任务（可按类型过滤）。"""
        rows = self._engine.list_tasks(limit, task_type=task_type or "")
        return _dump({"items": [self._redact(dict(r)) for r in rows]})

    def task_result(self, task_id: str) -> str:
        """已完成任务的结果摘要（run_id 与门结论）。"""
        try:
            st = self._engine.status(task_id)
            result = self._engine.workflow_result(task_id)
        except KeyError:
            return _dump({"error": "task not found"})
        out: dict[str, Any] = {
            "task_id": task_id,
            "state": st.state.value,
            "finished": result is not None,
        }
        if result is not None:
            out["run_id"] = result.get("run_id")
            if self._ceiling >= DataClass.D2:
                out["result"] = result
            else:
                out["result_withheld"] = True
        return _dump(out)

    def my_samples(self, query: str = "", limit: int = 20) -> str:
        """列出当前用户自己的样本（严格 owner 隔离）。"""
        if self._ceiling < DataClass.D2:
            return _dump({"withheld": True, "reason": "data ceiling below D2"})
        from bacmap.store.strain_index import StrainGenotypeIndex

        gom_db = self._home / "gom.sqlite"
        if not gom_db.is_file():
            return _dump({"items": [], "total": 0})
        with StrainGenotypeIndex(gom_db) as index:
            items, total = index.sample_page(
                query=query,
                owner_user_id=self._actor.username,
                limit=max(1, min(limit, 100)),
            )
        return _dump({"items": items, "total": total})

    def my_tasks(self, limit: int = 20, task_type: str = "") -> str:
        """列出当前用户自己提交的任务。"""
        rows = self._engine.list_tasks(
            limit, task_type=task_type or "", submitted_by=self._actor.username
        )
        return _dump({"items": [self._redact(dict(r)) for r in rows]})

    def tools(self) -> list[Tool]:
        tools = [
            Tool(
                self.task_status,
                name="bacmap_task_status",
                description=(
                    "查询任务状态（state: running/succeeded/failed/"
                    "awaiting_approval/cancelled）。"
                ),
            )
        ]
        if self._actor.can_read_all:
            tools.extend(
                [
                    Tool(
                        self.list_tasks,
                        name="bacmap_list_tasks",
                        description="列出最近的分析/策展/挖掘任务及其状态。",
                    ),
                    Tool(
                        self.task_result,
                        name="bacmap_task_result",
                        description="已完成任务的结果摘要；大文件与报告请在控制台查看。",
                    ),
                ]
            )
        else:
            tools.extend(
                [
                    Tool(
                        self.my_samples,
                        name="bacmap_my_samples",
                        description="列出你自己名下的样本（不含其他用户的数据）。",
                    ),
                    Tool(
                        self.my_tasks,
                        name="bacmap_my_tasks",
                        description="列出你自己提交的任务及状态。",
                    ),
                ]
            )
        return tools


class _PlanTooling:
    """计划工具（ADR-21：模型只能创建/修订/查询；确认只在可信界面）。"""

    def __init__(self, service: Any, engine: Any, actor: Any, side: list[AgUiEvent]) -> None:
        self._service = service
        self._engine = engine
        self._actor = actor
        self._side = side

    def _card(self, rec: Any) -> dict[str, Any]:
        return {
            "plan_id": rec.plan_id,
            "version": rec.version,
            "state": rec.state.value,
            "plan_hash": rec.plan_hash,
            "short_hash": rec.short_hash,
            "rationale": rec.rationale,
            "tasks": [t.model_dump(mode="json") for t in rec.tasks],
            "task_ids": list(rec.task_ids),
            "created_by": rec.created_by,
            "can_confirm": self._actor.can_confirm_plans,
        }

    def _emit(self, rec: Any) -> None:
        card = self._card(rec)
        self._side.append(CustomEvent(name="bacmap.plan_card", value=card))
        for tid in rec.task_ids:
            self._side.append(
                CustomEvent(
                    name="bacmap.task_ref",
                    value={"task_id": tid, "plan_id": rec.plan_id},
                )
            )

    def _maybe_auto_confirm(self, rec: Any) -> Any:
        if not self._actor.can_confirm_plans:
            return rec
        from bacmap.interfaces.mcp.confirm import auto_confirm_allows

        if auto_confirm_allows(Path(self._engine.home), rec.tasks):
            return self._service.confirm(
                rec.plan_id, rec.version, rec.plan_hash, "policy:auto-confirm"
            )
        return rec

    def _check_user_tasks(self, tasks: list[Any]) -> str | None:
        if self._actor.can_confirm_plans:
            return None
        for t in tasks:
            if str(getattr(t, "task_type", "")) not in ("analyze", "reanalyze"):
                return _dump(
                    {
                        "error": "你的角色只能创建 analyze/reanalyze 类型的计划；"
                        "其他类型请由 analyst/admin 创建"
                    }
                )
        return None

    def _run_guarded(self, action: str, fn: Any) -> str:
        from bacmap.application.errors import ApplicationError

        try:
            rec = fn()
        except ApplicationError as exc:
            return _dump(exc.to_dict())
        except Exception as exc:
            return _dump({"error": _safe_error(exc)})
        self._emit(rec)
        return _dump(self._card(rec))

    def create_plan(self, tasks: list[PlannableTask], rationale: str = "") -> str:
        """创建分析计划。计划创建后必须由用户在控制台确认才会执行；
        你不能自行确认。"""
        rejected = self._check_user_tasks(tasks)
        if rejected is not None:
            return rejected

        def _do() -> Any:
            rec = self._service.create(tasks, rationale, self._actor.username)
            return self._maybe_auto_confirm(rec)

        return self._run_guarded("create", _do)

    def revise_plan(
        self, plan_id: str, tasks: list[PlannableTask], rationale: str = ""
    ) -> str:
        """修订未确认/已拒绝的计划（产生新版本，旧版本作废）。"""
        rejected = self._check_user_tasks(tasks)
        if rejected is not None:
            return rejected
        from bacmap.application.errors import ApplicationError

        try:
            existing = self._service.get(plan_id)
        except ApplicationError as exc:
            return _dump(exc.to_dict())
        if not self._actor.can_confirm_plans and existing.created_by != self._actor.username:
            return _dump({"error": "只能修订自己创建的计划"})

        def _do() -> Any:
            rec = self._service.revise(plan_id, tasks, rationale, self._actor.username)
            return self._maybe_auto_confirm(rec)

        return self._run_guarded("revise", _do)

    def get_plan(self, plan_id: str, version: int | None = None) -> str:
        """查询计划状态；确认后返回 task_ids 供 bacmap_task_status 跟踪。"""
        from bacmap.application.errors import ApplicationError

        try:
            rec = self._service.get(plan_id, version)
        except ApplicationError as exc:
            return _dump(exc.to_dict())
        if not self._actor.can_read_all and rec.created_by != self._actor.username:
            return _dump({"error": "plan not found"})
        self._emit(rec)
        return _dump(self._card(rec))


class BuiltinChatBackend:
    """内置对话后端：pydantic-ai 流式智能体 + bacmap 工具面。"""

    def __init__(
        self,
        home: Path,
        engine: Any,
        llm_config: LlmConfig,
        chat_config: BuiltinChatConfig,
        model_override: Any = None,
    ) -> None:
        self._home = Path(home)
        self._engine = engine
        self._llm_config = llm_config
        self._chat_config = chat_config
        self._model_override = model_override

    # ---- 端点与数据级别 ---------------------------------------------------------

    def resolve_chat_endpoint(self) -> tuple[LlmEndpoint, DataClass]:
        endpoint = self._llm_config.resolve(self._chat_config.purpose)
        if endpoint is None and self._chat_config.purpose != "interpretation":
            endpoint = self._llm_config.resolve("interpretation")
        if endpoint is None:
            raise RuntimeError(
                "no enabled LLM endpoint for chat purpose "
                f"{self._chat_config.purpose!r} (or 'interpretation')"
            )
        ceiling = self._llm_config.policy.ai_max_data_class
        if endpoint.location == "cloud":
            from bacmap.config import debug_allow_cloud_d4

            policy = self._llm_config.policy.cloud_max_data_class
            cloud_cap = (
                policy
                if policy <= DataClass.D2 or debug_allow_cloud_d4()
                else DataClass.D2
            )
            ceiling = min(ceiling, cloud_cap)
        return endpoint, ceiling

    # ---- 说明书 -----------------------------------------------------------------

    def _instructions(self, ctx: ChatRunContext) -> str:
        from bacmap.agent.instructions import external_operating_rules

        base = external_operating_rules()
        web_rules = (
            "你运行在 bacmap Web 控制台的对话面板中，而不是外部 MCP 客户端。"
            "计划确认由用户在控制台里点击计划卡片的确认按钮完成（或 CLI）；"
            "你**绝不能**声称自己已确认计划，也不能要求用户跳过确认。"
            "回答时引用具体的样本/run/task 标识；用户角色为 "
            f"{ctx.actor.role}，严格遵守当前数据级别上限，不要输出超出权限的数据。"
        )
        parts = [base, web_rules]
        extra = self._chat_config.system_prompt_extra.strip()
        if extra:
            parts.append(extra)
        page = ctx.page_context
        if page is not None and (page.entity_type or page.route):
            parts.append(
                "当前用户正在浏览: "
                f"{page.entity_type} {page.entity_id} ({page.route})".strip()
            )
        return "\n".join(parts)

    # ---- 工具面 -----------------------------------------------------------------

    def _registry_tools(self, ceiling: DataClass, read_all: bool) -> list[Tool]:
        from bacmap.tools import registry

        tools: list[Tool] = []
        for spec in registry.list_specs():
            if spec.effect not in (Effect.READ, Effect.COMPUTE):
                continue
            if spec.legacy_schema is None or spec.legacy_handler is None:
                continue
            if read_all:
                if spec.output_data_class > ceiling:
                    continue
            elif spec.output_data_class != DataClass.D0:
                continue
            tools.append(self._wrap_legacy(spec.name, spec.description, spec))
        return tools

    @staticmethod
    def _wrap_legacy(name: str, description: str, spec: Any) -> Tool:
        def run(**kwargs: Any) -> str:
            try:
                return str(
                    spec.legacy_handler({k: v for k, v in kwargs.items() if v is not None})
                )
            except Exception as exc:
                return _dump({"error": _safe_error(exc)})

        schema = dict(spec.legacy_schema.get("parameters") or {"type": "object"})
        return Tool.from_schema(run, name=name, description=description, json_schema=schema)

    def _task_tools(
        self, ctx: ChatRunContext, ceiling: DataClass, side: list[AgUiEvent]
    ) -> list[Tool]:
        tooling = _TaskTooling(self._engine, self._home, ctx.actor, ceiling, side)
        return tooling.tools()

    def _plan_tools(self, ctx: ChatRunContext, side: list[AgUiEvent]) -> list[Tool]:
        from bacmap.application.plans import PlanService

        service = PlanService(self._engine, Path(self._engine.db))
        tooling = _PlanTooling(service, self._engine, ctx.actor, side)
        return [
            Tool(
                tooling.create_plan,
                name="bacmap_create_plan",
                description=(
                    "Create an analysis plan with typed parameters. Nothing runs until "
                    "the user confirms this exact version in the bacmap Web console or CLI."
                ),
            ),
            Tool(
                tooling.revise_plan,
                name="bacmap_revise_plan",
                description="Replace the tasks of an unconfirmed or rejected plan (new version).",
            ),
            Tool(
                tooling.get_plan,
                name="bacmap_get_plan",
                description="Get a plan's state, parameters, hash and task_ids after confirmation.",
            ),
        ]

    def _build_tools(
        self, ctx: ChatRunContext, ceiling: DataClass, side: list[AgUiEvent]
    ) -> list[Tool]:
        tools = self._registry_tools(ceiling, ctx.actor.can_read_all)
        tools.extend(self._task_tools(ctx, ceiling, side))
        tools.extend(self._plan_tools(ctx, side))
        return tools

    # ---- 历史转换 -----------------------------------------------------------------

    def _model_history(self, history: list[ChatMessage]) -> list[Any]:
        bound = max(2, self._chat_config.max_history_messages)
        messages: list[Any] = []
        for msg in history[-bound:]:
            if msg.role == "user" and msg.content.strip():
                messages.append(ModelRequest([UserPromptPart(content=msg.content)]))
            elif msg.role == "assistant" and msg.content.strip():
                messages.append(ModelResponse([TextPart(content=msg.content)]))
        return messages

    # ---- 流式运行 -----------------------------------------------------------------

    def _build_model(self, endpoint: LlmEndpoint) -> Any:
        if self._model_override is not None:
            return self._model_override
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        api_key = "local"
        if endpoint.api_key_env:
            api_key = os.environ.get(endpoint.api_key_env, "missing")
        return OpenAIChatModel(
            endpoint.model,
            provider=OpenAIProvider(base_url=endpoint.base_url, api_key=api_key),
        )

    async def run_stream(self, ctx: ChatRunContext) -> AsyncIterator[AgUiEvent]:
        yield RunStartedEvent(threadId=ctx.thread_id, runId=ctx.run_id)
        try:
            endpoint, ceiling = self.resolve_chat_endpoint()
        except Exception as exc:
            yield RunErrorEvent(message=_safe_error(exc))
            return
        yield StateSnapshotEvent(
            snapshot={
                "session_id": ctx.session_id,
                "backend": "builtin",
                "role": ctx.actor.role,
                "endpoint": endpoint.name,
                "location": endpoint.location,
                "data_class_ceiling": ceiling.name,
            }
        )
        sem = _endpoint_semaphore(endpoint)
        was_queued = sem.locked()
        if was_queued:
            yield CustomEvent(
                name="bacmap.queue_status",
                value={"queued": True, "endpoint": endpoint.name},
            )
        async with sem:
            if was_queued:
                yield CustomEvent(
                    name="bacmap.queue_status",
                    value={"queued": False, "endpoint": endpoint.name},
                )
            side: list[AgUiEvent] = []
            try:
                agent = Agent(
                    self._build_model(endpoint),
                    instructions=self._instructions(ctx),
                    tools=self._build_tools(ctx, ceiling, side),
                )
                async for event in self._stream_agent(agent, ctx, side):
                    yield event
            except Exception as exc:
                logger.warning("chat builtin run failed: %s", exc, exc_info=True)
                yield RunErrorEvent(message=_safe_error(exc))
                return

    async def _stream_agent(
        self, agent: Any, ctx: ChatRunContext, side: list[AgUiEvent]
    ) -> AsyncIterator[AgUiEvent]:
        history = self._model_history(ctx.history)
        async with agent.iter(ctx.message, message_history=history) as run:
            async for node in run:
                if isinstance(node, ModelRequestNode):
                    async with node.stream(run.ctx) as req_stream:
                        async for event in self._stream_model_events(req_stream, ctx):
                            yield event
                elif isinstance(node, CallToolsNode):
                    async with node.stream(run.ctx) as handle_stream:
                        async for event in self._stream_tool_events(handle_stream, side):
                            yield event
        yield RunFinishedEvent(threadId=ctx.thread_id, runId=ctx.run_id)

    async def _stream_model_events(
        self, req_stream: Any, ctx: ChatRunContext
    ) -> AsyncIterator[AgUiEvent]:
        text_ids: dict[int, str] = {}
        thinking_open: dict[int, bool] = {}
        async for event in req_stream:
            if isinstance(event, PartStartEvent):
                async for out in self._part_start_events(event, text_ids, thinking_open):
                    yield out
            elif isinstance(event, PartDeltaEvent):
                delta = event.delta
                if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
                    if not thinking_open.get(event.index):
                        # 部分实现在 delta 前不发 PartStart——懒开思考段，避免前端悬空。
                        thinking_open[event.index] = True
                        yield ThinkingStartEvent()
                        yield ThinkingTextMessageStartEvent()
                    yield ThinkingTextMessageContentEvent(delta=delta.content_delta)
                elif isinstance(delta, TextPartDelta) and delta.content_delta:
                    mid = text_ids.get(event.index)
                    if mid is not None:
                        yield TextMessageContentEvent(
                            messageId=mid, delta=delta.content_delta
                        )
            elif isinstance(event, PartEndEvent):
                part = event.part
                if isinstance(part, ThinkingPart) and thinking_open.pop(event.index, False):
                    yield ThinkingTextMessageEndEvent()
                    yield ThinkingEndEvent()
                elif isinstance(part, TextPart) and event.index in text_ids:
                    yield TextMessageEndEvent(messageId=text_ids.pop(event.index))
        # 流中断/上游缺 PartEnd：关闭仍开放的思考段与文本消息，前端不得悬停。
        for _index in sorted(thinking_open):
            yield ThinkingTextMessageEndEvent()
            yield ThinkingEndEvent()
        for index in sorted(text_ids):
            yield TextMessageEndEvent(messageId=text_ids[index])

    @staticmethod
    async def _part_start_events(
        event: Any,
        text_ids: dict[int, str],
        thinking_open: dict[int, bool],
    ) -> AsyncIterator[AgUiEvent]:
        part = event.part
        if isinstance(part, ThinkingPart):
            thinking_open[event.index] = True
            yield ThinkingStartEvent()
            yield ThinkingTextMessageStartEvent()
            if part.content:
                yield ThinkingTextMessageContentEvent(delta=part.content)
        elif isinstance(part, TextPart):
            message_id = new_id("cm_msg_")
            text_ids[event.index] = message_id
            yield TextMessageStartEvent(messageId=message_id)
            if part.content:
                yield TextMessageContentEvent(messageId=message_id, delta=part.content)

    async def _stream_tool_events(
        self, handle_stream: Any, side: list[AgUiEvent]
    ) -> AsyncIterator[AgUiEvent]:
        async for event in handle_stream:
            if isinstance(event, FunctionToolCallEvent):
                part = event.part
                args = part.args
                if not isinstance(args, str):
                    args = _dump(args) if args else ""
                yield ToolCallStartEvent(
                    toolCallId=part.tool_call_id,
                    toolCallName=part.tool_name,
                )
                if args:
                    yield ToolCallArgsEvent(toolCallId=part.tool_call_id, delta=args)
                yield ToolCallEndEvent(toolCallId=part.tool_call_id)
            elif isinstance(event, FunctionToolResultEvent):
                raw = event.part.content
                text = raw if isinstance(raw, str) else _dump(raw)
                yield ToolCallResultEvent(
                    messageId=new_id("cm_tool_"),
                    toolCallId=event.part.tool_call_id,
                    content=text[:_TOOL_RESULT_WIRE_LIMIT],
                )
                while side:
                    yield side.pop(0)
