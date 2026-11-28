"""ACP（Agent Client Protocol）适配器：DSH / OpenCode / Hermes / 通用 ACP。

两种传输：stdio 持久子进程（``AcpStdioBackend``，多轮复用同一 ACP 会话）
与回环 HTTP+SSE（``AcpHttpBackend``，如 ``dsh --profile acp serve``）。
ACP ``session/update`` 通知经 ``AcpEventTranslator`` 实时翻译为 AG-UI 事件；
bacmap 计划/任务工具结果提取为原生卡片。权限请求默认只放行只读与
``bacmap`` MCP 工具，破坏性操作除非 ``auto_approve_permissions`` 开启一律拒绝，
保证代理永不悬挂在无人值守的 TUI 提示上。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from bacmap import __version__
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

_HANDSHAKE_TIMEOUT = 30.0


def _content_text(content: Any) -> str:
    """ACP 内容块（字符串 / 单块 / 块列表）提取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            return content["text"]
        return ""
    if isinstance(content, list):
        return "".join(_content_text(block) for block in content)
    return ""


class AcpEventTranslator:
    """单次运行内把 ACP ``session/update`` 载荷翻译为 AG-UI 事件（有状态）。"""

    def __init__(self, *, can_confirm: bool) -> None:
        self._can_confirm = can_confirm
        self._thinking_open = False
        self._message_id: str | None = None
        self._tool_seen: set[str] = set()
        self._tool_done: set[str] = set()

    # ---- 思考/文本 ------------------------------------------------------------

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

    def translate(self, update: dict[str, Any]) -> list[AgUiEvent]:
        kind = update.get("sessionUpdate") or update.get("type") or ""
        if kind in ("agent_thought_chunk", "agent_thought"):
            delta = _content_text(update.get("content"))
            if not delta:
                return []
            return [
                *self._open_thinking(),
                ThinkingTextMessageContentEvent(delta=delta),
            ]
        if kind in ("agent_message_chunk", "agent_message"):
            delta = _content_text(update.get("content"))
            if not delta:
                return []
            return [
                *self._close_thinking(),
                *self._open_text(),
                *([TextMessageContentEvent(messageId=self._message_id or "", delta=delta)]),
            ]
        if kind in ("tool_call", "tool_call_update"):
            return self._tool_events(update)
        return []

    # ---- 工具调用 ---------------------------------------------------------------

    def _tool_events(self, update: dict[str, Any]) -> list[AgUiEvent]:
        out: list[AgUiEvent] = []
        tool_id = str(update.get("toolCallId") or update.get("id") or "")
        if not tool_id:
            return out
        name = str(
            update.get("title")
            or update.get("name")
            or update.get("toolName")
            or "tool"
        )
        if tool_id not in self._tool_seen:
            self._tool_seen.add(tool_id)
            out.extend(self._close_thinking())
            out.extend(self._close_text())
            out.append(ToolCallStartEvent(toolCallId=tool_id, toolCallName=name))
            raw_input = update.get("rawInput") or update.get("input")
            if raw_input:
                args = (
                    raw_input
                    if isinstance(raw_input, str)
                    else json.dumps(raw_input, ensure_ascii=False)
                )
                out.append(ToolCallArgsEvent(toolCallId=tool_id, delta=args))
            out.append(ToolCallEndEvent(toolCallId=tool_id))

        status = str(update.get("status") or "")
        output = update.get("rawOutput")
        if output is None:
            output = update.get("output")
        if output is None:
            output = _content_text(update.get("content"))
        if tool_id in self._tool_done:
            return out
        if status in ("completed", "failed", "error") or output:
            text = output if isinstance(output, str) else (
                json.dumps(output, ensure_ascii=False) if output else ""
            )
            self._tool_done.add(tool_id)
            out.append(
                ToolCallResultEvent(
                    messageId=new_id("cm_tool_"),
                    toolCallId=tool_id,
                    content=text[:TOOL_RESULT_WIRE_LIMIT],
                )
            )
            if text:
                out.extend(
                    extract_bacmap_cards(name, text, can_confirm=self._can_confirm)
                )
        return out

    def close(self) -> list[AgUiEvent]:
        return [*self._close_thinking(), *self._close_text()]


