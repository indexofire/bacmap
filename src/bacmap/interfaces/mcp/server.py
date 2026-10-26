"""bacmap MCP server（ADR-12）。

从工具注册表生成：只暴露 effect=read/compute 的工具——写操作一律经
bacmap_submit_task 提交任务（V11④：MCP 通道无直写）；并按实例绑定的
Profile 裁剪 ``output_data_class``（v1.5，ADR-16：默认 ``cloud``，D3/D4 不出）。
输入 schema 从 legacy JSON Schema（Hermes 插件格式，字段在
parameters.properties 下）生成 pydantic 模型，经单参数 `params` 传入。
传输：stdio（本机客户端，如 Hermes / Claude / Codex）。
"""

import json
import logging
import re
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import create_model

from bacmap.interfaces.mcp.profiles import McpProfile, ProfileSpec
from bacmap.tools import registry as tool_registry
from bacmap.tools.spec import DataClass, Effect

logger = logging.getLogger(__name__)

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
        raw_type = str(prop.get("type", "string"))
        if raw_type not in _TYPE_MAP:
            logger.warning(
                "MCP schema: unknown type %r for %s.%s — defaulting to string",
                raw_type,
                tool_name,
                key,
            )
            raw_type = "string"
        base = _TYPE_MAP[raw_type]
        if key in required:
            fields[key] = (base, ...)
        else:
            fields[key] = (base | None, prop.get("default"))
    safe = re.sub(r"\W", "_", tool_name)
    return create_model(f"{safe}Input", **fields)


DEFAULT_PROFILE = ProfileSpec(
    profile=McpProfile.CLOUD, max_data_class=DataClass.D1, actor="mcp-stdio:cloud:unknown"
)


def exposed_specs(profile: ProfileSpec) -> list[Any]:
    """该 Profile 下对外可见的注册表工具：read/compute 且数据级别不超上限。"""
    return [
        spec
        for spec in tool_registry.list_specs()
        if spec.effect in (Effect.READ, Effect.COMPUTE)
        and profile.allows(spec.output_data_class)
    ]


def build_server(engine: Any = None, profile: ProfileSpec = DEFAULT_PROFILE) -> MCPServer:
    """构建 bacmap MCP server。

    engine 为 None 时不注册任务提交工具（纯只读模式）；
    传入 DbosTaskEngine 时暴露 bacmap_submit_task / bacmap_task_status。
    ``profile`` 决定工具带的数据级别上限与任务提交者身份（服务端决定）。
    """
    server = MCPServer(
        name="bacmap",
        instructions=(
            "bacmap 病原微生物基因组分析。只读/计算工具直接调用；"
            "写操作（分析、建库）优先经 bacmap_create_plan 提交计划，由用户在 bacmap "
            "CLI/Web 中确认后执行（bacmap_get_plan 查看状态与 task_id）；"
            "用 bacmap_task_status 轮询任务（长任务句柄模式）。"
            f"本实例 Profile={profile.profile.value}，"
            f"工具数据级别上限 {profile.max_data_class.name}（ADR-16）。"
        ),
    )

    for spec in exposed_specs(profile):
        model = _model_from_schema(spec.name, spec.legacy_schema)
        _register_legacy_tool(server, spec, model, profile)

    if engine is not None:
        _register_task_tools(server, engine, profile)
        _register_task_control_tools(server, engine, profile)
        _register_record_tool(server, engine, profile)
        _register_plan_tools(server, engine, profile.actor)

    _register_capabilities(server, profile)
    _register_role_prompts(server)
    _register_skill_resources(server)

    return server


def _register_role_prompts(server: MCPServer) -> None:
    """角色说明书经 MCP prompts 暴露（ADR-12：外部助手获得领域指导）。"""
    from bacmap.agent import roledef

    for role in roledef.list_roles():
        def _prompt(role_name: str = role) -> str:
            return roledef.build_system_prompt(role_name)

        _prompt.__name__ = f"bacmap_role_{role}"
        _prompt.__doc__ = f"bacmap {role} 角色说明书：全局原则 + 权限边界 + SKILL 指导"
        server.prompt(
            name=f"bacmap_role_{role}",
            description=(
                f"bacmap {role} 角色说明书：全局原则 + 权限边界 + SKILL 指导。"
                "外部智能体以该角色使用 bacmap 工具前应先取此说明。"
            ),
        )(_prompt)


