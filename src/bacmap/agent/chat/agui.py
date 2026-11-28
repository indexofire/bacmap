"""AG-UI v0.1 协议事件模型（SSE wire 格式）。

事件以 JSON 序列化：``type`` 为判别字段，字段名 camelCase（alias），
``None`` 字段不出现在线上（``exclude_none``）。``encode_sse`` 产出
``data: {...}\n\n`` 帧，供 ``text/event-stream`` 响应逐条写出。
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(8)


def _ts() -> int:
    return int(time.time() * 1000)


class AgUiBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timestamp: int = Field(default_factory=_ts)


class RunStartedEvent(AgUiBase):
    type: Literal["RUN_STARTED"] = "RUN_STARTED"
    thread_id: str = Field(alias="threadId")
    run_id: str = Field(alias="runId")


class RunFinishedEvent(AgUiBase):
    type: Literal["RUN_FINISHED"] = "RUN_FINISHED"
    thread_id: str = Field(alias="threadId")
    run_id: str = Field(alias="runId")
    result: Any = None


class RunErrorEvent(AgUiBase):
    type: Literal["RUN_ERROR"] = "RUN_ERROR"
    message: str
    code: str | None = None


class ThinkingStartEvent(AgUiBase):
    type: Literal["THINKING_START"] = "THINKING_START"
    title: str | None = None


class ThinkingTextMessageStartEvent(AgUiBase):
    type: Literal["THINKING_TEXT_MESSAGE_START"] = "THINKING_TEXT_MESSAGE_START"


class ThinkingTextMessageContentEvent(AgUiBase):
    type: Literal["THINKING_TEXT_MESSAGE_CONTENT"] = "THINKING_TEXT_MESSAGE_CONTENT"
    delta: str


class ThinkingTextMessageEndEvent(AgUiBase):
    type: Literal["THINKING_TEXT_MESSAGE_END"] = "THINKING_TEXT_MESSAGE_END"


class ThinkingEndEvent(AgUiBase):
    type: Literal["THINKING_END"] = "THINKING_END"


class TextMessageStartEvent(AgUiBase):
    type: Literal["TEXT_MESSAGE_START"] = "TEXT_MESSAGE_START"
    message_id: str = Field(alias="messageId")
    role: str = "assistant"


class TextMessageContentEvent(AgUiBase):
    type: Literal["TEXT_MESSAGE_CONTENT"] = "TEXT_MESSAGE_CONTENT"
    message_id: str = Field(alias="messageId")
    delta: str


class TextMessageEndEvent(AgUiBase):
    type: Literal["TEXT_MESSAGE_END"] = "TEXT_MESSAGE_END"
    message_id: str = Field(alias="messageId")


class ToolCallStartEvent(AgUiBase):
    type: Literal["TOOL_CALL_START"] = "TOOL_CALL_START"
    tool_call_id: str = Field(alias="toolCallId")
    tool_call_name: str = Field(alias="toolCallName")
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")


class ToolCallArgsEvent(AgUiBase):
    type: Literal["TOOL_CALL_ARGS"] = "TOOL_CALL_ARGS"
    tool_call_id: str = Field(alias="toolCallId")
    delta: str


class ToolCallEndEvent(AgUiBase):
    type: Literal["TOOL_CALL_END"] = "TOOL_CALL_END"
    tool_call_id: str = Field(alias="toolCallId")


class ToolCallResultEvent(AgUiBase):
    type: Literal["TOOL_CALL_RESULT"] = "TOOL_CALL_RESULT"
    message_id: str = Field(alias="messageId")
    tool_call_id: str = Field(alias="toolCallId")
    content: str
    role: str = "tool"


class StateSnapshotEvent(AgUiBase):
    type: Literal["STATE_SNAPSHOT"] = "STATE_SNAPSHOT"
    snapshot: dict[str, Any]


class StateDeltaEvent(AgUiBase):
    type: Literal["STATE_DELTA"] = "STATE_DELTA"
    delta: list[dict[str, Any]]


class CustomEvent(AgUiBase):
    type: Literal["CUSTOM"] = "CUSTOM"
    name: str
    value: Any


AgUiEvent = (
    RunStartedEvent
    | RunFinishedEvent
    | RunErrorEvent
    | ThinkingStartEvent
    | ThinkingTextMessageStartEvent
    | ThinkingTextMessageContentEvent
    | ThinkingTextMessageEndEvent
    | ThinkingEndEvent
    | TextMessageStartEvent
    | TextMessageContentEvent
    | TextMessageEndEvent
    | ToolCallStartEvent
    | ToolCallArgsEvent
    | ToolCallEndEvent
    | ToolCallResultEvent
    | StateSnapshotEvent
    | StateDeltaEvent
    | CustomEvent
)


def encode_sse(event: AgUiEvent) -> str:
    payload = event.model_dump_json(by_alias=True, exclude_none=True)
    return f"data: {payload}\n\n"
