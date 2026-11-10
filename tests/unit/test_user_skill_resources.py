"""用户安装领域技能的 MCP 资源发布（v1.10.20）。

figures4papers 的 figure-maker 技能经 ``scripts/install_figure_skill.py``
装到 ``$BACMAP_HOME/skills/`` 后，应与角色技能同以 ``skill://bacmap/**``
发布（SKILL.md + references/*.md）；目录缺失时静默跳过（角色技能不受影响）。
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path


def _make_user_skill(home: Path) -> None:
    skill = home / "skills" / "figure-maker"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: figure-maker\nversion: 0.1.0\n---\n\n# test skill\n", encoding="utf-8"
    )
    (skill / "references" / "api.md").write_text("# api\npalette: test\n", encoding="utf-8")


class TestUserSkillResources:
    def test_user_skill_published_with_references(self, tmp_path, monkeypatch):
        import bacmap.config as cfg

        _make_user_skill(tmp_path)
        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path)
        from bacmap.interfaces.mcp import server as mcp_server

        # 重新加载资源注册（BACMAP_HOME 已 monkeypatch）

        importlib.reload(mcp_server)

        uri = "skill://bacmap/figure-maker/SKILL.md"
        text = asyncio.run(mcp_server.build_server().read_resource(uri))
        assert "test skill" in str(text)

        ref = asyncio.run(
            mcp_server.build_server().read_resource(
                "skill://bacmap/figure-maker/references/api.md"
            )
        )
        assert "palette" in str(ref)

    def test_missing_skills_dir_role_skills_still_published(self, tmp_path, monkeypatch):
        """$BACMAP_HOME/skills 不存在 → 只发布角色技能，不报错。"""
        import bacmap.config as cfg

        monkeypatch.setattr(cfg, "BACMAP_HOME", tmp_path)  # 无 skills/ 子目录
        from bacmap.interfaces.mcp import server as mcp_server


        importlib.reload(mcp_server)

        text = asyncio.run(mcp_server.build_server().read_resource("skill://bacmap/analyst/SKILL.md"))
        assert "生信分析师" in str(text)