def _decide_permission(params: dict[str, Any], auto_approve: bool) -> dict[str, Any]:
    """权限裁决：bacmap MCP 工具与只读操作放行，其余默认拒绝（不悬挂）。

    ``auto_approve=True`` 时一律选第一个 allow_* 选项。
    """
    options = params.get("options") or []
    tool = params.get("toolCall") or {}
    title = str(tool.get("title") or tool.get("name") or params.get("title") or "")
    kind = str(tool.get("kind") or params.get("kind") or "")

    allow = next(
        (o for o in options if str(o.get("kind", "")).startswith("allow")),
        None,
    )
    reject = next(
        (
            o
            for o in options
            if str(o.get("kind", "")).startswith(("reject", "cancel"))
        ),
        None,
    )
    readonly = kind == "read" or "bacmap" in title.lower()
    granted = auto_approve or readonly
    chosen = (allow if granted else reject) or reject or allow
    if chosen is None:
        return {"outcome": {"outcome": "cancelled"}}
    return {
        "outcome": {
            "outcome": "selected",
            "optionId": chosen.get("optionId") or chosen.get("id") or "",
        }
    }


# ---- stdio 持久子进程 -----------------------------------------------------------


class _AcpProcess:
    """一个长驻 ACP stdio 子进程 + 其 acp 会话。"""

    def __init__(self, cmd: list[str], cwd: Path) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.proc: asyncio.subprocess.Process | None = None
        self.acp_session_id = ""
        self._next_id = 0

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def start(self, auto_approve: bool) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.cwd),
            start_new_session=True,
        )
        await self._roundtrip(
            "initialize",
            {
                "protocolVersion": 1,
                "clientInfo": {"name": "bacmap", "version": __version__},
                "clientCapabilities": {},
            },
            auto_approve,
        )
        result = await self._roundtrip(
            "session/new",
            {"cwd": str(self.cwd), "mcpServers": []},
            auto_approve,
        )
        self.acp_session_id = str(result.get("sessionId") or "")

    # ---- wire 读写 ---------------------------------------------------------------

    def _write(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("ACP 子进程未启动")
        self.proc.stdin.write(json.dumps(payload).encode() + b"\n")

    async def _readline(self) -> dict[str, Any] | None:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("ACP 子进程未启动")
        line = await self.proc.stdout.readline()
        if not line:
            return None
        try:
            msg = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            return {}
        return msg if isinstance(msg, dict) else {}

    def _answer_server_request(self, msg: dict[str, Any], auto_approve: bool) -> None:
        req_id = msg.get("id")
        method = str(msg.get("method") or "")
        if method == "session/request_permission":
            result = _decide_permission(msg.get("params") or {}, auto_approve)
            self._write({"jsonrpc": "2.0", "id": req_id, "result": result})
        else:
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )

    async def _roundtrip(
        self, method: str, params: dict[str, Any], auto_approve: bool
    ) -> dict[str, Any]:
        """握手期请求-响应：读到匹配 id 的响应为止，期间应答服务器请求。"""
        req_id = self._alloc_id()
        self._write(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        while True:
            msg = await asyncio.wait_for(self._readline(), timeout=_HANDSHAKE_TIMEOUT)
            if msg is None:
                raise RuntimeError(f"ACP 子进程在 {method} 期间退出")
            if "id" in msg and "method" in msg:
                self._answer_server_request(msg, auto_approve)
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"ACP {method} 失败: {msg['error']}")
                result = msg.get("result")
                return result if isinstance(result, dict) else {}

    async def kill(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.kill()
        except ProcessLookupError:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)


class _PoolEntry:
    def __init__(self, process: _AcpProcess) -> None:
        self.process = process
        self.lock = asyncio.Lock()


_ACP_POOL: dict[tuple[str, str, Any], _PoolEntry] = {}


def close_acp_session(backend_id: str = "", session_id: str = "") -> None:
    """回收匹配会话的 ACP 子进程（同步、best-effort）。"""
    doomed = [
        key
        for key in _ACP_POOL
        if (not backend_id or key[0] == backend_id) and key[1] == session_id
    ]
    for key in doomed:
        entry = _ACP_POOL.pop(key, None)
        if entry is None:
            continue
        proc = entry.process.proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()


async def reap_acp_pool() -> None:
    """kill 并 await 全部池化 ACP 子进程（测试拆除与服务关停用）。

    与 pi_rpc.reap_pi_pool 同理：不收割会在事件循环关闭后产生
    "Event loop is closed" 的 GC 告警并可能孤儿化外部 Agent 进程。
    """
    entries = list(_ACP_POOL.values())
    _ACP_POOL.clear()
    for entry in entries:
        await entry.process.kill()


