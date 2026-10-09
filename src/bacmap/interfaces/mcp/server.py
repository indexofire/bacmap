"""bacmap MCP server（ADR-12）。

从工具注册表生成：只暴露 effect=read/compute 的工具——写操作一律经
bacmap_submit_task 提交任务（V11④：MCP 通道无直写）。
输入 schema 从 legacy JSON Schema（Hermes 插件格式，字段在
parameters.properties 下）生成 pydantic 模型，经单参数 `params` 传入。
传输：stdio（本机客户端，如 Hermes / Claude / Codex）。
"""

import re
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import create_model

from bacmap.tools import registry as tool_registry
from bacmap.tools.spec import Effect

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _model_from_schema(tool_name: str, schema: dict[str, Any] | None) -> type:
    """legacy JSON Schema（parameters 嵌套）→ pydantic 输入模型。"""
    params = (schema or {}).get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = set(params.get("required", []) or [])
    fields: dict[str, Any] = {}
    for key, prop in props.items():
        base = _TYPE_MAP.get(str(prop.get("type", "string")), str)
        if key in required:
            fields[key] = (base, ...)
        else:
            fields[key] = (base | None, prop.get("default"))
    safe = re.sub(r"\W", "_", tool_name)
    return create_model(f"{safe}Input", **fields)


def build_server(engine: Any = None) -> MCPServer:
    """构建 bacmap MCP server。

    engine 为 None 时不注册任务提交工具（纯只读模式）；
    传入 DbosTaskEngine 时暴露 bacmap_submit_task / bacmap_task_status。
    """
    server = MCPServer(
        name="bacmap",
        instructions=(
            "bacmap 病原微生物基因组分析。只读/计算工具直接调用；"
            "写操作（分析、建库）经 bacmap_submit_task 提交任务，"
            "用 bacmap_task_status 轮询（长任务句柄模式）。"
        ),
    )

    for spec in tool_registry.list_specs():
        if spec.effect not in (Effect.READ, Effect.COMPUTE):
            continue
        model = _model_from_schema(spec.name, spec.legacy_schema)
        _register_legacy_tool(server, spec, model)

    if engine is not None:
        _register_task_tools(server, engine)

    return server


def _register_legacy_tool(server: MCPServer, spec: Any, model: type) -> None:
    def _fn(params: model) -> str:  # type: ignore[valid-type]
        raw = spec.legacy_handler(params.model_dump(exclude_none=True))
        return str(raw)

    _fn.__name__ = spec.name
    _fn.__doc__ = spec.description
    server.tool(name=spec.name, description=spec.description)(_fn)


def _register_task_tools(server: MCPServer, engine: Any) -> None:
    import json

    from bacmap.tasks.spec import TaskType

    @server.tool(
        name="bacmap_submit_task",
        description=(
            "提交任务（写操作唯一入口）。task_type: analyze（基因组分析）| curate（特征库构建）。"
            "analyze 需要 samples（样本 ID 列表）；curate 可选 scope（pathogen 等筛选）。"
            "返回 task_id，用 bacmap_task_status 轮询。"
        ),
    )
    def submit_task(
        task_type: str,
        samples: list[str] | None = None,
        scope: dict[str, Any] | None = None,
        submitted_by: str = "mcp-client",
    ) -> str:
        try:
            tt = TaskType(task_type)
        except ValueError:
            return json.dumps({"error": f"unknown task_type: {task_type!r}"}, ensure_ascii=False)
        params: dict[str, Any] = {}
        if samples:
            params["samples"] = samples
        if scope:
            params["scope"] = scope
        try:
            tid = engine.submit(tt, params, submitted_by)
        except NotImplementedError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps({"task_id": tid, "state": "running"}, ensure_ascii=False)

    @server.tool(
        name="bacmap_task_status",
        description="查询任务状态（state: running/succeeded/failed/awaiting_approval/cancelled）。",
    )
    def task_status(task_id: str) -> str:
        try:
            st = engine.status(task_id)
        except KeyError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return st.model_dump_json()
