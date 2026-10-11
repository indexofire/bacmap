"""角色三文件加载（ADR-10：principles + SKILL.md + role.yaml）。

权限由 role.yaml 决定并交代码强制；principles 与 SKILL.md 只是对模型的指导。
build_system_prompt() 供 LlmGateway 以 role= 注入 system instructions（ADR-08/10）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_AGENT_DIR = Path(__file__).parent
_PRINCIPLES_PATH = _AGENT_DIR / "principles.md"
_SKILLS_DIR = _AGENT_DIR / "skills"
_ROLES_DIR = _AGENT_DIR / "roles"


class RoleDef(BaseModel):
    """role.yaml 的代码化形态（冻结设计 §4.4 角色清单）。"""

    name: str
    task_types: list[str]
    min_model_tier: str = "T1"
    allowed_locations: list[str] = Field(default_factory=lambda: ["local"])
    max_data_class: str = "D1"
    trust_layer: str = "L3"
    tools: list[str] = Field(default_factory=list)
    fs_scope: dict[str, list[str]] = Field(default_factory=dict)
    network: bool = False


def load_principles() -> str:
    if not _PRINCIPLES_PATH.is_file():
        raise FileNotFoundError(f"principles.md missing: {_PRINCIPLES_PATH}")
    return _PRINCIPLES_PATH.read_text(encoding="utf-8")


def load_skill(role: str) -> str:
    """SKILL.md 正文（剥掉 YAML frontmatter）。"""
    path = _SKILLS_DIR / role / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"SKILL.md not found for role {role!r}: {path}")
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def load_role_def(role: str) -> RoleDef:
    path = _ROLES_DIR / f"{role}.role.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"role manifest not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid role manifest (not a mapping): {path}")
    return RoleDef.model_validate(raw)


def list_roles() -> list[str]:
    """skills/ 下已交付说明书全部角色名。"""
    return sorted(p.parent.name for p in _SKILLS_DIR.glob("*/SKILL.md"))


def build_system_prompt(role: str) -> str:
    """全局原则 + 角色权限摘要 + SKILL 说明书 → system instructions。"""
    rd = load_role_def(role)
    perm = (
        f"- 任务类型：{'、'.join(rd.task_types)}\n"
        f"- 工具白名单：{'、'.join(rd.tools) if rd.tools else '无'}\n"
        f"- 数据级别上限：{rd.max_data_class}\n"
        f"- 端点位置：{'、'.join(rd.allowed_locations)}\n"
        f"- 网络：{'允许' if rd.network else '禁止'}\n"
    )
    return (
        f"# 全局原则\n\n{load_principles()}\n\n"
        f"# 角色：{role}\n\n"
        f"## 权限边界（由代码强制，此处仅作提醒）\n{perm}\n"
        f"## 角色说明书\n\n{load_skill(role)}\n"
    )
