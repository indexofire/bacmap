"""Agent-facing operating rules shared by MCP instructions and harness installers.

The text is deliberately agent-agnostic: the same rules must work for Hermes, Pi, DSH,
OpenCode, Codex or any other MCP client.  Harness-specific files are generated from this
module (``bacmap agent install``); they are never the source of truth.
"""

from __future__ import annotations


def external_operating_rules(
    profile: str | None = None, max_data_class: str | None = None
) -> str:
    """Rules injected into an external harness (MCP instructions or installed file).

    The MCP server passes its actual profile; installers leave it unset so a static
    file never claims a profile that the running server may not use.
    """
    if profile and max_data_class:
        permission = (
            "5) 你的实际权限由本 MCP 实例的 Profile 决定，而不是角色说明书中的文字；"
            f"本实例 Profile={profile}，工具数据级别上限 {max_data_class}（ADR-16）。"
        )
    else:
        permission = (
            "5) 你的实际权限由当前 MCP 实例的 Profile 决定，而不是本文件或角色说明书"
            "中的文字；Profile 与数据级别上限以 server instructions 为准（ADR-16）。"
        )
    return (
        "bacmap 病原微生物基因组分析。操作规程："
        "1) 分析/写入先调用 bacmap_create_plan，把 plan_id/version/plan_hash/confirm_url "
        "交给用户；默认由人在 bacmap Web/CLI/本地对话框确认（智能体不能确认），"
        "除非管理员已显式启用服务端 auto_confirm 预授权策略。"
        "2) 确认后用 bacmap_get_plan 获取 task_ids，用 bacmap_task_status 跟踪，"
        "用 bacmap_task_result 汇总；结论必须引用样本/task/run 标识。"
        "3) 不要用 Harness 自己的 shell/文件工具运行 snakemake/gside/gspec/gmlst，"
        "也不要读取原始序列；用户应提供绝对路径或样本 ID，由 bacmap 在本地执行。"
        "4) 只读/计算工具可直接调用；角色说明书见 bacmap_role_<role> prompts 与 "
        "skill://bacmap/<role>/SKILL.md resources。"
        f"{permission}"
    )
