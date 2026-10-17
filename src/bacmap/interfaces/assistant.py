"""接口层助手胶水：构建会话 + 在确认后执行计划（Web / CLI / TUI 共用）。

- 会话/规划属 agent 层（``bacmap.agent.session``）；
- 提交属任务层（``DbosTaskEngine``）；本模块只做"配置 → 会话"与"计划 → 提交"的编排。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bacmap.agent.llm.endpoints import load_llm_config
from bacmap.agent.llm.gateway import LlmGateway
from bacmap.agent.session import AgentReply, AgentSession, AnalysisPlan, PlannedTask
from bacmap.tasks.engine.dbos_engine import DbosTaskEngine
from bacmap.tasks.spec import TaskType

logger = logging.getLogger(__name__)


def build_session(engine: DbosTaskEngine, *, submitted_by: str = "assistant") -> AgentSession:
    """按 ``$BACMAP_HOME/config.toml`` 的 LLM 配置构建会话（role=assistant）。"""
    home = Path(engine.home)
    from bacmap import config as _config

    if home.resolve() != _config.BACMAP_HOME.resolve():
        # 只读工具（bio_list_samples 等）按 BACMAP_HOME 解析路径；--home 与 env 不一致时提醒。
        logger.warning(
            "assistant read tools follow BACMAP_HOME=%s, but engine.home=%s differs; "
            "set BACMAP_HOME env to the same directory for consistent tool paths",
            _config.BACMAP_HOME,
            home,
        )
    gateway = LlmGateway(load_llm_config(home / "config.toml"))
    from bacmap.agent.sandbox.tool import build_sandbox_tool, build_shell_tool

    workspace = home / "workspaces" / "assistant"
    workspace.mkdir(parents=True, exist_ok=True)
    return AgentSession(
        gateway,
        home=home,
        extra_tools=[build_sandbox_tool(workspace), build_shell_tool(workspace)],
    )


def endpoint_status(engine: DbosTaskEngine) -> str:
    """一行端点状态（名称/位置/模型 + 连通性），供 TUI/CLI 显示——避免"看起来没连上"。

    连通性用 ``GET <base_url>/models`` 轻量探测（3s 超时），失败按未连接报告。
    """
    import httpx

    home = Path(engine.home)
    cfg = load_llm_config(home / "config.toml")
    endpoint = cfg.resolve("intent_classifier")
    if endpoint is None:
        enabled = [e for e in cfg.endpoints.values() if e.enabled]
        endpoint = enabled[0] if enabled else None
    if endpoint is None:
        return "无可用 LLM 端点（确定性路径仍可用）"
    url = endpoint.base_url.rstrip("/") + "/models"
    try:
        resp = httpx.get(url, timeout=3.0)
        conn = "已连接" if resp.status_code < 500 else f"异常 HTTP {resp.status_code}"
    except Exception as exc:  # 连接失败/超时
        conn = f"未连接（{type(exc).__name__}）"
    return f"{endpoint.name} [{endpoint.location}] {endpoint.model} · {conn}"


def execute_plan(
    engine: DbosTaskEngine, plan: AnalysisPlan, *, submitted_by: str = "assistant"
) -> list[dict[str, Any]]:
    """把已确认的计划逐条提交（analyze/curate/mine/write 走同一任务引擎与门）。"""
    results: list[dict[str, Any]] = []
    for task in plan.tasks:
        results.append(_submit_one(engine, task, submitted_by))
    return results


def _submit_one(
    engine: DbosTaskEngine, task: PlannedTask, submitted_by: str
) -> dict[str, Any]:
    try:
        tid = engine.submit(TaskType(task.task_type), dict(task.params), submitted_by)
        return {"task_type": task.task_type, "task_id": tid, "ok": True}
    except (ValueError, NotImplementedError, KeyError) as exc:
        return {"task_type": task.task_type, "ok": False, "error": str(exc)}


def format_plan(plan: AnalysisPlan | None) -> str:
    """计划 → 人读文本（CLI/TUI/Web 通用）。"""
    if plan is None or not plan.tasks:
        return ""
    lines = []
    for i, t in enumerate(plan.tasks, 1):
        reason = f" —— {t.rationale}" if t.rationale else ""
        lines.append(f"  {i}. {t.task_type}{reason}")
    return "\n".join(lines)


def format_reply(reply: AgentReply) -> str:
    """回复 → 人读文本（含计划与降级提示）。"""
    parts = [reply.message] if reply.message else []
    if reply.plan is not None and reply.plan.tasks:
        parts.append("建议执行的分析计划：\n" + format_plan(reply.plan))
    return "\n".join(parts)
