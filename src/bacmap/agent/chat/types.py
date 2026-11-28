"""对话编排的类型：操作者、页面上下文、后端描述与运行上下文。

``ChatBackend`` 是所有后端（内置 pydantic-ai / 外部协议）的统一协议；
实现端按 AG-UI 事件流产出，编排层负责持久化与转发。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bacmap.agent.chat.agui import AgUiEvent
from bacmap.store.chat import ChatMessage


class ChatActor(BaseModel):
    """当前对话操作者（服务端认定，不接受客户端自填）。"""

    user_id: str
    username: str
    role: str  # "admin" | "analyst" | "user"
    can_read_all: bool
    can_confirm_plans: bool
    is_admin: bool


class PageContext(BaseModel):
    """用户发起对话时正在浏览的页面（提示注入用，不构成权限依据）。"""

    route: str = ""
    entity_type: str = ""
    entity_id: str = ""
    title: str = ""


class BackendInfo(BaseModel):
    id: str
    name: str
    kind: Literal["builtin", "external"]
    protocol: str
    available: bool
    reason: str = ""


class ChatRunContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    thread_id: str
    run_id: str
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    actor: ChatActor
    page_context: PageContext | None = None
    backend_id: str = "builtin"


class ChatBackend(Protocol):
    """对话后端协议：输入运行上下文，产出 AG-UI 事件流。"""

    def run_stream(self, ctx: ChatRunContext) -> AsyncIterator[AgUiEvent]: ...
