"""Pathogen registry — the single source of pathogen configuration.

Every rule file and analysis module derives its per-pathogen lookup tables
(marker genes, MLST / cgMLST schemes, AMRFinderPlus organisms, SNP groups)
from ``pathogens.yaml`` shipped inside the package. Adding a pathogen is a
yaml edit; no ``.smk`` file needs to change.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bacmap.config import DATA_DIR
from bacmap.core._pkg import pkg_dir


class RegistryError(Exception):
    """Raised when pathogens.yaml violates the registry contract."""


_PATHOGEN_FIELDS = frozenset(
    {
        "display_name",
        "species_label",
        "marker_genes",
        "mlst_scheme",
        "cgmlst_scheme",
        "amrfinder_organism",
        "serotype_engine",
        "pathotype",
        "snp_group",
        "enabled",
    }
)
_PATHOGEN_REQUIRED = ("display_name", "marker_genes", "mlst_scheme", "snp_group")
_SNP_GROUP_FIELDS = frozenset({"ref", "species", "organism"})
_MARKER_CONFIDENCE = "high"


@dataclass(frozen=True)
class PathogenSpec:
    name: str
    display_name: str
    marker_genes: tuple[str, ...]
    mlst_scheme: str
    snp_group: str
    species_label: str
    cgmlst_scheme: str | None = None
    amrfinder_organism: str | None = None
    serotype_engine: str | None = None
    pathotype: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class SnpGroup:
    name: str
    ref: Path
    species: tuple[str, ...]
    organism: str


@dataclass(frozen=True)
class WorkflowTables:
    mlst_schemes: dict[str, str]
    cgmlst_schemes: dict[str, str]
    amrfinder_organisms: dict[str, str]
    gene_to_species: dict[str, tuple[str, str]]
    species_priority: list[str]
    snp_groups: dict[str, dict[str, Any]]
    cgmlst_species_groups: dict[str, dict[str, Any]]
    signature: str


@dataclass(frozen=True)
class PathogenRegistry:
    pathogens: dict[str, PathogenSpec] = field(default_factory=dict)
    snp_group_specs: dict[str, SnpGroup] = field(default_factory=dict)

    def mlst_schemes(self) -> dict[str, str]:
        return {name: p.mlst_scheme for name, p in self.pathogens.items() if p.enabled}

    def cgmlst_schemes(self) -> dict[str, str]:
        return {
            name: p.cgmlst_scheme
            for name, p in self.pathogens.items()
            if p.enabled and p.cgmlst_scheme is not None
        }

    def amrfinder_organisms(self) -> dict[str, str]:
        return {
            name: p.amrfinder_organism
            for name, p in self.pathogens.items()
            if p.enabled and p.amrfinder_organism is not None
        }

    def species_markers(self) -> tuple[dict[str, tuple[str, str]], list[str]]:
        gene_map: dict[str, tuple[str, str]] = {}
        priority: list[str] = []
        for p in self.pathogens.values():
            if not p.enabled:
                continue
            for gene in p.marker_genes:
                gene_map[gene] = (p.species_label, _MARKER_CONFIDENCE)
                priority.append(gene)
        return gene_map, priority

    def snp_groups(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "ref": str(g.ref),
                "species": list(g.species),
                "organism": g.organism,
            }
            for name, g in self.snp_group_specs.items()
        }

    def cgmlst_species_groups(self) -> dict[str, dict[str, Any]]:
        """Cohort groups keyed by group name; scheme from first member that declares one."""
        groups: dict[str, dict[str, Any]] = {}
        for name, g in self.snp_group_specs.items():
            scheme = next(
                (
                    p.cgmlst_scheme
                    for p in (self.pathogens.get(s) for s in g.species)
                    if p is not None and p.cgmlst_scheme is not None
                ),
                None,
            )
            if scheme is None:
                continue
            groups[name] = {
                "species": list(g.species),
                "organism": g.organism,
                "scheme": scheme,
            }
        return groups

    def signature(self) -> str:
        payload = {
            "pathogens": {
                name: {
                    "display_name": p.display_name,
                    "species_label": p.species_label,
                    "marker_genes": list(p.marker_genes),
                    "mlst_scheme": p.mlst_scheme,
                    "cgmlst_scheme": p.cgmlst_scheme,
                    "amrfinder_organism": p.amrfinder_organism,
                    "serotype_engine": p.serotype_engine,
                    "pathotype": p.pathotype,
                    "snp_group": p.snp_group,
                    "enabled": p.enabled,
                }
                for name, p in sorted(self.pathogens.items())
            },
            "snp_groups": {
                name: {
                    "ref": str(g.ref),
                    "species": list(g.species),
                    "organism": g.organism,
                }
                for name, g in sorted(self.snp_group_specs.items())
            },
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_pathogen(name: str, raw: dict[str, Any]) -> PathogenSpec:
    unknown = set(raw) - _PATHOGEN_FIELDS
    if unknown:
        raise RegistryError(
            f"pathogen {name!r}: unknown field(s) {sorted(unknown)}; "
            f"allowed: {sorted(_PATHOGEN_FIELDS)}"
        )
    missing = [f for f in _PATHOGEN_REQUIRED if f not in raw]
    if missing:
        raise RegistryError(f"pathogen {name!r}: missing required field(s) {missing}")

    marker_genes = tuple(g.lower() for g in raw["marker_genes"])
    if not marker_genes:
        raise RegistryError(f"pathogen {name!r}: marker_genes must not be empty")

    return PathogenSpec(
        name=name,
        display_name=str(raw["display_name"]),
        species_label=str(raw.get("species_label", name)),
        marker_genes=marker_genes,
        mlst_scheme=str(raw["mlst_scheme"]),
        cgmlst_scheme=raw.get("cgmlst_scheme"),
        amrfinder_organism=raw.get("amrfinder_organism"),
        serotype_engine=raw.get("serotype_engine"),
        pathotype=raw.get("pathotype"),
        snp_group=str(raw["snp_group"]),
        enabled=bool(raw.get("enabled", True)),
    )


def _validate_snp_group(name: str, raw: dict[str, Any]) -> SnpGroup:
    unknown = set(raw) - _SNP_GROUP_FIELDS
    if unknown:
        raise RegistryError(
            f"snp_group {name!r}: unknown field(s) {sorted(unknown)}; "
            f"allowed: {sorted(_SNP_GROUP_FIELDS)}"
        )
    for required in ("ref", "species", "organism"):
        if required not in raw:
            raise RegistryError(f"snp_group {name!r}: missing field {required!r}")
    return SnpGroup(
        name=name,
        ref=(DATA_DIR / str(raw["ref"]).removeprefix("data/")).resolve(),
        species=tuple(raw["species"]),
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

    pathogens_raw = raw.get("pathogens") or {}
    snp_groups_raw = raw.get("snp_groups") or {}

    pathogens = {name: _validate_pathogen(name, spec) for name, spec in pathogens_raw.items()}
    snp_groups = {name: _validate_snp_group(name, spec) for name, spec in snp_groups_raw.items()}

    seen_genes: dict[str, str] = {}
    for name, p in pathogens.items():
        for gene in p.marker_genes:
            if gene in seen_genes:
                raise RegistryError(
                    f"marker gene {gene!r} claimed by both {seen_genes[gene]!r} and {name!r}"
                )
            seen_genes[gene] = name
        if p.snp_group not in snp_groups:
            raise RegistryError(f"pathogen {name!r} references unknown snp_group {p.snp_group!r}")

    for group in snp_groups.values():
        for species in group.species:
            if species not in pathogens:
                raise RegistryError(
                    f"snp_group {group.name!r} lists unregistered species {species!r}"
                )

    return PathogenRegistry(pathogens=pathogens, snp_group_specs=snp_groups)


def load_registry(path: str | Path | None = None) -> PathogenRegistry:
    if path is not None:
        return _load(Path(path))
    env = os.environ.get("BACMAP_PATHOGEN_REGISTRY")
    return _load_cached(str(Path(env).resolve() if env else default_registry_path()))


@lru_cache(maxsize=1)
def get_workflow_tables() -> WorkflowTables:
    reg = load_registry()
    gene_map, priority = reg.species_markers()
    return WorkflowTables(
        mlst_schemes=reg.mlst_schemes(),
        cgmlst_schemes=reg.cgmlst_schemes(),
        amrfinder_organisms=reg.amrfinder_organisms(),
        gene_to_species=dict(gene_map),
        species_priority=priority,
        snp_groups=reg.snp_groups(),
        cgmlst_species_groups=reg.cgmlst_species_groups(),
        signature=reg.signature(),
    )
