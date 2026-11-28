"""外部智能体后端的共享助手：卡片提取、提示组装、可用性与工厂。

ACP / Pi RPC 适配器共用此模块，保证无论外部 Harness 用何种协议，
bacmap 计划/任务对象都能提取为原生卡片（``bacmap.plan_card`` /
``bacmap.task_ref``），在控制台内联确认（ADR-21 纪律不变）。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from bacmap.agent.chat.agui import CustomEvent
from bacmap.agent.chat.config import ExternalAgentConfig
from bacmap.agent.chat.types import ChatBackend, ChatRunContext

TOOL_RESULT_WIRE_LIMIT = 16_000


def _unwrap_json_text(text: str) -> str:
    """MCP 包装 ``{"content":[{"type":"text","text":...}]}`` 拆出内层文本。"""
    try:
        outer = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(outer, dict):
        return text
    content = outer.get("content")
    if not isinstance(content, list):
        return text
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p) or text


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """从工具输出中提取首个 JSON 对象（直接 JSON 或混杂文本中的块）。"""
    candidate = _unwrap_json_text(text.strip())
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except (ValueError, TypeError):
        pass
    # 混杂输出：扫描 {...} 平衡括号块，取首个可解析对象。
    depth = 0
    start = -1
    for i, ch in enumerate(candidate):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                chunk = candidate[start : i + 1]
                try:
                    data = json.loads(chunk)
                except (ValueError, TypeError):
                    start = -1
                    continue
                if isinstance(data, dict):
                    return data
                start = -1
    return None


def extract_bacmap_cards(
    tool_name: str, result_text: str, *, can_confirm: bool
) -> list[CustomEvent]:
    """从工具结果中识别 bacmap 计划/任务对象并生成原生卡片事件。

    永不因畸形或非 JSON 输出抛错——无法识别时返回空列表。
    """
    del tool_name  # 识别以载荷结构为准，工具名仅作将来启发式
    try:
        data = _extract_json_object(result_text)
    except Exception:  # 防御：提取逻辑任何异常都不应炸掉对话流
        return []
    if not data:
        return []

    events: list[CustomEvent] = []
    if (
        isinstance(data.get("plan_id"), str)
        and isinstance(data.get("plan_hash"), str)
        and "version" in data
        and "state" in data
    ):
        value = dict(data)
        value["short_hash"] = str(data["plan_hash"])[:12]
        value["can_confirm"] = can_confirm
        events.append(CustomEvent(name="bacmap.plan_card", value=value))
        task_ids = data.get("task_ids")
        if isinstance(task_ids, list):
            for tid in task_ids:
                if isinstance(tid, str) and tid:
                    events.append(
                        CustomEvent(
                            name="bacmap.task_ref",
                            value={
                                "task_id": tid,
                                "plan_id": data["plan_id"],
                            },
                        )
                    )
        return events

    if isinstance(data.get("task_id"), str) and data.get("task_id"):
        events.append(
            CustomEvent(
                name="bacmap.task_ref",
                value={
                    "task_id": data["task_id"],
                    "state": str(data.get("state", "") or ""),
                },
            )
        )
    return events


def format_prompt_with_context(ctx: ChatRunContext) -> str:
    """页面上下文折叠为单行头部注入提示（提示层面，不构成权限依据）。"""
    page = ctx.page_context
    if page and (page.entity_type or page.route):
        bits = page.entity_type or "page"
        if page.entity_id:
            bits = f"{bits} {page.entity_id}"
        header = f"[bacmap context: {bits} ({page.route})]"
        return f"{header}\n\n{ctx.message}"
    return ctx.message


def resolve_external_command(cfg: ExternalAgentConfig) -> list[str]:
    """显式 command 优先；否则按协议取默认启动命令。"""
    if cfg.command:
        return list(cfg.command)
    if cfg.protocol == "dsh":
        if shutil.which("dsh"):
            return ["dsh", "--profile", "acp"]
        return ["npx", "-y", "@deepseek-ai/dsh", "--profile", "acp"]
    if cfg.protocol == "pi-rpc":
        return ["pi", "--mode", "rpc"]
    if cfg.protocol == "opencode":
        return ["opencode", "acp"]
    if cfg.protocol == "hermes":
        if shutil.which("hermes-acp"):
            return ["hermes-acp"]
        return ["hermes", "acp"]
    return []  # acp: 必须显式配置 command 或 url


def check_external_availability(cfg: ExternalAgentConfig) -> tuple[bool, str]:
    """配置面可用性：url 合法即认为可连；否则要求命令存在。"""
    if cfg.url:
        return True, ""
    cmd = resolve_external_command(cfg)
    if not cmd:
        return False, f"外部后端 {cfg.id} 需配置 command 或 url"
    exe = cmd[0]
    if shutil.which(exe) or Path(exe).is_file():
        return True, ""
    return False, f"未找到外部命令 {exe!r}，请先安装或配置绝对路径"


def build_external_backend(cfg: ExternalAgentConfig, home: Path) -> ChatBackend:
    """按协议与传输构造外部后端实例。"""
    if cfg.protocol == "pi-rpc":
        from bacmap.agent.chat.pi_rpc import PiRpcExternalBackend

        return PiRpcExternalBackend(cfg, home)
    if cfg.url:
        from bacmap.agent.chat.acp import AcpHttpBackend

        return AcpHttpBackend(cfg, home)
    from bacmap.agent.chat.acp import AcpStdioBackend

    return AcpStdioBackend(cfg, home)


async def aclose_external_session(session_id: str) -> None:
    """会话删除时回收其外部后端子进程（kill+wait，best-effort 不抛错）。

    必须在 Web 应用的事件循环内 await——子进程 transport 绑定创建它的循环，
    同步 kill-without-wait 会留下半开传输层（GC 告警/孤儿进程）。
    """
    try:
        from bacmap.agent.chat.acp import aclose_acp_session
        from bacmap.agent.chat.pi_rpc import aclose_pi_session

        await aclose_acp_session(session_id=session_id)
        await aclose_pi_session(session_id=session_id)
    except Exception:  # 清理失败不影响删除操作
        logging.getLogger(__name__).debug("external session cleanup failed", exc_info=True)
