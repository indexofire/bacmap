"""对话编排层：会话归属校验、后端解析、AG-UI 事件转发与持久化。

编排层本身不含任何 LLM/协议实现——后端经工厂注入（内置 pydantic-ai
后端在 ``bacmap.agent.llm.chat``，外部协议适配器在 P2 接入）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from bacmap.agent.chat.agui import (
    AgUiEvent,
    CustomEvent,
    TextMessageContentEvent,
    ThinkingTextMessageContentEvent,
    ToolCallArgsEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    new_id,
)
from bacmap.agent.chat.config import WebChatConfig
from bacmap.agent.chat.types import (
    BackendInfo,
    ChatActor,
    ChatBackend,
    ChatRunContext,
    PageContext,
)
from bacmap.store.chat import ChatStore
from bacmap.tools.spec import DataClass

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 16_000
_CARD_EVENTS = ("bacmap.plan_card", "bacmap.task_ref")

BuiltinFactory = Callable[[], ChatBackend]
ExternalFactory = Callable[[str], ChatBackend | None]


def _builtin_availability(home: Path, purpose: str) -> tuple[bool, str]:
    """内置后端可用性：purpose（或 interpretation 回退）能解析到启用端点。"""
    from bacmap.agent.llm.endpoints import load_llm_config
    from bacmap.config import config_path

    try:
        config = load_llm_config(config_path(home))
    except Exception as exc:  # 配置损坏不阻断 Web 启动，仅标记不可用
        logger.warning("chat builtin: llm config unreadable: %s", exc)
        return False, "LLM 配置不可读，内置对话不可用"
    endpoint = config.resolve(purpose)
    if endpoint is None and purpose != "interpretation":
        endpoint = config.resolve("interpretation")
    if endpoint is None:
        return False, (
            "未配置可用的 LLM 端点：请在 config.toml 的 [llm.endpoints] 配置端点，"
            "并在 [llm.routing] 指派 chat 或 interpretation 用途"
        )
    return True, ""


class ChatOrchestrator:
    """会话/后端/事件流的编排（Web API 层与后端实现之间）。"""

    def __init__(
        self,
        home: Path,
        engine: Any,
        chat_config: WebChatConfig,
        *,
        builtin_backend_factory: BuiltinFactory | None = None,
        external_backend_factory: ExternalFactory | None = None,
    ) -> None:
        self._home = Path(home)
        self._engine = engine
        self._config = chat_config
        self._builtin_factory = builtin_backend_factory
        self._external_factory = external_backend_factory
        self._db = self._home / "data" / "bacmap.sqlite"

    # ---- 能力面 ---------------------------------------------------------------

    def available_backends(self, actor: ChatActor) -> list[BackendInfo]:
        out: list[BackendInfo] = []
        if self._config.mode in ("builtin", "both"):
            available, reason = _builtin_availability(
                self._home, self._config.builtin.purpose
            )
            if self._builtin_factory is not None:
                available, reason = True, ""
            out.append(
                BackendInfo(
                    id="builtin",
                    name="bacmap 内置助手",
                    kind="builtin",
                    protocol="pydantic-ai",
                    available=available,
                    reason=reason,
                )
            )
        if self._config.mode in ("external", "both"):
            for ext in self._config.external:
                if not ext.enabled:
                    continue
                if not (actor.is_admin or actor.role in ext.allowed_roles):
                    continue
                if self._external_factory is not None:
                    available = self._external_factory(ext.id) is not None
                    reason = "" if available else "外部后端构造失败"
                else:
                    from bacmap.agent.chat.external import check_external_availability

                    available, reason = check_external_availability(ext)
                out.append(
                    BackendInfo(
                        id=ext.id,
                        name=ext.name,
                        kind="external",
                        protocol=ext.protocol,
                        available=available,
                        reason=reason,
                    )
                )
        return out

    def capabilities_payload(self, actor: ChatActor) -> dict[str, Any]:
        return {
            "enabled": self._config.enabled,
            "mode": self._config.mode,
            "default_backend": self._config.default_backend,
            "backends": [
                b.model_dump(mode="json") for b in self.available_backends(actor)
            ],
            "can_confirm_plans": actor.can_confirm_plans,
        }

    # ---- 后端解析 ---------------------------------------------------------------

    def _resolve_backend(self, backend_id: str, actor: ChatActor) -> ChatBackend:
        if not self._config.enabled:
            raise RuntimeError("chat is disabled (web.chat.mode = off)")
        info = {b.id: b for b in self.available_backends(actor)}
        if backend_id not in info:
            raise KeyError(f"backend not available for this user: {backend_id}")
        if backend_id == "builtin":
            if self._config.mode not in ("builtin", "both"):
                raise KeyError(f"backend disabled by mode: {backend_id}")
            if self._builtin_factory is None:
                raise RuntimeError("builtin chat backend is not configured")
            return self._builtin_factory()
        if self._external_factory is not None:
            backend = self._external_factory(backend_id)
            if backend is not None:
                return backend
        for ext in self._config.external:
            if ext.id != backend_id or not ext.enabled:
                continue
            if not (actor.is_admin or actor.role in ext.allowed_roles):
                break
            from bacmap.agent.chat.external import build_external_backend

            return build_external_backend(ext, self._home)
        raise RuntimeError(f"external backend not available: {backend_id}")

    def validate_backend(self, backend_id: str | None, actor: ChatActor) -> None:
        """运行前置校验：后端对该操作者可用，否则 KeyError/RuntimeError。"""
        self._resolve_backend(
            backend_id or self._config.default_backend, actor,
        )

    # ---- 运行与持久化 -------------------------------------------------------------

    async def stream_run(
        self,
        session_id: str,
        message: str,
        actor: ChatActor,
        *,
        backend_id: str | None = None,
        page_context: PageContext | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[AgUiEvent]:
        text = message.strip()
        if not text:
            raise ValueError("message must not be empty")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message too long (>{MAX_MESSAGE_CHARS} chars)")

        with ChatStore(self._db) as store:
            session = store.get_session(session_id, actor.user_id)
            if session is None:
                raise KeyError(session_id)
            backend = self._resolve_backend(
                backend_id or session.backend_id or self._config.default_backend,
                actor,
            )
            history = store.list_recent_messages(
                session_id, actor.user_id,
                limit=self._config.builtin.max_history_messages,
            )
            store.append_message(session_id, actor.user_id, role="user", content=text)

        ctx = ChatRunContext(
            session_id=session_id,
            thread_id=thread_id or session_id,
            run_id=run_id or new_id("run_"),
            message=text,
            history=history,
            actor=actor,
            page_context=page_context,
            backend_id=backend_id or session.backend_id,
        )
        collector = _RunCollector(self._db, session_id, actor.user_id)
        try:
            async for event in backend.run_stream(ctx):
                collector.collect(event)
                yield event
        finally:
            collector.persist(ctx.backend_id)


class _RunCollector:
    """累积一次运行的 assistant 产出（文本/思考/工具调用/卡片）并落库。"""

    def __init__(self, db: Path, session_id: str, owner_user_id: str) -> None:
        self._db = db
        self._session_id = session_id
        self._owner = owner_user_id
        self._content: list[str] = []
        self._thinking: list[str] = []
        self._tool_calls: dict[str, dict[str, Any]] = {}
        self._tool_order: list[str] = []
        self._cards: list[dict[str, Any]] = []
        self._linked: set[str] = set()

    def collect(self, event: AgUiEvent) -> None:
        if isinstance(event, TextMessageContentEvent):
            self._content.append(event.delta)
        elif isinstance(event, ThinkingTextMessageContentEvent):
            self._thinking.append(event.delta)
        elif isinstance(event, ToolCallStartEvent):
            self._tool_calls[event.tool_call_id] = {
                "id": event.tool_call_id,
                "name": event.tool_call_name,
                "args": "",
                "result": "",
            }
            self._tool_order.append(event.tool_call_id)
        elif isinstance(event, ToolCallArgsEvent):
            entry = self._tool_calls.get(event.tool_call_id)
            if entry is not None:
                entry["args"] += event.delta
        elif isinstance(event, ToolCallResultEvent):
            entry = self._tool_calls.get(event.tool_call_id)
            if entry is not None:
                entry["result"] = event.content[:4000]
        elif isinstance(event, CustomEvent) and event.name in _CARD_EVENTS:
            self._collect_card(event)

    def _collect_card(self, event: CustomEvent) -> None:
        value = event.value if isinstance(event.value, dict) else {"value": event.value}
        self._cards.append({"kind": event.name, **value})
        ids = value.get("task_ids") or []
        single = value.get("task_id")
        if isinstance(single, str) and single:
            ids = [*ids, single]
        for tid in ids:
            if isinstance(tid, str) and tid and tid not in self._linked:
                self._linked.add(tid)
                try:
                    with ChatStore(self._db) as store:
                        store.link_task(self._session_id, self._owner, tid)
                except KeyError:
                    pass

    def persist(self, backend_id: str) -> None:
        content = "".join(self._content)
        thinking = "".join(self._thinking)
        calls = [self._tool_calls[k] for k in self._tool_order]
        if not (content or thinking or calls or self._cards):
            return
        try:
            with ChatStore(self._db) as store:
                store.append_message(
                    self._session_id,
                    self._owner,
                    role="assistant",
                    content=content,
                    thinking=thinking,
                    tool_calls=calls,
                    cards=self._cards,
                    backend_id=backend_id,
                )
        except Exception:
            logger.warning(
                "chat: failed to persist assistant message session=%s",
                self._session_id,
                exc_info=True,
            )


def ceiling_for(ai_max: DataClass, location: str, cloud_max: DataClass) -> DataClass:
    """ADR-16 生效上限：min(AI 总上限, cloud 位置上限)。供编排/后端共用。"""
    ceiling = ai_max
    if location == "cloud":
        from bacmap.config import debug_allow_cloud_d4

        cloud_cap = (
            cloud_max
            if cloud_max <= DataClass.D2 or debug_allow_cloud_d4()
            else DataClass.D2
        )
        ceiling = min(ceiling, cloud_cap)
    return ceiling
