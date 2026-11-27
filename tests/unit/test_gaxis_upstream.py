"""gaxis 上游适配器：环境开关、Profile 数据级别裁剪、命名前缀。"""

from __future__ import annotations

import asyncio

import pytest

from bacmap.interfaces.mcp.profiles import McpProfile, ProfileSpec
from bacmap.interfaces.mcp.server import build_server
from bacmap.tools.spec import DataClass


def _chart_tools(ceiling: DataClass) -> set[str]:
    server = build_server(profile=ProfileSpec(McpProfile.CLOUD, ceiling, "test"))
    tools = asyncio.run(server.list_tools())
    return {tool.name for tool in tools if tool.name.startswith("bacmap_chart_")}


def test_disabled_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACMAP_GAXIS_URL", raising=False)
    assert _chart_tools(DataClass.D4) == set()
    # 公网端点默认拒绝；显式放行也只允许 D0-D1。
    monkeypatch.setenv("BACMAP_GAXIS_URL", "http://8.8.8.8/mcp")
    assert _chart_tools(DataClass.D4) == set()
    monkeypatch.setenv("BACMAP_GAXIS_ALLOW_REMOTE", "1")
    assert _chart_tools(DataClass.D4) == set()


def test_cloud_profile_hides_local_data_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACMAP_GAXIS_URL", "http://127.0.0.1:1/mcp")
    names = _chart_tools(DataClass.D1)
    assert "bacmap_chart_health" in names
    assert "bacmap_chart_search_chart_assets" in names
    assert "bacmap_chart_plan_chart_from_brief" in names
    assert "bacmap_chart_render_chart_from_data" not in names
    assert "bacmap_chart_adapt_chart_code" not in names
    assert "bacmap_chart_describe_data_schema" not in names


def test_local_trusted_profile_exposes_every_gaxis_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACMAP_GAXIS_URL", "http://127.0.0.1:1/mcp")
    names = _chart_tools(DataClass.D4)
    assert len(names) == 12
    assert "bacmap_chart_render_chart_from_data" in names
    assert "bacmap_chart_list_figure_recipes" in names
    assert "bacmap_chart_render_figure_recipe" in names


def test_registration_is_fail_open_for_a_broken_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad URL must not stop bacmap from starting; tools simply do not appear."""
    monkeypatch.setenv("BACMAP_GAXIS_URL", "http://127.0.0.1:1/mcp")
    server = build_server(profile=ProfileSpec(McpProfile.CLOUD, DataClass.D1, "test"))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "bacmap_capabilities" in names or "bacmap_create_plan" in names
    assert any(name.startswith("bacmap_chart_") for name in names)
