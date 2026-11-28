"""Web 控制台对话 API（/api/v1/chat/*，v1.10.x P1）。

- 会话/消息持久化在 ``store.chat``（严格 owner 隔离，跨用户一律 404）；
- 运行入口 ``POST /chat/sessions/{id}/run`` 以 SSE（AG-UI 事件）流式返回；
  同步路由纪律的例外：本路由为 async（SSE 流式本质），DBOS 同步面只在
  后端工具的 worker 线程内触达；
- 写操作一律过 CSRF；鉴权按 ``Permission.DATA_READ``（USER 可对话，但工具
  面/计划类型在后端按角色收敛）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bacmap.agent.chat.agui import encode_sse
from bacmap.agent.chat.config import load_chat_config
from bacmap.agent.chat.service import ChatOrchestrator
from bacmap.agent.chat.types import ChatActor, PageContext
from bacmap.interfaces.web.auth import principal_of, verify_csrf
from bacmap.interfaces.web.rbac import Permission, require_permission
from bacmap.store.chat import ChatStore
from bacmap.store.users import Role
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

logger = logging.getLogger(__name__)


def _require_csrf(request: Request) -> None:
    if not verify_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(403, "CSRF check failed")


def _chat_actor(request: Request) -> ChatActor:
    principal = principal_of(request)
    if principal is not None:
        privileged = principal.role in (Role.ADMIN, Role.ANALYST)
        return ChatActor(
            user_id=principal.user_id,
            username=principal.username,
            role=principal.role.value,
            can_read_all=privileged,
            can_confirm_plans=privileged,
            is_admin=principal.is_admin,
        )
    return ChatActor(
        user_id="local",
        username="web",
        role="admin",
        can_read_all=True,
        can_confirm_plans=True,
        is_admin=True,
    )


def _orchestrator(request: Request, engine: DbosTaskEngine) -> ChatOrchestrator:
    override = getattr(request.app.state, "chat_orchestrator", None)
    if override is not None:
        return override
    config = getattr(request.app.state, "chat_config", None)
    if config is None:
        from bacmap.config import config_path as _active_config_path

        config = load_chat_config(_active_config_path(engine.home))
    return ChatOrchestrator(
        Path(engine.home),
        engine,
        config,
        builtin_backend_factory=lambda: _builtin_backend(engine, config),
    )


def _builtin_backend(engine: DbosTaskEngine, config: Any) -> Any:
    from bacmap.agent.llm.chat import BuiltinChatBackend
    from bacmap.agent.llm.endpoints import load_llm_config
    from bacmap.config import config_path as _active_config_path

    return BuiltinChatBackend(
        Path(engine.home),
        engine,
        load_llm_config(_active_config_path(engine.home)),
        config.builtin,
    )


def chat_capabilities_for_request(request: Request, engine: DbosTaskEngine) -> dict[str, Any]:
    orch = _orchestrator(request, engine)
    return orch.capabilities_payload(_chat_actor(request))


class SessionCreateBody(BaseModel):
    title: str = Field(default="", max_length=200)
    backend_id: str = Field(default="builtin", max_length=64)


class SessionPatchBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    backend_id: str | None = Field(default=None, max_length=64)


class RunBody(BaseModel):
    message: str = ""
    backend_id: str | None = None
    page_context: PageContext | None = None
    thread_id: str | None = None
    run_id: str | None = None
    # AG-UI RunAgentInput 兼容形状：messages 末条 user 消息作为输入。
    messages: list[dict[str, Any]] | None = None

    def effective_message(self) -> str:
        if self.message.strip():
            return self.message
        for item in reversed(self.messages or []):
            if item.get("role") == "user":
                content = item.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    text = "".join(
                        str(p.get("text", ""))
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                    if text.strip():
                        return text
        return ""


def _store(engine: DbosTaskEngine) -> ChatStore:
    return ChatStore(Path(engine.home) / "data" / "bacmap.sqlite")


def build_chat_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    _session_read_routes(router, engine)
    _session_write_routes(router, engine)
    _run_route(router, engine)


def _session_read_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.get("/chat/config")
    def chat_config_endpoint(request: Request) -> dict[str, Any]:
        require_permission(request, Permission.DATA_READ)
        orch = _orchestrator(request, engine)
        return orch.capabilities_payload(_chat_actor(request))

    @router.get("/chat/sessions")
    def chat_sessions(request: Request, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        with _store(engine) as store:
            items = store.list_sessions(actor.user_id, limit=limit, offset=offset)
        return {"items": [s.model_dump(mode="json") for s in items]}

    @router.get("/chat/sessions/{session_id}")
    def chat_get_session(session_id: str, request: Request) -> dict[str, Any]:
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        with _store(engine) as store:
            session = store.get_session(session_id, actor.user_id)
            if session is None:
                raise HTTPException(404, "chat session not found")
            messages = store.list_messages(session_id, actor.user_id)
        return {
            "session": session.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in messages],
        }


def _session_write_routes(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.post("/chat/sessions")
    def chat_create_session(request: Request, body: SessionCreateBody) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        with _store(engine) as store:
            session = store.create_session(
                actor.user_id, title=body.title, backend_id=body.backend_id
            )
        return session.model_dump(mode="json")

    @router.patch("/chat/sessions/{session_id}")
    def chat_patch_session(
        session_id: str, request: Request, body: SessionPatchBody
    ) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        with _store(engine) as store:
            session = store.update_session(
                session_id, actor.user_id, title=body.title, backend_id=body.backend_id
            )
        if session is None:
            raise HTTPException(404, "chat session not found")
        return session.model_dump(mode="json")

    @router.delete("/chat/sessions/{session_id}")
    def chat_delete_session(session_id: str, request: Request) -> dict[str, Any]:
        _require_csrf(request)
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        with _store(engine) as store:
            deleted = store.delete_session(session_id, actor.user_id)
        if not deleted:
            raise HTTPException(404, "chat session not found")
        try:
            from bacmap.agent.chat.external import close_external_session

            close_external_session(session_id)
        except Exception:  # 子进程清理失败不影响删除
            logger.debug("chat: external session cleanup failed", exc_info=True)
        return {"deleted": True, "session_id": session_id}


def _run_route(router: APIRouter, engine: DbosTaskEngine) -> None:
    @router.post("/chat/sessions/{session_id}/run")
    async def chat_run(session_id: str, request: Request, body: RunBody) -> StreamingResponse:
        _require_csrf(request)
        require_permission(request, Permission.DATA_READ)
        actor = _chat_actor(request)
        orch = _orchestrator(request, engine)
        if not orch.capabilities_payload(actor)["enabled"]:
            raise HTTPException(400, "chat is disabled (web.chat.mode = off)")
        with _store(engine) as store:
            session = store.get_session(session_id, actor.user_id)
            if session is None:
                raise HTTPException(404, "chat session not found")
        message = body.effective_message()
        if not message.strip():
            raise HTTPException(400, "message must not be empty")
        try:
            orch.validate_backend(body.backend_id or session.backend_id or None, actor)
        except KeyError:
            raise HTTPException(404, "chat backend not available for this user") from None
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from None

        async def events() -> Any:
            try:
                async for event in orch.stream_run(
                    session_id,
                    message,
                    actor,
                    backend_id=body.backend_id,
                    page_context=body.page_context,
                    thread_id=body.thread_id,
                    run_id=body.run_id,
                ):
                    yield encode_sse(event)
            except KeyError:
                return
            except Exception as exc:  # SSE 已开始，错误只能进流
                from bacmap.agent.chat.agui import RunErrorEvent

                logger.warning("chat run failed: %s", exc, exc_info=True)
                yield encode_sse(RunErrorEvent(message=f"{type(exc).__name__}: {exc}"[:300]))

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
