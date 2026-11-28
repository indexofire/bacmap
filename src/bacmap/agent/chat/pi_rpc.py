"""Pi RPC 适配器（``pi --mode rpc``）：JSONL stdin/stdout 协议。

Pi 的 RPC 模式以 LF 分隔 JSON 记录通信：客户端发送
``{"id": N, "type": "prompt", "message": ...}``，代理流式产出
``message_update`` / ``tool_execution_*`` / ``agent_end`` / ``agent_settled``。
子进程按会话持久复用（多轮对话同一进程），中止时写入 ``{"type": "abort"}``。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from bacmap.agent.chat.agui import (
    AgUiEvent,
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
from bacmap.agent.chat.config import ExternalAgentConfig
from bacmap.agent.chat.external import (
    TOOL_RESULT_WIRE_LIMIT,
    extract_bacmap_cards,
    format_prompt_with_context,
    resolve_external_command,
)
from bacmap.agent.chat.types import ChatRunContext

logger = logging.getLogger(__name__)

_AGENT_SETTLE_GRACE_S = 0.15


def _result_text(result: Any) -> str:
    """Pi 工具结果提取可读文本（content 文本块数组或 JSON 回退）。"""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False) if result else ""
    content = result.get("content")
    if isinstance(content, list):
        parts = [
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(p for p in parts if p)
        if text:
            return text
    return json.dumps(result, ensure_ascii=False)


class PiRpcEventTranslator:
    """单次运行内把 Pi JSONL 记录翻译为 AG-UI 事件（有状态）。"""

    def __init__(self, *, can_confirm: bool) -> None:
        self._can_confirm = can_confirm
        self._thinking_open = False
        self._message_id: str | None = None
        self._tool_started: set[str] = set()

    def _open_thinking(self) -> list[AgUiEvent]:
        if self._thinking_open:
            return []
        self._thinking_open = True
        return [ThinkingStartEvent(), ThinkingTextMessageStartEvent()]

    def _close_thinking(self) -> list[AgUiEvent]:
        if not self._thinking_open:
            return []
        self._thinking_open = False
        return [ThinkingTextMessageEndEvent(), ThinkingEndEvent()]

    def _open_text(self) -> list[AgUiEvent]:
        if self._message_id is not None:
            return []
        self._message_id = new_id("cm_msg_")
        return [TextMessageStartEvent(messageId=self._message_id)]

    def _close_text(self) -> list[AgUiEvent]:
        if self._message_id is None:
            return []
        mid = self._message_id
        self._message_id = None
        return [TextMessageEndEvent(messageId=mid)]

    # ---- message_update ----------------------------------------------------------

    def _assistant_event(self, sub: dict[str, Any]) -> list[AgUiEvent]:
        kind = str(sub.get("type") or "")
        if kind == "thinking_start":
            return self._open_thinking()
        if kind == "thinking_delta":
            delta = str(sub.get("delta") or "")
            if not delta:
                return []
            return [*self._open_thinking(), ThinkingTextMessageContentEvent(delta=delta)]
        if kind == "thinking_end":
            return self._close_thinking()
        if kind == "text_start":
            return [*self._close_thinking(), *self._open_text()]
        if kind == "text_delta":
            delta = str(sub.get("delta") or "")
            if not delta:
                return []
            out = [*self._close_thinking(), *self._open_text()]
            out.append(
                TextMessageContentEvent(messageId=self._message_id or "", delta=delta)
            )
            return out
        if kind == "text_end":
            return self._close_text()
        if kind.startswith("toolcall_"):
            return self._toolcall_event(kind, sub)
        return []

    def _toolcall_event(self, kind: str, sub: dict[str, Any]) -> list[AgUiEvent]:
        tool_id = str(sub.get("toolCallId") or sub.get("id") or "")
        if not tool_id:
            return []
        if kind == "toolcall_start":
            self._tool_started.add(tool_id)
            name = str(sub.get("toolName") or sub.get("name") or "tool")
            return [ToolCallStartEvent(toolCallId=tool_id, toolCallName=name)]
        if kind == "toolcall_delta":
            delta = str(sub.get("delta") or "")
            return [ToolCallArgsEvent(toolCallId=tool_id, delta=delta)] if delta else []
        return [ToolCallEndEvent(toolCallId=tool_id)]

    # ---- 记录入口 ------------------------------------------------------------------

    def translate(self, rec: dict[str, Any]) -> list[AgUiEvent]:
        rtype = str(rec.get("type") or "")
        if rtype == "turn_end":
            return self._turn_end(rec)
        if rtype == "message_update":
            sub = rec.get("assistantMessageEvent")
            if isinstance(sub, dict):
                return self._assistant_event(sub)
            return []
        if rtype == "tool_execution_start":
            return self._exec_start(rec)
        if rtype == "tool_execution_end":
            return self._exec_end(rec)
        return []

    def _exec_start(self, rec: dict[str, Any]) -> list[AgUiEvent]:
        tool_id = str(rec.get("toolCallId") or "")
        if not tool_id or tool_id in self._tool_started:
            return []
        self._tool_started.add(tool_id)
        name = str(rec.get("toolName") or "tool")
        out: list[AgUiEvent] = [
            *self._close_thinking(),
            *self._close_text(),
            ToolCallStartEvent(toolCallId=tool_id, toolCallName=name),
        ]
        args = rec.get("args")
        if args:
            text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            out.append(ToolCallArgsEvent(toolCallId=tool_id, delta=text))
        out.append(ToolCallEndEvent(toolCallId=tool_id))
        return out

    def _exec_end(self, rec: dict[str, Any]) -> list[AgUiEvent]:
        tool_id = str(rec.get("toolCallId") or "")
        if not tool_id:
            return []
        name = str(rec.get("toolName") or "tool")
        text = _result_text(rec.get("result"))
        out: list[AgUiEvent] = [
            ToolCallResultEvent(
                messageId=new_id("cm_tool_"),
                toolCallId=tool_id,
                content=text[:TOOL_RESULT_WIRE_LIMIT],
            )
        ]
        if text:
            out.extend(extract_bacmap_cards(name, text, can_confirm=self._can_confirm))
        return out

    def _turn_end(self, rec: dict[str, Any]) -> list[AgUiEvent]:
        """模型调用失败（stopReason=error）必须浮现——否则用户只看到空回复。

        pi 把错误放在 assistant 消息的 ``errorMessage`` 字段（docs/message-types.md），
        此处整轮结束时翻译为 RunErrorEvent；流仍由 agent_settled 正常收尾。
        """
        msg = rec.get("message")
        if not isinstance(msg, dict):
            return []
        if str(msg.get("stopReason") or "") != "error":
            return []
        detail = str(msg.get("errorMessage") or "").strip() or "未知错误"
        provider = str(msg.get("provider") or "")
        model = str(msg.get("model") or "")
        origin = f"（{provider}/{model}）" if provider or model else ""
        return [
            *self.close(),
            RunErrorEvent(message=f"外部智能体模型调用失败{origin}: {detail}"),
        ]

    def close(self) -> list[AgUiEvent]:
        return [*self._close_thinking(), *self._close_text()]


# ---- 持久子进程池 -----------------------------------------------------------------


class _PiProcess:
    def __init__(self, cmd: list[str], cwd: Path) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.proc: asyncio.subprocess.Process | None = None
        self._next_id = 0

    def alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            start_new_session=True,
        )

    def write(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("Pi 子进程未启动")
        self.proc.stdin.write(json.dumps(payload).encode() + b"\n")

    async def readline(self) -> dict[str, Any] | None:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("Pi 子进程未启动")
        line = await self.proc.stdout.readline()
        if not line:
            return None
        try:
            rec = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        return rec if isinstance(rec, dict) else {}


class _PiPoolEntry:
    def __init__(self, process: _PiProcess) -> None:
        self.process = process
        self.lock = asyncio.Lock()


_PI_POOL: dict[tuple[str, str, Any], _PiPoolEntry] = {}


async def aclose_pi_session(backend_id: str = "", session_id: str = "") -> None:
    """按会话回收 Pi 子进程（kill+wait，须在拥有进程的循环内 await）。

    只 kill 不 wait 会留下半开传输层——会话删除等异步上下文必须经此收割。
    """
    doomed = [
        key
        for key in _PI_POOL
        if (not backend_id or key[0] == backend_id) and key[1] == session_id
    ]
    for key in doomed:
        entry = _PI_POOL.pop(key, None)
        if entry is None:
            continue
        proc = entry.process.proc
        if proc is None or proc.returncode is not None:
            continue
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)


async def reap_pi_pool() -> None:
    """kill 并 await 全部池化 Pi 子进程（测试拆除与服务关停用）。

    仅 ``kill`` 不 ``wait`` 会让 subprocess transport 半开，事件循环关闭后
    GC 触发 ``BaseSubprocessTransport.__del__`` 报 "Event loop is closed"。
    """
    entries = list(_PI_POOL.values())
    _PI_POOL.clear()
    for entry in entries:
        proc = entry.process.proc
        if proc is None or proc.returncode is not None:
            continue
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)


class PiRpcExternalBackend:
    """Pi RPC（``pi --mode rpc``）外部后端。"""

    def __init__(self, cfg: ExternalAgentConfig, home: Path) -> None:
        self._cfg = cfg
        self._home = Path(home)

    async def _acquire(self, ctx: ChatRunContext) -> _PiPoolEntry:
        key = (self._cfg.id, ctx.session_id, asyncio.get_running_loop())
        entry = _PI_POOL.get(key)
        if entry is not None and (
            entry.process.proc is None or entry.process.proc.returncode is not None
        ):
            _PI_POOL.pop(key, None)
            entry = None
        if entry is None:
            cmd = resolve_external_command(self._cfg)
            cwd = Path(self._cfg.workdir) if self._cfg.workdir else self._home
            process = _PiProcess(cmd, cwd)
            await process.start()
            entry = _PiPoolEntry(process)
            _PI_POOL[key] = entry
        return entry

    async def run_stream(self, ctx: ChatRunContext) -> AsyncIterator[AgUiEvent]:
        yield RunStartedEvent(threadId=ctx.thread_id, runId=ctx.run_id)
        yield StateSnapshotEvent(
            snapshot={
                "session_id": ctx.session_id,
                "backend": self._cfg.id,
                "protocol": self._cfg.protocol,
                "role": ctx.actor.role,
            }
        )
        try:
            entry = await self._acquire(ctx)
        except Exception as exc:
            yield RunErrorEvent(message=f"外部后端启动失败: {exc}")
            return
        async with entry.lock:
            async for event in self._prompt(ctx, entry.process):
                yield event

    async def _prompt(
        self, ctx: ChatRunContext, process: _PiProcess
    ) -> AsyncIterator[AgUiEvent]:
        translator = PiRpcEventTranslator(can_confirm=ctx.actor.can_confirm_plans)
        req_id = process.alloc_id()
        try:
            process.write(
                {
                    "id": req_id,
                    "type": "prompt",
                    "message": format_prompt_with_context(ctx),
                }
            )
        except (BrokenPipeError, RuntimeError) as exc:
            yield RunErrorEvent(message=f"Pi 进程不可用: {exc}")
            return
        try:
            async for event in self._read_events(process, req_id, translator, ctx):
                yield event
        except asyncio.CancelledError:
            with contextlib.suppress(BrokenPipeError, RuntimeError):
                process.write({"type": "abort"})
            raise

    async def _read_events(
        self,
        process: _PiProcess,
        req_id: int,
        translator: PiRpcEventTranslator,
        ctx: ChatRunContext,
    ) -> AsyncIterator[AgUiEvent]:
        while True:
            rec = await process.readline()
            if rec is None:
                yield RunErrorEvent(message="Pi 进程意外退出")
                return
            rtype = str(rec.get("type") or "")
            if rtype == "response" and rec.get("id") == req_id:
                if rec.get("success") is False:
                    yield RunErrorEvent(
                        message=str(rec.get("error") or "pi prompt failed")
                    )
                    return
                continue
            if rtype == "agent_settled":
                async for event in self._finish(translator, ctx):
                    yield event
                return
            if rtype == "agent_end" and rec.get("willRetry") is False:
                # Pi 1.7 随后即发 agent_settled；旧版本可能没有——宽限一拍。
                settled = await self._wait_settled(process)
                if settled is not None:
                    for event in translator.translate(settled):
                        yield event
                async for event in self._finish(translator, ctx):
                    yield event
                return
            for event in translator.translate(rec):
                yield event

    async def _wait_settled(self, process: _PiProcess) -> dict[str, Any] | None:
        try:
            rec = await asyncio.wait_for(
                process.readline(), timeout=_AGENT_SETTLE_GRACE_S
            )
        except TimeoutError:
            return None
        return rec

    async def _finish(
        self, translator: PiRpcEventTranslator, ctx: ChatRunContext
    ) -> AsyncIterator[AgUiEvent]:
        for event in translator.close():
            yield event
        yield RunFinishedEvent(threadId=ctx.thread_id, runId=ctx.run_id)
