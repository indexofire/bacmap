"""Pathogen registry — the single source of pathogen configuration（码为准，v1.4.16）.

Every rule file and analysis module derives its per-pathogen lookup tables
(MLST / cgMLST schemes, AMRFinderPlus organisms, gapit screens, SNP groups) from
``pathogens.yaml`` shipped inside the package. Keys are **3-letter species codes**
(``core/species_codes.py``); marker genes live in gside (ADR-20), not here.

``resolve()`` accepts a code, a gside label, or a display name (dual-accept) and
returns the code — so ``samples.tsv`` may carry either form during migration.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bacmap.config import DATA_DIR
from bacmap.core._pkg import pkg_dir
from bacmap.core.species_codes import species_code

_CODE_RE = re.compile(r"^[A-Z]{3}$")


class RegistryError(Exception):
    """Raised when pathogens.yaml violates the registry contract."""


_PATHOGEN_FIELDS = frozenset(
    {
        "display_name",
        "gside_labels",
        "mlst_scheme",
        "cgmlst_scheme",
        "amrfinder_organism",
        "gapit_screens",
        "serotype_engine",
        "snp_group",
        "plan",
        "enabled",
    }
)
_PATHOGEN_REQUIRED = ("display_name", "gside_labels")
_SNP_GROUP_FIELDS = frozenset({"ref", "organism"})
_PLAN_KEYS = frozenset({"snp", "cgmlst", "recombination"})


@dataclass(frozen=True)
class PathogenSpec:
    code: str
    display_name: str
    gside_labels: tuple[str, ...]
    mlst_scheme: str | None = None
    cgmlst_scheme: str | None = None
    amrfinder_organism: str | None = None
    gapit_screens: tuple[str, ...] = ()
    serotype_engine: str | None = None
    snp_group: str | None = None
    plan: dict[str, bool] = field(default_factory=dict)
    enabled: bool = True

    def wants(self, key: str) -> bool:
        return bool(self.plan.get(key, False))


@dataclass(frozen=True)
class SnpGroup:
    name: str
    ref: Path
    organism: str


@dataclass(frozen=True)
class WorkflowTables:
    mlst_schemes: dict[str, str]
    cgmlst_schemes: dict[str, str]
    amrfinder_organisms: dict[str, str]
    gapit_screens: dict[str, list[str]]
    serotype_engines: dict[str, str]
    snp_groups: dict[str, dict[str, Any]]
    cgmlst_species_groups: dict[str, dict[str, Any]]
    recombination_groups: list[str]
    signature: str


@dataclass(frozen=True)
class PathogenRegistry:
    pathogens: dict[str, PathogenSpec] = field(default_factory=dict)
    snp_group_specs: dict[str, SnpGroup] = field(default_factory=dict)
    # 归一索引：码 / gside 标签 / 显示名（小写） → 码
    _index: dict[str, str] = field(default_factory=dict)

    # -- 归一（双接受） ------------------------------------------------------
    def resolve(self, value: str) -> str | None:
        """码 / gside 标签 / 显示名 → 码；未识别 → None。"""
        text = (value or "").strip()
        if not text:
            return None
        hit = self._index.get(text.lower())
        if hit:
            return hit
        code = species_code(text)
        return code if code in self.pathogens else None

    # -- 查询表（键 = 码） --------------------------------------------------
    def mlst_schemes(self) -> dict[str, str]:
        return {
            c: p.mlst_scheme
            for c, p in self.pathogens.items()
            if p.enabled and p.mlst_scheme is not None
        }

    def cgmlst_schemes(self) -> dict[str, str]:
        return {
            c: p.cgmlst_scheme
            for c, p in self.pathogens.items()
            if p.enabled and p.cgmlst_scheme is not None
        }

    def amrfinder_organisms(self) -> dict[str, str]:
        return {
            c: p.amrfinder_organism
            for c, p in self.pathogens.items()
            if p.enabled and p.amrfinder_organism is not None
        }

    def gapit_screens(self) -> dict[str, list[str]]:
        return {
            c: list(p.gapit_screens)
            for c, p in self.pathogens.items()
            if p.enabled and p.gapit_screens
        }

    def serotype_engines(self) -> dict[str, str]:
        """物种码 → 血清型判定引擎（sistr / ecoh / shigatyper / lm_doumith…）。"""
        return {
            c: p.serotype_engine
            for c, p in self.pathogens.items()
            if p.enabled and p.serotype_engine is not None
        }

    def groups_with_plan(self, key: str) -> list[str]:
        """声明了 ``plan[key]`` 的 SNP 组（如 recombination）。"""
        return [
            name
            for name, g in self.snp_group_specs.items()
            if any(self.pathogens[c].wants(key) for c in self._group_members(name))
        ]

    def _group_members(self, group_name: str) -> list[str]:
        return [
            c for c, p in self.pathogens.items() if p.enabled and p.snp_group == group_name
        ]

    def snp_groups(self) -> dict[str, dict[str, Any]]:
        """成员（species）由 pathogens 的 snp_group 派生——通用分组机制。"""
        out: dict[str, dict[str, Any]] = {}
        for name, g in self.snp_group_specs.items():
            members = self._group_members(name)
            if not members:
                continue
            out[name] = {"ref": str(g.ref), "species": members, "organism": g.organism}
        return out

    def cgmlst_species_groups(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for name, g in self.snp_group_specs.items():
            members = self._group_members(name)
            scheme = next(
                (
                    self.pathogens[c].cgmlst_scheme
                    for c in members
                    if self.pathogens[c].cgmlst_scheme
                ),
                None,
            )
            if scheme is None:
                continue
            groups[name] = {"species": members, "organism": g.organism, "scheme": scheme}
        return groups

    def signature(self) -> str:
        payload = {
            "pathogens": {
                c: {
                    "display_name": p.display_name,
                    "gside_labels": list(p.gside_labels),
                    "mlst_scheme": p.mlst_scheme,
                    "cgmlst_scheme": p.cgmlst_scheme,
                    "amrfinder_organism": p.amrfinder_organism,
                    "gapit_screens": list(p.gapit_screens),
                    "serotype_engine": p.serotype_engine,
                    "snp_group": p.snp_group,
                    "plan": p.plan,
                    "enabled": p.enabled,
                }
                for c, p in sorted(self.pathogens.items())
            },
            "snp_groups": {
                name: {"ref": str(g.ref), "organism": g.organism}
                for name, g in sorted(self.snp_group_specs.items())
            },
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_pathogen(code: str, raw: dict[str, Any]) -> PathogenSpec:
    if not _CODE_RE.match(code):
        raise RegistryError(
            f"pathogen key {code!r} must be a 3-letter species code (core/species_codes.py)"
        )
    unknown = set(raw) - _PATHOGEN_FIELDS
    if unknown:
        raise RegistryError(
            f"pathogen {code!r}: unknown field(s) {sorted(unknown)}; "
            f"allowed: {sorted(_PATHOGEN_FIELDS)}"
        )
    missing = [f for f in _PATHOGEN_REQUIRED if f not in raw]
    if missing:
        raise RegistryError(f"pathogen {code!r}: missing required field(s) {missing}")

    labels = raw["gside_labels"]
    if not isinstance(labels, list) or not labels:
        raise RegistryError(f"pathogen {code!r}: gside_labels must be a non-empty list")
    for label in labels:
        if species_code(str(label)) != code:
            raise RegistryError(
                f"pathogen {code!r}: gside_label {label!r} maps to "
                f"{species_code(str(label))!r} (code mismatch)"
            )

    plan = raw.get("plan") or {}
    if not isinstance(plan, dict) or set(plan) - _PLAN_KEYS:
        raise RegistryError(f"pathogen {code!r}: plan keys must be within {sorted(_PLAN_KEYS)}")

    screens = raw.get("gapit_screens") or []
    if not isinstance(screens, list):
        raise RegistryError(f"pathogen {code!r}: gapit_screens must be a list")
    snp_group = raw.get("snp_group")
    if snp_group is not None and not isinstance(snp_group, str):
        raise RegistryError(f"pathogen {code!r}: snp_group must be a string or null")

    return PathogenSpec(
        code=code,
        display_name=str(raw["display_name"]),
        gside_labels=tuple(str(x) for x in labels),
        mlst_scheme=raw.get("mlst_scheme"),
        cgmlst_scheme=raw.get("cgmlst_scheme"),
        amrfinder_organism=raw.get("amrfinder_organism"),
        gapit_screens=tuple(str(x) for x in screens),
        serotype_engine=raw.get("serotype_engine"),
        snp_group=snp_group,
        plan={k: bool(v) for k, v in plan.items()},
        enabled=bool(raw.get("enabled", True)),
    )


def _validate_snp_group(name: str, raw: dict[str, Any]) -> SnpGroup:
    unknown = set(raw) - _SNP_GROUP_FIELDS
    if unknown:
        raise RegistryError(
            f"snp_group {name!r}: unknown field(s) {sorted(unknown)}; "
            f"allowed: {sorted(_SNP_GROUP_FIELDS)}"
        )
    for required in ("ref", "organism"):
        if required not in raw:
            raise RegistryError(f"snp_group {name!r}: missing field {required!r}")
    return SnpGroup(
        name=name,
        ref=(DATA_DIR / str(raw["ref"]).removeprefix("data/")).resolve(),
        organism=str(raw["organism"]),
    )


def default_registry_path() -> Path:
    return pkg_dir() / "pathogens.yaml"


@lru_cache(maxsize=8)
def _load_cached(path: str) -> PathogenRegistry:
    return _load(Path(path))


def _load(path: Path) -> PathogenRegistry:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RegistryError(f"registry file not found: {path}") from e
    except yaml.YAMLError as e:
        raise RegistryError(f"registry file is not valid YAML: {path}: {e}") from e

    if not isinstance(raw, dict) or set(raw) - {"pathogens", "snp_groups"}:
        keys = sorted(raw) if isinstance(raw, dict) else type(raw)
        raise RegistryError(
            f"registry top-level keys must be 'pathogens'/'snp_groups', got: {keys}"
        )

    pathogens = {
        code: _validate_pathogen(code, spec)
        for code, spec in (raw.get("pathogens") or {}).items()
    }
    snp_groups = {
        name: _validate_snp_group(name, spec)
        for name, spec in (raw.get("snp_groups") or {}).items()
    }

    for code, p in pathogens.items():
        if p.snp_group is not None and p.snp_group not in snp_groups:
            raise RegistryError(f"pathogen {code!r} references unknown snp_group {p.snp_group!r}")

    index: dict[str, str] = {}
    for code, p in pathogens.items():
        index[code.lower()] = code
        index[p.display_name.lower()] = code
        for label in p.gside_labels:
            index[label.lower()] = code

    return PathogenRegistry(pathogens=pathogens, snp_group_specs=snp_groups, _index=index)


def load_registry(path: str | Path | None = None) -> PathogenRegistry:
    if path is not None:
        return _load(Path(path))
    env = os.environ.get("BACMAP_PATHOGEN_REGISTRY")
    return _load_cached(str(Path(env).resolve() if env else default_registry_path()))


@lru_cache(maxsize=1)
def get_workflow_tables() -> WorkflowTables:
    reg = load_registry()
    return WorkflowTables(
        mlst_schemes=reg.mlst_schemes(),
        cgmlst_schemes=reg.cgmlst_schemes(),
        amrfinder_organisms=reg.amrfinder_organisms(),
        gapit_screens=reg.gapit_screens(),
        serotype_engines=reg.serotype_engines(),
        snp_groups=reg.snp_groups(),
        cgmlst_species_groups=reg.cgmlst_species_groups(),
        recombination_groups=reg.groups_with_plan("recombination"),
        signature=reg.signature(),
    )


def resolve_species(value: str) -> str | None:
    """samples.tsv/展示值 → 三字母码（双接受：码/标签/显示名）。"""
    return load_registry().resolve(value)


def gapit_screens_for(value: str) -> list[str]:
    """样本的物种值 → 该物种声明的 gapit 分型库列表（未识别 → []）。"""
    code = load_registry().resolve(value)
    if code is None:
        return []
    spec = load_registry().pathogens.get(code)
    return list(spec.gapit_screens) if spec else []