def _register_legacy_tool(
    server: MCPServer, spec: Any, model: type, profile: ProfileSpec
) -> None:
    def _fn(params: Any) -> str:
        # 调用层二次校验（防御纵深）：发现层已按 Profile 过滤，此处再拒一次。
        if not profile.allows(spec.output_data_class):
            return json.dumps(
                {"error": f"{spec.name} exceeds profile data class "
                          f"{profile.max_data_class.name}"},
                ensure_ascii=False,
            )
        raw = spec.legacy_handler(params.model_dump(exclude_none=True))
        return str(raw)

    # 运行时注解必须是动态生成的输入模型：MCP SDK 据此构建 JSON Schema。
    # 静态上用 Any（动态模型无静态类型），故此处显式补注解，而非抑制类型检查。
    _fn.__annotations__["params"] = model
    _fn.__name__ = spec.name
    _fn.__doc__ = spec.description
    server.tool(name=spec.name, description=spec.description)(_fn)


def _register_task_tools(server: MCPServer, engine: Any, profile: ProfileSpec) -> None:
    from bacmap.tasks.spec import TaskType

    actor = profile.actor

    @server.tool(
        name="bacmap_submit_task",
        description=(
            "直接提交任务（兼容入口；新客户端请优先用 bacmap_create_plan，经用户在 bacmap 中"
            "确认后执行）。task_type: analyze（基因组分析）| curate（特征库构建）。"
            "analyze 需要 samples（样本 ID 列表）；curate 可选 scope（pathogen 等筛选）。"
            "返回 task_id，用 bacmap_task_status 轮询。"
        ),
    )
    def submit_task(
        task_type: str,
        samples: list[str] | None = None,
        scope: dict[str, Any] | None = None,
    ) -> str:
        try:
            tt = TaskType(task_type)
        except ValueError:
            return json.dumps({"error": f"unknown task_type: {task_type!r}"}, ensure_ascii=False)
        # MCP 提交仅支持 analyze/curate（mine/write 属开放路径，需要 script/draft 等
        # 参数，经内建智能体或 Web 提交；此处暴露会退化为空任务）。
        if tt not in (TaskType.ANALYZE, TaskType.CURATE):
            return json.dumps(
                {"error": f"task_type {tt.value!r} is not submittable via MCP "
                          f"(use analyze or curate)"},
                ensure_ascii=False,
            )
        if samples:
            # P2-2：样本 ID 直接进 results/ 路径拼接——白名单校验，拒绝遍历串。
            from bacmap.tools._common import _validate_sample_id

            bad = [s for s in samples if not _validate_sample_id(s)]
            if bad:
                return json.dumps(
                    {"error": f"invalid sample id(s): {bad!r}"}, ensure_ascii=False
                )
        params: dict[str, Any] = {}
        if samples:
            params["samples"] = samples
        if scope:
            params["scope"] = scope
        try:
            # 提交者身份由服务端（Profile/传输）决定，不接受客户端自填（审计链）。
            tid = engine.submit(tt, params, actor)
        except (ValueError, NotImplementedError) as exc:
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
        original_message = str(st.message or "")
        data = st.model_dump(mode="json")
        if not profile.allows(DataClass.D2):
            # 任务消息可能含样本 ID、宿主路径等单株信息（D2）：低于 D2 的 Profile 不回传原文，
            # 但给出脱敏的故障类别与处置建议，让智能体能协助排查（v1.8.5）。
            data["message"] = ""
            data["message_withheld"] = True
            data["failure"] = _redacted_failure(original_message)
        return json.dumps(data, ensure_ascii=False)


