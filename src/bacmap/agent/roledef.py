"""角色三文件加载（ADR-10：principles + SKILL.md + role.yaml）。

权限由 role.yaml 决定并交代码强制；principles 与 SKILL.md 只是对模型的指导。
build_system_prompt() 供 LlmGateway 以 role= 注入 system instructions（ADR-08/10）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_AGENT_DIR = Path(__file__).parent
_PRINCIPLES_PATH = _AGENT_DIR / "principles.md"
_SKILLS_DIR = _AGENT_DIR / "skills"
_ROLES_DIR = _AGENT_DIR / "roles"

# 角色清单的封闭取值（ADR-09 档位 / ADR-16 数据级别 / ADR-06 任务类型 / 端点位置）。
_TIERS = frozenset({"T0", "T1", "T2"})
_DATA_CLASSES = frozenset({"D0", "D1", "D2", "D3", "D4"})
_TASK_TYPES = frozenset({"analyze", "curate", "mine", "write"})
_LOCATIONS = frozenset({"local", "lan", "cloud"})


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

    @field_validator("min_model_tier")
    @classmethod
    def _valid_tier(cls, v: str) -> str:
        if v not in _TIERS:
            raise ValueError(f"min_model_tier must be one of {sorted(_TIERS)}, got {v!r}")
        return v

    @field_validator("max_data_class")
    @classmethod
    def _valid_data_class(cls, v: str) -> str:
        if v not in _DATA_CLASSES:
            raise ValueError(f"max_data_class must be one of {sorted(_DATA_CLASSES)}, got {v!r}")
        return v

    @field_validator("task_types")
    @classmethod
    def _valid_task_types(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in _TASK_TYPES]
        if bad:
            raise ValueError(f"task_types must be within {sorted(_TASK_TYPES)}, got {bad!r}")
        return v

    @field_validator("allowed_locations")
    @classmethod
    def _valid_locations(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in _LOCATIONS]
        if bad:
            raise ValueError(f"allowed_locations must be within {sorted(_LOCATIONS)}, got {bad!r}")
        return v


def load_principles() -> str:
    if not _PRINCIPLES_PATH.is_file():
        raise FileNotFoundError(f"principles.md missing: {_PRINCIPLES_PATH}")
    return _PRINCIPLES_PATH.read_text(encoding="utf-8")


def skill_markdown(role: str) -> str:
    """SKILL.md 原文（含 frontmatter；agentskills.io 格式，供 MCP skill:// 资源分发）。"""
    path = _SKILLS_DIR / role / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"SKILL.md not found for role {role!r}: {path}")
    return path.read_text(encoding="utf-8")


def load_skill(role: str) -> str:
    """SKILL.md 正文（剥掉 YAML frontmatter）。"""
    text = skill_markdown(role)
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