class AcpStdioBackend:
    """ACP stdio 后端：DSH / OpenCode / Hermes / 通用 ACP 代理。"""

    def __init__(self, cfg: ExternalAgentConfig, home: Path) -> None:
        self._cfg = cfg
        self._home = Path(home)

    async def _acquire(self, ctx: ChatRunContext) -> tuple[tuple[str, str, Any], _PoolEntry]:
        key = (self._cfg.id, ctx.session_id, asyncio.get_running_loop())
        entry = _ACP_POOL.get(key)
        if entry is not None and (
            entry.process.proc is None or entry.process.proc.returncode is not None
        ):
            _ACP_POOL.pop(key, None)
            entry = None
        if entry is None:
            cmd = resolve_external_command(self._cfg)
            cwd = Path(self._cfg.workdir) if self._cfg.workdir else self._home
            process = _AcpProcess(cmd, cwd)
            await process.start(self._cfg.auto_approve_permissions)
            entry = _PoolEntry(process)
            _ACP_POOL[key] = entry
        return key, entry

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
            _key, entry = await self._acquire(ctx)
        except Exception as exc:
            yield RunErrorEvent(message=f"外部后端启动失败: {exc}")
            return
        async with entry.lock:
            async for event in self._prompt(ctx, entry.process):
                yield event

    async def _prompt(
        self, ctx: ChatRunContext, process: _AcpProcess
    ) -> AsyncIterator[AgUiEvent]:
        translator = AcpEventTranslator(can_confirm=ctx.actor.can_confirm_plans)
        req_id = process._alloc_id()
        process._write(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "session/prompt",
                "params": {
                    "sessionId": process.acp_session_id,
                    "prompt": [
                        {"type": "text", "text": format_prompt_with_context(ctx)}
                    ],
                },
            }
        )
        try:
            async for event in self._read_prompt_events(process, req_id, translator, ctx):
                yield event
        except asyncio.CancelledError:
            process._write(
                {
                    "jsonrpc": "2.0",
                    "method": "session/cancel",
                    "params": {"sessionId": process.acp_session_id},
                }
            )
            raise

    async def _read_prompt_events(
        self,
        process: _AcpProcess,
        req_id: int,
        translator: AcpEventTranslator,
        ctx: ChatRunContext | None = None,
    ) -> AsyncIterator[AgUiEvent]:
        while True:
            msg = await process._readline()
            if msg is None:
                # 子进程死亡：从池中剔除由 _acquire 下次判定，向上报错
                yield RunErrorEvent(message="外部智能体进程意外退出")
                return
            if "id" in msg and "method" in msg:
                process._answer_server_request(
                    msg, self._cfg.auto_approve_permissions
                )
                continue
            method = str(msg.get("method") or "")
            if method == "session/update":
                params = msg.get("params") or {}
                update = params.get("update") or params
                if isinstance(update, dict):
                    for event in translator.translate(update):
                        yield event
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    error = msg["error"]
                    note = (
                        error.get("message", str(error))
                        if isinstance(error, dict)
                        else str(error)
                    )
                    yield RunErrorEvent(message=f"ACP prompt 失败: {note}")
                    return
                for event in translator.close():
                    yield event
                if ctx is not None:
                    yield RunFinishedEvent(threadId=ctx.thread_id, runId=ctx.run_id)
                return


# ---- HTTP+SSE 后端 ---------------------------------------------------------------