def _register_plan_tools(server: MCPServer, engine: Any, actor: str) -> None:
    """计划工具（v1.5.1，ADR-21）：Harness 只能创建/修订/查询计划；确认只在可信界面。"""
    from pathlib import Path

    from bacmap.application.errors import ApplicationError
    from bacmap.application.plans import PlanRecord, PlanService
    from bacmap.tasks.params import PlannableTask

    service = PlanService(engine, Path(engine.db))

    def _out(rec: PlanRecord) -> str:
        data = rec.model_dump(mode="json")
        if rec.state.value == "awaiting_confirmation":
            data["next_step"] = (
                "Ask the user to review and confirm this exact version in bacmap itself: "
                f"`bacmap plan confirm {rec.plan_id} --version {rec.version} "
                f"--hash {rec.short_hash}` (or the Web console). You cannot confirm it; "
                "poll bacmap_get_plan for task_ids after confirmation."
            )
        return json.dumps(data, ensure_ascii=False)

    def _err(exc: ApplicationError) -> str:
        return json.dumps(exc.to_dict(), ensure_ascii=False)

    @server.tool(
        name="bacmap_create_plan",
        description=(
            "Create an analysis plan with typed parameters. Nothing runs until the user confirms "
            "this exact version in the bacmap CLI or Web console. analyze takes exactly one of "
            "samples / fasta_dir / fastq_dir; curate takes scope; mine takes objective + script "
            "(runs in the sandbox, no network) + optional absolute input_paths; write takes "
            "objective + draft. Returns plan_id, version and plan_hash; the user reviews the full "
            "parameters (including the script/draft) before confirming."
        ),
    )
    def create_plan(tasks: list[PlannableTask], rationale: str = "") -> str:
        try:
            return _out(service.create(tasks, rationale, actor))
        except ApplicationError as exc:
            return _err(exc)

    @server.tool(
        name="bacmap_revise_plan",
        description=(
            "Replace the tasks of an unconfirmed or rejected plan. Creates a new version; the "
            "previous version can no longer be confirmed."
        ),
    )
    def revise_plan(plan_id: str, tasks: list[PlannableTask], rationale: str = "") -> str:
        try:
            return _out(service.revise(plan_id, tasks, rationale, actor))
        except ApplicationError as exc:
            return _err(exc)

    @server.tool(
        name="bacmap_get_plan",
        description=(
            "Get a plan (latest version unless version is given): state "
            "(awaiting_confirmation / submitted / rejected / superseded / failed), parameters, "
            "plan_hash and, once confirmed, task_ids to poll with bacmap_task_status."
        ),
    )
    def get_plan(plan_id: str, version: int | None = None) -> str:
        try:
            return _out(service.get(plan_id, version))
        except ApplicationError as exc:
            return _err(exc)


def _register_capabilities(server: MCPServer, profile: ProfileSpec) -> None:
    """能力协商：客户端在调用前了解 Profile、可计划任务与长任务机制（ADR-12）。"""
    from importlib.metadata import version as _version

    @server.tool(
        name="bacmap_capabilities",
        description=(
            "This bacmap instance's capabilities: server version, MCP profile and the highest "
            "data class it may return, plannable task types, the recommended write path, and how "
            "long-running tasks are represented. Call this first."
        ),
    )
    def capabilities() -> str:
        return json.dumps(
            {
                "server": "bacmap",
                "bacmap_version": _version("bacmap"),
                "api": "mcp",
                "profile": profile.profile.value,
                "max_data_class": profile.max_data_class.name,
                "plannable_task_types": ["analyze", "curate", "mine", "write"],
                "recommended_write_path": (
                    "bacmap_create_plan -> user confirms in bacmap CLI/Web -> "
                    "bacmap_get_plan -> bacmap_task_status"
                ),
                "long_running": "explicit task handles (bacmap_task_status polling)",
                # 2026-07-28 规范把 Tasks 移为官方扩展；Python SDK 2.3 尚未实现，
                # 因此 bacmap 继续用显式句柄，语义对齐该扩展以便日后迁移。
                "tasks_extension": "unsupported_by_sdk",
            },
            ensure_ascii=False,
        )


def _redacted_failure(message: str) -> dict[str, Any] | None:
    """任务失败消息 → 脱敏故障类别/建议（不含样本 ID、路径原文）。"""
    if not message:
        return None
    from bacmap.core.analysis.failure_diagnostics import diagnose

    d = diagnose(message)
    return {
        "kind": d.error_type,
        "suggested_fix": d.suggested_fix,
        "recovery_commands": d.recovery_commands,
    }


def _register_record_tool(server: MCPServer, engine: Any, profile: ProfileSpec) -> None:
    """数据管理（v1.8.4）：D4 Profile 下允许智能体经任务层录入元数据/化验/知识库。"""
    if not profile.allows(DataClass.D4):
        return

    from bacmap.tasks.records import parse_record
    from bacmap.tasks.spec import TaskType

    @server.tool(
        name="bacmap_record_data",
        description=(
            "Record data through the task layer (audited). record.kind is one of: metadata "
            "(strain_id, sample_id, fields), lab_result (strain_id, category, test_name, result, "
            "optional unit/method/interpretation/standard/tested_date/tested_by/lab/notes), "
            "knowledge_import (title, authors, year, source, identifier, content, entry_kind), "
            "knowledge_approve (entry_id). Knowledge entries are staged until approved."
        ),
    )
    def record_data(record: dict[str, Any]) -> str:
        payload = dict(record)
        payload.setdefault("kind", "")
        try:
            parse_record(payload)
        except ValueError as exc:
            return json.dumps(
                {"code": "validation_error", "error": str(exc)}, ensure_ascii=False
            )
        try:
            tid = engine.submit(
                TaskType.RECORD, payload, f"{profile.actor} (record_data)"
            )
        except ValueError as exc:
            return json.dumps(
                {"code": "validation_error", "error": str(exc)}, ensure_ascii=False
            )
        return json.dumps(
            {"task_id": tid, "kind": payload["kind"], "state": "running"},
            ensure_ascii=False,
        )


