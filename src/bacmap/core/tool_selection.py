"""User/project selection of per-tool reference data.

The packaged ``core/pathogens.yaml`` remains the default mapping (developers
own it).  Users who need a different mapping write a ``tool_selection.yaml``
under ``$BACMAP_HOME/config/`` (or point ``$BACMAP_TOOL_SELECTION`` / the
``tool_selection`` workflow config key at one).  The overlay is organised by
tool (``gspec`` databases, ``gmlst`` typing modes/schemes) so future tools can
add their own section without a new file.

Layering (ADR-03 extension, v1.4.40)::

    pathogens.yaml          packaged defaults (never edited by users)
    tool_selection.yaml     user/project overlay (this module)
    species_id.json         runtime gside verdict (workflow only)
    effective selection     merged plan handed to gspec/gmlst

The legacy ``db_selection.yaml`` / ``bacmap.db_selection/1`` document is
accepted as a gspec-only alias and translated on load.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bacmap.config import BACMAP_HOME
from bacmap.core.pathogen_registry import PathogenRegistry, load_registry
from bacmap.core.species_codes import UNK

SCHEMA: Literal["bacmap.tool_selection/1"] = "bacmap.tool_selection/1"
LEGACY_SCHEMA = "bacmap.db_selection/1"
TOOL_SELECTION_ENV = "BACMAP_TOOL_SELECTION"
LEGACY_SELECTION_ENV = "BACMAP_DB_SELECTION"
DEFAULT_SELECTION_REL = Path("config") / "tool_selection.yaml"
LEGACY_SELECTION_REL = Path("config") / "db_selection.yaml"

GmlstMode = Literal["mlst", "cgmlst", "wgmlst", "tgmlst"]

_SAMPLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CODE_RE = re.compile(r"^[A-Z]{3}$")


class SelectionError(Exception):
    """Raised when a tool selection document cannot be loaded or written."""


class ToolModeDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["extend", "replace"] = "extend"


class SelectionDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gspec: ToolModeDefaults = Field(default_factory=ToolModeDefaults)
    gmlst: ToolModeDefaults = Field(default_factory=ToolModeDefaults)

    @model_validator(mode="before")
    @classmethod
    def _legacy_defaults(cls, value: Any) -> Any:
        # Old db_selection.yaml: ``defaults: {mode: replace}``.
        if (
            isinstance(value, dict)
            and "mode" in value
            and "gspec" not in value
            and "gmlst" not in value
        ):
            return {"gspec": {"mode": value["mode"]}}
        return value


class GspecSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["extend", "replace"] | None = None
    databases: list[str] = Field(default_factory=list)

    @field_validator("databases")
    @classmethod
    def _clean_databases(cls, value: list[str]) -> list[str]:
        return _dedupe(str(item).strip() for item in value)


class GmlstSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["extend", "replace"] | None = None
    modes: list[GmlstMode] | None = None
    schemes: dict[str, str] = Field(default_factory=dict)

    @field_validator("modes")
    @classmethod
    def _clean_modes(cls, value: list[GmlstMode] | None) -> list[GmlstMode] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @field_validator("schemes")
    @classmethod
    def _clean_schemes(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(key).strip(): str(item).strip()
            for key, item in value.items()
            if str(item).strip()
        }


class SpeciesSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gspec: GspecSelection | None = None
    gmlst: GmlstSelection | None = None


class SampleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gspec: GspecSelection | None = None
    gmlst: GmlstSelection | None = None


class SelectionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_by: Literal["ai", "cli", "manual"] = "manual"
    generated_at: str = ""
    approved_by: str = ""
    registry_signature: str = ""
    gspec_catalog_hash: str = ""
    gmlst_catalog_hash: str = ""
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_meta(cls, value: Any) -> Any:
        # Old db_selection.yaml wrote ``catalog_hash`` for the gspec catalog.
        if isinstance(value, dict) and "catalog_hash" in value:
            data = dict(value)
            data.setdefault("gspec_catalog_hash", data.pop("catalog_hash"))
            return data
        return value


class GmlstPlan(BaseModel):
    """Effective gmlst modes and schemes for one sample/species."""

    model_config = ConfigDict(frozen=True)

    modes: list[GmlstMode] = Field(default_factory=list)
    schemes: dict[str, str] = Field(default_factory=dict)


class ToolSelection(BaseModel):
    """``bacmap.tool_selection/1`` — the user/project overlay document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal[
        "bacmap.tool_selection/1", "bacmap.db_selection/1"
    ] = Field(default="bacmap.tool_selection/1", alias="schema")
    defaults: SelectionDefaults = Field(default_factory=SelectionDefaults)
    species: dict[str, SpeciesSelection] = Field(default_factory=dict)
    samples: dict[str, SampleSelection] = Field(default_factory=dict)
    meta: SelectionMeta = Field(default_factory=SelectionMeta)

    @field_validator("species", mode="before")
    @classmethod
    def _normalize_species(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[str(key).strip().upper()] = _normalize_entry(item)
        return out

    @field_validator("samples", mode="before")
    @classmethod
    def _normalize_samples(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            out[str(key).strip()] = _normalize_entry(item)
        return out

    def effective_gspec_databases(
        self,
        code: str | None,
        *,
        sample: str | None = None,
        registry: PathogenRegistry | None = None,
    ) -> list[str]:
        """Sample override → species override → registry default → ``[]``."""
        if sample and sample in self.samples:
            sample_gspec = self.samples[sample].gspec
            if sample_gspec is not None:
                return list(sample_gspec.databases)

        key = code or UNK
        reg = registry or load_registry()
        defaults = _registry_gspec_defaults(reg, key)
        spec = self.species.get(key)
        if spec is None or spec.gspec is None:
            return defaults

        mode = spec.gspec.mode or self.defaults.gspec.mode
        if mode == "replace":
            return list(spec.gspec.databases)
        return _dedupe([*defaults, *spec.gspec.databases])

    def effective_gmlst(
        self,
        code: str | None,
        *,
        sample: str | None = None,
        registry: PathogenRegistry | None = None,
    ) -> GmlstPlan:
        """Sample override → species override → registry default."""
        reg = registry or load_registry()
        key = code or UNK
        base = _registry_gmlst_defaults(reg, key)

        species_plan = base
        spec = self.species.get(key)
        if spec is not None and spec.gmlst is not None:
            species_plan = _merge_gmlst(
                base, spec.gmlst, self.defaults.gmlst.mode
            )

        if sample and sample in self.samples:
            sample_gmlst = self.samples[sample].gmlst
            if sample_gmlst is not None:
                return _merge_gmlst(
                    species_plan, sample_gmlst, self.defaults.gmlst.mode
                )
        return species_plan

    # Backward-compatible alias for the gspec-only call sites.
    def effective_databases(
        self,
        code: str | None,
        *,
        sample: str | None = None,
        registry: PathogenRegistry | None = None,
    ) -> list[str]:
        return self.effective_gspec_databases(
            code, sample=sample, registry=registry
        )

    def includes(
        self,
        code: str | None,
        database: str,
        *,
        sample: str | None = None,
        registry: PathogenRegistry | None = None,
    ) -> bool:
        return database in self.effective_gspec_databases(
            code, sample=sample, registry=registry
        )


# Old class name kept for call sites that have not migrated yet.
DbSelection = ToolSelection


def _normalize_entry(item: Any) -> Any:
    """Accept the v1.4.40 gspec-only shapes as ``{gspec: ...}``."""
    if isinstance(item, list):
        return {"gspec": {"databases": item}}
    if isinstance(item, dict):
        if "gspec" in item or "gmlst" in item:
            return item
        if "databases" in item or "mode" in item:
            return {"gspec": item}
    return item


def _dedupe(values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in out:
            out.append(text)
    return out


def default_gspec_databases(
    code: str | None, *, registry: PathogenRegistry | None = None
) -> list[str]:
    """Registry default gspec databases for a species code (public helper)."""
    return _registry_gspec_defaults(registry or load_registry(), code or UNK)


def default_gmlst_plan(
    code: str | None, *, registry: PathogenRegistry | None = None
) -> GmlstPlan:
    """Registry default gmlst modes/schemes for a species code."""
    return _registry_gmlst_defaults(registry or load_registry(), code or UNK)


def _registry_gspec_defaults(registry: PathogenRegistry, code: str) -> list[str]:
    if code == UNK:
        return []
    spec = registry.pathogens.get(code)
    return list(spec.gspec_screens) if spec is not None else []


def _registry_gmlst_defaults(registry: PathogenRegistry, code: str) -> GmlstPlan:
    if code == UNK:
        return GmlstPlan()
    spec = registry.pathogens.get(code)
    if spec is None:
        return GmlstPlan()
    modes: list[GmlstMode] = []
    schemes: dict[str, str] = {}
    if spec.mlst_scheme:
        modes.append("mlst")
        schemes["mlst"] = spec.mlst_scheme
    if spec.cgmlst_scheme:
        modes.append("cgmlst")
        schemes["cgmlst"] = spec.cgmlst_scheme
    return GmlstPlan(modes=modes, schemes=schemes)


def _merge_gmlst(
    base: GmlstPlan, override: GmlstSelection, default_mode: str
) -> GmlstPlan:
    mode = override.mode or default_mode
    if override.modes is None:
        modes = list(base.modes)
    elif mode == "replace":
        modes = list(override.modes)
    else:
        modes = list(dict.fromkeys([*base.modes, *override.modes]))
    schemes = {**base.schemes, **override.schemes}
    return GmlstPlan(modes=modes, schemes=schemes)


def resolve_selection_path(
    path: str | Path | None = None, *, home: Path | None = None
) -> Path | None:
    """Resolve the overlay path: explicit → env → new file → legacy file."""
    if path is not None and str(path).strip():
        return Path(path).expanduser().resolve()
    for env_name in (TOOL_SELECTION_ENV, LEGACY_SELECTION_ENV):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return Path(env_value).expanduser().resolve()
    root = home or BACMAP_HOME
    for rel in (DEFAULT_SELECTION_REL, LEGACY_SELECTION_REL):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def load_selection(
    path: str | Path | None = None, *, home: Path | None = None
) -> ToolSelection:
    """Load the overlay; a missing file means "registry defaults only"."""
    resolved = resolve_selection_path(path, home=home)
    if resolved is None or not resolved.is_file():
        return ToolSelection()
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SelectionError(f"cannot read tool selection {resolved}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SelectionError(f"tool selection is not valid YAML ({resolved}): {exc}") from exc
    return load_selection_data(raw, source=str(resolved))


def load_selection_data(raw: Any, *, source: str = "<memory>") -> ToolSelection:
    """Validate an in-memory document (used by ``selection select --from-json``)."""
    if raw is None:
        return ToolSelection()
    if not isinstance(raw, dict):
        raise SelectionError(f"tool selection must be a mapping ({source})")
    try:
        return ToolSelection.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError carries the field detail
        raise SelectionError(f"invalid tool selection ({source}): {exc}") from exc


def selection_to_yaml(selection: ToolSelection) -> str:
    """Deterministic YAML (sorted species/sample keys, schema first)."""
    payload: dict[str, Any] = {"schema": SCHEMA}
    defaults: dict[str, Any] = {}
    if selection.defaults.gspec.mode != "extend":
        defaults["gspec"] = {"mode": selection.defaults.gspec.mode}
    if selection.defaults.gmlst.mode != "extend":
        defaults["gmlst"] = {"mode": selection.defaults.gmlst.mode}
    if defaults:
        payload["defaults"] = defaults
    if selection.species:
        payload["species"] = {
            code: _entry_payload(selection.species[code])
            for code in sorted(selection.species)
        }
    if selection.samples:
        payload["samples"] = {
            sample: _entry_payload(selection.samples[sample])
            for sample in sorted(selection.samples)
        }
    meta = selection.meta.model_dump(exclude_defaults=True)
    if meta:
        payload["meta"] = meta
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def _entry_payload(entry: SpeciesSelection | SampleSelection) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if entry.gspec is not None:
        gspec: dict[str, Any] = {}
        if entry.gspec.mode is not None:
            gspec["mode"] = entry.gspec.mode
        gspec["databases"] = list(entry.gspec.databases)
        payload["gspec"] = gspec
    if entry.gmlst is not None:
        gmlst: dict[str, Any] = {}
        if entry.gmlst.mode is not None:
            gmlst["mode"] = entry.gmlst.mode
        if entry.gmlst.modes is not None:
            gmlst["modes"] = list(entry.gmlst.modes)
        if entry.gmlst.schemes:
            gmlst["schemes"] = dict(entry.gmlst.schemes)
        payload["gmlst"] = gmlst
    return payload


def write_selection(
    selection: ToolSelection, path: str | Path, *, backup: bool = True
) -> Path:
    """Atomically write the overlay (``.bak`` keeps the previous document)."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.is_file():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(selection_to_yaml(selection), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        raise SelectionError(f"cannot write tool selection {target}: {exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def file_hash(path: str | Path) -> str:
    """SHA256 of an existing file (empty string when absent)."""
    p = Path(path)
    if not p.is_file():
        return ""
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selection_signature(selection: ToolSelection) -> str:
    """Stable hash of the selection payload (for run records)."""
    blob = json.dumps(
        selection.model_dump(by_alias=True, mode="json"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_legacy_path(path: str | Path | None) -> bool:
    """True when the resolved overlay is the old ``db_selection.yaml``."""
    if path is None:
        return False
    return Path(path).name == LEGACY_SELECTION_REL.name


def validate_sample_id(sample: str) -> bool:
    """Same conservative sample-id shape used by the tool layer."""
    return bool(_SAMPLE_RE.match(sample))


def validate_species_code(code: str) -> bool:
    return code == UNK or bool(_CODE_RE.match(code))