class AcpHttpBackend:
    """回环 ACP HTTP+SSE 后端（``dsh --profile acp serve`` 等）。"""

    def __init__(
        self,
        cfg: ExternalAgentConfig,
        home: Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._home = Path(home)
        base = cfg.url.rstrip("/")
        self._post_url = base if base.endswith("/acp") else f"{base}/acp"
        self._stream_url = f"{self._post_url}/stream"
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._cfg.api_key_env:
            import os

            token = os.environ.get(self._cfg.api_key_env, "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

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
        timeout = httpx.Timeout(300.0, connect=10.0)
        async with httpx.AsyncClient(
            timeout=timeout, transport=self._transport
        ) as client:
            try:
                async for event in self._run_http(ctx, client):
                    yield event
            except httpx.HTTPError as exc:
                yield RunErrorEvent(message=f"外部后端 HTTP 错误: {exc}")

    async def _run_http(
        self, ctx: ChatRunContext, client: httpx.AsyncClient
    ) -> AsyncIterator[AgUiEvent]:
        conn_id = ""
        try:
            init_resp = await client.post(
                self._post_url,
                headers=self._headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "bacmap", "version": __version__},
                        "clientCapabilities": {},
                    },
                },
            )
            init_resp.raise_for_status()
            conn_id = init_resp.headers.get("acp-connection-id", "")
        except httpx.HTTPError as exc:
            yield RunErrorEvent(message=f"ACP initialize 失败: {exc}")
            return

        headers = self._headers()
        if conn_id:
            headers["Acp-Connection-Id"] = conn_id
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        stream_task = asyncio.create_task(
            self._pump_stream(client, headers, queue)
        )
        try:
            async for event in self._run_session(ctx, client, headers, queue):
                yield event
        finally:
            stream_task.cancel()
            with contextlib.suppress(httpx.HTTPError):
                await client.delete(self._post_url, headers=headers)

    async def _pump_stream(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> None:
        try:
            async with client.stream(
                "GET", self._stream_url, headers=headers
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        msg = json.loads(payload)
                    except ValueError:
                        continue
                    if isinstance(msg, dict):
                        await queue.put(msg)
        except (httpx.HTTPError, asyncio.CancelledError):
            pass
        finally:
            await queue.put(None)

    async def _post_rpc(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        req_id: int,
        method: str,
        params: dict[str, Any],
    ) -> None:
        resp = await client.post(
            self._post_url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params},
        )
        resp.raise_for_status()

    async def _wait_result(
        self, queue: asyncio.Queue[dict[str, Any] | None], req_id: int
    ) -> dict[str, Any] | None:
        """握手阶段：消费 SSE 队列直到 req_id 响应到达，返回 result 或 None。"""
        while True:
            msg = await queue.get()
            if msg is None:
                return None
            if msg.get("id") == req_id:
                if "error" in msg:
                    return None
                result = msg.get("result")
                return result if isinstance(result, dict) else {}

    async def _run_session(
        self,
        ctx: ChatRunContext,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        queue: asyncio.Queue[dict[str, Any] | None],
    ) -> AsyncIterator[AgUiEvent]:
        try:
            await self._post_rpc(
                client, headers, 2, "session/new",
                {"cwd": str(self._home), "mcpServers": []},
            )
        except httpx.HTTPError as exc:
            yield RunErrorEvent(message=f"ACP session/new 失败: {exc}")
            return
        result = await self._wait_result(queue, 2)
        acp_session_id = str((result or {}).get("sessionId") or "")
        if not acp_session_id:
            yield RunErrorEvent(message="ACP session/new 未返回 sessionId")
            return

        try:
            await self._post_rpc(
                client, headers, 3, "session/prompt",
                {
                    "sessionId": acp_session_id,
                    "prompt": [
                        {"type": "text", "text": format_prompt_with_context(ctx)}
                    ],
                },
            )
        except httpx.HTTPError as exc:
            yield RunErrorEvent(message=f"ACP session/prompt 失败: {exc}")
            return

        translator = AcpEventTranslator(can_confirm=ctx.actor.can_confirm_plans)
        async for event in self._stream_prompt_events(queue, 3, translator, ctx):
            yield event

    async def _stream_prompt_events(
        self,
        queue: asyncio.Queue[dict[str, Any] | None],
        req_id: int,
        translator: AcpEventTranslator,
        ctx: ChatRunContext,
    ) -> AsyncIterator[AgUiEvent]:
        """消费 SSE 队列：翻译 update、应答服务器请求，直到 prompt 响应。"""
        while True:
            msg = await queue.get()
            if msg is None:
                yield RunErrorEvent(message="外部后端 SSE 流中断")
                return
            method = str(msg.get("method") or "")
            if method == "session/update":
                params = msg.get("params") or {}
                update = params.get("update") or params
                if isinstance(update, dict):
                    for event in translator.translate(update):
                        yield event
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    yield RunErrorEvent(message=f"ACP prompt 失败: {msg['error']}")
                    return
                for event in translator.close():
                    yield event
                yield RunFinishedEvent(threadId=ctx.thread_id, runId=ctx.run_id)
                return