def _register_skill_resources(server: MCPServer) -> None:
    """角色说明书以 skill:// 资源发布（agentskills.io 原文 + sha256 摘要，ADR-12/21）。"""
    import hashlib

    from bacmap.agent import roledef

    for role in roledef.list_roles():
        text = roledef.skill_markdown(role)
        server.resource(
            f"skill://bacmap/{role}/SKILL.md",
            name=f"bacmap-{role}-skill",
            description=f"bacmap {role} 角色说明书（SKILL.md 原文）",
            mime_type="text/markdown",
            meta={"sha256": hashlib.sha256(text.encode()).hexdigest()},
        )(_skill_reader(text))


def _skill_reader(text: str) -> Any:
    def _read() -> str:
        return text

    return _read


def _owns_task(engine: Any, task: dict[str, Any], actor: str) -> bool:
    """本主体直接提交的任务，或由本主体创建的计划派生的任务。"""
    by = str(task.get("submitted_by", ""))
    if by == actor:
        return True
    marker = " via plan "
    if marker not in by:
        return False
    plan_ref = by.rsplit(marker, 1)[1]
    plan_id = plan_ref.split("@", 1)[0]
    from pathlib import Path

    from bacmap.application.errors import NotFound
    from bacmap.application.plans import PlanService

    try:
        plan = PlanService(engine, Path(engine.db)).get(plan_id)
    except NotFound:
        return False
    return plan.created_by == actor


def _gate_summary(result: dict[str, Any], profile: ProfileSpec) -> dict[str, Any]:
    raw = result.get("gates") or {}
    verdicts: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, val in raw.items():
            if isinstance(val, dict) and "verdict" in val:
                verdicts[str(key)] = str(val["verdict"])
    if isinstance(result.get("gate"), dict):  # curate：单一发布门
        verdicts["baseline_release"] = str(result["gate"].get("verdict", ""))
    if profile.allows(DataClass.D2):
        return {"gates": verdicts}
    counts: dict[str, int] = {}
    for v in verdicts.values():
        counts[v] = counts.get(v, 0) + 1
    return {"gate_counts": counts}


def _register_task_control_tools(server: MCPServer, engine: Any, profile: ProfileSpec) -> None:
    from bacmap.tasks.spec import TaskId

    def _err(code: str, message: str) -> str:
        return json.dumps({"code": code, "error": message}, ensure_ascii=False)

    @server.tool(
        name="bacmap_task_cancel",
        description=(
            "Cancel a running task that this client submitted (directly or through a plan it "
            "created). Finished tasks cannot be cancelled."
        ),
    )
    def task_cancel(task_id: str) -> str:
        try:
            task = engine.get_task(TaskId(task_id))
        except KeyError:
            return _err("not_found", f"no such task: {task_id}")
        if not _owns_task(engine, task, profile.actor):
            return _err("forbidden", "only tasks submitted by this client can be cancelled")
        try:
            engine.cancel(TaskId(task_id))
        except ValueError as exc:
            return _err("conflict", str(exc))
        return json.dumps(engine.status(TaskId(task_id)).model_dump(mode="json"))

    @server.tool(
        name="bacmap_task_result",
        description=(
            "Result summary of a finished task: state, run_id and gate verdicts (per sample when "
            "this profile may see single-strain data, otherwise counts only). Large files and "
            "reports are not returned; open them in the bacmap Web console."
        ),
    )
    def task_result(task_id: str) -> str:
        try:
            st = engine.status(TaskId(task_id))
            result = engine.workflow_result(TaskId(task_id))
        except KeyError:
            return _err("not_found", f"no such task: {task_id}")
        out: dict[str, Any] = {"task_id": task_id, "state": st.state.value, "finished": False}
        if result is not None:
            out["finished"] = True
            out["run_id"] = result.get("run_id")
            out.update(_gate_summary(result, profile))
        return json.dumps(out, ensure_ascii=False)
