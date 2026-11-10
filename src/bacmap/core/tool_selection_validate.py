"""Catalog validation, option documents, and diffs for tool selection.

Split from ``core.tool_selection`` so the persistence/merge module stays
small.  The live catalogs are fetched elsewhere
(``bacmap.tools.tool_catalog``); this module only parses and reasons over them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bacmap.core.pathogen_registry import PathogenRegistry, load_registry, resolve_species
from bacmap.core.species_codes import UNK
from bacmap.core.tool_selection import (
    GmlstMode,
    GmlstPlan,
    GmlstSelection,
    SelectionError,
    ToolSelection,
    default_gmlst_plan,
    default_gspec_databases,
    validate_sample_id,
    validate_species_code,
)

OPTIONS_SCHEMA: Literal["bacmap.tool_selection_options/1"] = (
    "bacmap.tool_selection_options/1"
)
DIFF_SCHEMA: Literal["bacmap.tool_selection_diff/1"] = (
    "bacmap.tool_selection_diff/1"
)


class DbCatalogEntry(BaseModel):
    """One ``gspec db list --json`` provider row (only fields we consume)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    vendor: str = ""
    dbtype: str = ""
    kind: Literal["gene", "cluster", "composite"] = "gene"
    typing: bool = False
    installed: bool = False
    indexed: bool = False
    records: int | None = None
    license: str = ""
    source: str = ""


class GmlstScheme(BaseModel):
    """One ``gmlst scheme list/show -f json`` row."""

    model_config = ConfigDict(extra="ignore")

    name: str
    organism: str = ""
    scheme_type: str = ""
    n_loci: int | None = None
    provider: str = ""
    display_name: str = ""
    downloaded: bool = False


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: Literal["error", "warning"]
    code: str
    message: str
    species: str = ""
    database: str = ""
    scheme: str = ""
    sample: str = ""


class ValidationReport(BaseModel):
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, code: str, message: str, **context: str) -> None:
        self.errors.append(ValidationIssue(level="error", code=code, message=message, **context))

    def warn(self, code: str, message: str, **context: str) -> None:
        self.warnings.append(
            ValidationIssue(level="warning", code=code, message=message, **context)
        )

    def raise_if_errors(self) -> None:
        if self.errors:
            detail = "; ".join(f"{issue.code}: {issue.message}" for issue in self.errors)
            raise SelectionError(detail)


class DbOption(BaseModel):
    name: str
    description: str = ""
    kind: str = ""
    typing: bool = False
    installed: bool = False
    source: str = ""
    license: str = ""
    default: bool = False
    selected: bool = False


class GmlstSchemeOption(BaseModel):
    name: str
    organism: str = ""
    scheme_type: str = ""
    n_loci: int | None = None
    provider: str = ""
    display_name: str = ""
    downloaded: bool = False
    default: bool = False
    selected: bool = False


class GmlstPlanOption(BaseModel):
    modes: list[str] = Field(default_factory=list)
    schemes: dict[str, str] = Field(default_factory=dict)


class GmlstSpeciesOption(BaseModel):
    defaults: GmlstPlanOption
    effective: GmlstPlanOption
    schemes: list[GmlstSchemeOption] = Field(default_factory=list)


class SpeciesOption(BaseModel):
    code: str
    display_name: str
    labels: list[str]
    defaults: list[str]
    effective: list[str]
    databases: list[DbOption]
    gmlst: GmlstSpeciesOption


class OptionsDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: Literal["bacmap.tool_selection_options/1"] = Field(
        default="bacmap.tool_selection_options/1", alias="schema"
    )
    selection_path: str = ""
    legacy_selection: bool = False
    catalog_available: bool = False
    catalog_hash: str = ""
    gmlst_catalog_available: bool = False
    gmlst_catalog_hash: str = ""
    registry_signature: str = ""
    species: list[SpeciesOption] = Field(default_factory=list)
    databases: list[DbOption] = Field(default_factory=list)
    gmlst_schemes: list[GmlstSchemeOption] = Field(default_factory=list)


class GmlstPlanDiff(BaseModel):
    defaults: GmlstPlanOption
    effective: GmlstPlanOption


class SpeciesDiff(BaseModel):
    code: str
    defaults: list[str]
    effective: list[str]
    added: list[str]
    removed: list[str]
    gmlst: GmlstPlanDiff | None = None


class SelectionDiff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: Literal["bacmap.tool_selection_diff/1"] = Field(
        default="bacmap.tool_selection_diff/1", alias="schema"
    )
    species: list[SpeciesDiff] = Field(default_factory=list)
    samples: dict[str, list[str]] = Field(default_factory=dict)
    gmlst_samples: dict[str, GmlstPlanOption] = Field(default_factory=dict)


def parse_catalog(payload: Mapping[str, Any]) -> dict[str, DbCatalogEntry]:
    """Parse a ``gspec.dblist/1`` document into name → entry."""
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise SelectionError("gspec db list --json: missing 'providers' array")
    out: dict[str, DbCatalogEntry] = {}
    for raw in providers:
        if not isinstance(raw, dict):
            raise SelectionError("gspec db list --json: provider row is not an object")
        name = str(raw.get("name") or "").strip()
        if not name:
            raise SelectionError("gspec db list --json: provider row without a name")
        out[name] = DbCatalogEntry.model_validate(raw)
    return out


def parse_gmlst_schemes(payload: Mapping[str, Any]) -> dict[str, GmlstScheme]:
    """Parse ``gmlst scheme list/show -f json`` into name → scheme."""
    data = payload.get("data")
    if isinstance(data, dict):
        rows: list[Any] = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise SelectionError("gmlst scheme JSON: missing 'data'")
    out: dict[str, GmlstScheme] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise SelectionError("gmlst scheme JSON: row is not an object")
        name = str(raw.get("scheme_name") or raw.get("name") or "").strip()
        if not name:
            raise SelectionError("gmlst scheme JSON: row without a scheme name")
        out[name] = GmlstScheme(
            name=name,
            organism=str(raw.get("organism") or ""),
            scheme_type=str(raw.get("scheme_type") or ""),
            n_loci=raw.get("n_loci") if isinstance(raw.get("n_loci"), int) else None,
            provider=str(raw.get("provider") or ""),
            display_name=str(raw.get("display_name") or ""),
            downloaded=bool(raw.get("downloaded", False)),
        )
    return out


def catalog_hash(catalog: Mapping[str, DbCatalogEntry]) -> str:
    """Stable hash of the catalog facts that change routing decisions."""
    rows = [
        {
            "name": entry.name,
            "kind": entry.kind,
            "typing": entry.typing,
            "installed": entry.installed,
            "source": entry.source,
            "license": entry.license,
        }
        for _, entry in sorted(catalog.items())
    ]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def gmlst_catalog_hash(catalog: Mapping[str, GmlstScheme]) -> str:
    rows = [
        {
            "name": entry.name,
            "type": entry.scheme_type,
            "downloaded": entry.downloaded,
            "provider": entry.provider,
        }
        for _, entry in sorted(catalog.items())
    ]
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_selection(
    selection: ToolSelection,
    *,
    registry: PathogenRegistry | None = None,
    catalog: Mapping[str, DbCatalogEntry] | None = None,
    gmlst_catalog: Mapping[str, GmlstScheme] | None = None,
    sample_types: Mapping[str, str] | None = None,
    sample_species: Mapping[str, str] | None = None,
) -> ValidationReport:
    """Deterministic validation of an overlay against registry + live catalogs."""
    reg = registry or load_registry()
    report = ValidationReport()
    catalog_available = bool(catalog)

    if catalog is not None and not catalog:
        report.warn(
            "CATALOG_UNAVAILABLE",
            "gspec db list returned no databases; names cannot be checked",
        )
    if gmlst_catalog is not None and not gmlst_catalog:
        report.warn(
            "GMLST_CATALOG_UNAVAILABLE",
            "gmlst scheme list returned no schemes; names cannot be checked",
        )

    for code, spec in sorted(selection.species.items()):
        if not validate_species_code(code):
            report.error(
                "INVALID_SPECIES_CODE",
                f"species key {code!r} is not a 3-letter code or UNK",
                species=code,
            )
            continue
        if code != UNK and code not in reg.pathogens:
            report.error(
                "UNKNOWN_SPECIES",
                f"species {code!r} is not in pathogens.yaml",
                species=code,
            )
        if spec.gspec is not None:
            for database in spec.gspec.databases:
                _check_database(
                    database,
                    species=code,
                    sample="",
                    report=report,
                    catalog=catalog,
                    catalog_available=catalog_available,
                    sample_types=sample_types,
                )
        if spec.gmlst is not None:
            _check_gmlst_plan(
                selection.effective_gmlst(code, registry=reg),
                species=code,
                sample="",
                report=report,
                catalog=gmlst_catalog,
                catalog_available=bool(gmlst_catalog),
            )

    for sample, sample_spec in sorted(selection.samples.items()):
        if not validate_sample_id(sample):
            report.error(
                "INVALID_SAMPLE_ID",
                f"sample key {sample!r} is not a safe sample id",
                sample=sample,
            )
        if sample_spec.gspec is not None:
            for database in sample_spec.gspec.databases:
                _check_database(
                    database,
                    species="",
                    sample=sample,
                    report=report,
                    catalog=catalog,
                    catalog_available=catalog_available,
                    sample_types=sample_types,
                )
        if sample_spec.gmlst is not None:
            sample_code = None
            if sample_species and sample_species.get(sample):
                sample_code = resolve_species(sample_species[sample])
            _check_gmlst_plan(
                selection.effective_gmlst(
                    sample_code, sample=sample, registry=reg
                ),
                species="",
                sample=sample,
                report=report,
                catalog=gmlst_catalog,
                catalog_available=bool(gmlst_catalog),
            )

    return report


def _check_database(
    database: str,
    *,
    species: str,
    sample: str,
    report: ValidationReport,
    catalog: Mapping[str, DbCatalogEntry] | None,
    catalog_available: bool,
    sample_types: Mapping[str, str] | None,
) -> None:
    if not database:
        report.error("EMPTY_DATABASE", "empty database name", species=species, sample=sample)
        return
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", database):
        report.error(
            "INVALID_DATABASE_NAME",
            f"database {database!r} is not a safe database name",
            species=species,
            database=database,
            sample=sample,
        )
        return
    if not catalog_available or catalog is None:
        return
    entry = catalog.get(database)
    if entry is None:
        report.error(
            "UNKNOWN_DATABASE",
            f"database {database!r} is not in the gspec catalog",
            species=species,
            database=database,
            sample=sample,
        )
        return

    if not entry.installed and entry.source != "bundled":
        report.warn(
            "DATABASE_NOT_INSTALLED",
            f"database {database!r} is not installed; run "
            f"`gspec db setup -d {database}` before analysis",
            species=species,
            database=database,
            sample=sample,
        )
    if entry.license and (
        "non-commercial" in entry.license.lower() or "gpl" in entry.license.lower()
    ):
        report.warn(
            "LICENSE_REVIEW",
            f"database {database!r} carries a restrictive license: {entry.license}",
            species=species,
            database=database,
            sample=sample,
        )
    if (
        entry.kind in {"cluster", "composite"}
        and sample_types is not None
        and sample_types.get(sample) == "reads"
    ):
        report.warn(
            "CLUSTER_DB_ON_READS",
            f"database {database!r} is cluster-kind and cannot screen reads; "
            "the workflow will skip it for read samples",
            species=species,
            database=database,
            sample=sample,
        )


def _check_gmlst_plan(
    plan: GmlstPlan,
    *,
    species: str,
    sample: str,
    report: ValidationReport,
    catalog: Mapping[str, GmlstScheme] | None,
    catalog_available: bool,
) -> None:
    _check_gmlst(
        GmlstSelection(modes=plan.modes, schemes=plan.schemes),
        species=species,
        sample=sample,
        report=report,
        catalog=catalog,
        catalog_available=catalog_available,
    )


def _check_gmlst(
    spec: GmlstSelection,
    *,
    species: str,
    sample: str,
    report: ValidationReport,
    catalog: Mapping[str, GmlstScheme] | None,
    catalog_available: bool,
) -> None:
    _check_gmlst_modes(
        spec.modes, report=report, species=species, sample=sample
    )
    _check_gmlst_scheme_keys(
        spec.schemes, report=report, species=species, sample=sample
    )
    modes = spec.modes or []
    for mode in modes:
        if mode == "tgmlst":
            continue
        scheme = str(spec.schemes.get(mode) or "").strip()
        _check_gmlst_scheme(
            mode,
            scheme,
            report=report,
            species=species,
            sample=sample,
            catalog=catalog,
            catalog_available=catalog_available,
        )


def _check_gmlst_modes(
    modes: list[GmlstMode] | None,
    *,
    report: ValidationReport,
    species: str,
    sample: str,
) -> None:
    if modes is None:
        return
    allowed = {"mlst", "cgmlst", "wgmlst", "tgmlst"}
    for mode in modes:
        if mode not in allowed:
            report.error(
                "INVALID_GMLST_MODE",
                f"gmlst mode {mode!r} is not one of {sorted(allowed)}",
                species=species,
                sample=sample,
            )
    if "cgmlst" in modes and "wgmlst" in modes:
        report.error(
            "GMLST_MODE_CONFLICT",
            "cgmlst and wgmlst are alternative schemes and cannot both run",
            species=species,
            sample=sample,
        )


def _check_gmlst_scheme_keys(
    schemes: dict[str, str],
    *,
    report: ValidationReport,
    species: str,
    sample: str,
) -> None:
    for key in schemes:
        if key not in {"mlst", "cgmlst", "wgmlst"}:
            report.error(
                "INVALID_GMLST_SCHEME_KEY",
                f"gmlst scheme key {key!r} must be mlst/cgmlst/wgmlst",
                species=species,
                scheme=key,
                sample=sample,
            )
    if "tgmlst" in schemes:
        report.error(
            "GMLST_TGMLST_SCHEME",
            "tgmlst is scheme-free; remove schemes.tgmlst",
            species=species,
            sample=sample,
        )


def _check_gmlst_scheme(
    mode: str,
    scheme: str,
    *,
    report: ValidationReport,
    species: str,
    sample: str,
    catalog: Mapping[str, GmlstScheme] | None,
    catalog_available: bool,
) -> None:
    if not scheme:
        report.error(
            "GMLST_SCHEME_MISSING",
            f"gmlst mode {mode!r} requires schemes.{mode}",
            species=species,
            sample=sample,
        )
        return
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", scheme):
        report.error(
            "INVALID_GMLST_SCHEME_NAME",
            f"gmlst scheme {scheme!r} is not a safe scheme name",
            species=species,
            scheme=scheme,
            sample=sample,
        )
        return
    if not catalog_available or catalog is None:
        return
    entry = catalog.get(scheme)
    if entry is None:
        report.error(
            "UNKNOWN_GMLST_SCHEME",
            f"gmlst scheme {scheme!r} is not in the gmlst catalog",
            species=species,
            scheme=scheme,
            sample=sample,
        )
        return
    expected = {
        "mlst": {"mlst"},
        "cgmlst": {"cgmlst"},
        "wgmlst": {"wgmlst"},
    }.get(mode, set())
    if expected and entry.scheme_type not in expected:
        report.error(
            "GMLST_SCHEME_TYPE",
            f"gmlst mode {mode!r} requires a {mode} scheme; "
            f"{scheme!r} is {entry.scheme_type or 'unknown'}",
            species=species,
            scheme=scheme,
            sample=sample,
        )
    if not entry.downloaded:
        report.warn(
            "GMLST_SCHEME_NOT_DOWNLOADED",
            f"gmlst scheme {scheme!r} is not cached; run "
            f"`gmlst scheme download {scheme}` before analysis",
            species=species,
            scheme=scheme,
            sample=sample,
        )


def _catalog_options(
    catalog: Mapping[str, DbCatalogEntry] | None,
    *,
    defaults: list[str],
    effective: list[str],
    include_all: bool = True,
) -> list[DbOption]:
    names = set(defaults) | set(effective)
    if catalog is None:
        ordered = list(dict.fromkeys([*defaults, *effective]))
        return [
            DbOption(
                name=name,
                default=name in defaults,
                selected=name in effective,
            )
            for name in ordered
        ]
    return [
        DbOption(
            name=entry.name,
            description=entry.description,
            kind=entry.kind,
            typing=entry.typing,
            installed=entry.installed,
            source=entry.source,
            license=entry.license,
            default=entry.name in defaults,
            selected=entry.name in effective,
        )
        for _, entry in sorted(catalog.items())
        if include_all or entry.name in names
    ]


def _gmlst_options(
    catalog: Mapping[str, GmlstScheme] | None,
    *,
    defaults: GmlstPlan,
    effective: GmlstPlan,
    include_all: bool = True,
    candidates: set[str] | None = None,
) -> list[GmlstSchemeOption]:
    names = set(defaults.schemes.values()) | set(effective.schemes.values())
    default_names = set(defaults.schemes.values())
    selected_names = set(effective.schemes.values())
    if catalog is None:
        ordered = list(dict.fromkeys([*default_names, *selected_names]))
        return [
            GmlstSchemeOption(
                name=name,
                default=name in default_names,
                selected=name in selected_names,
            )
            for name in ordered
        ]
    return [
        GmlstSchemeOption(
            name=entry.name,
            organism=entry.organism,
            scheme_type=entry.scheme_type,
            n_loci=entry.n_loci,
            provider=entry.provider,
            display_name=entry.display_name,
            downloaded=entry.downloaded,
            default=entry.name in default_names,
            selected=entry.name in selected_names,
        )
        for _, entry in sorted(catalog.items())
        if (candidates is None or entry.name in candidates)
        and (include_all or entry.name in names)
    ]


def _scheme_matches_species(entry: GmlstScheme, labels: list[str]) -> bool:
    """Cheap organism filter: every long label token appears in the organism."""
    organism = re.sub(r"[^a-z0-9]+", " ", entry.organism.lower())
    tokens: set[str] = set()
    for label in labels:
        for token in re.split(r"[^a-z0-9]+", label.lower()):
            if len(token) >= 4:
                tokens.add(token)
    return bool(tokens) and all(token in organism for token in tokens)


def _plan_option(plan: GmlstPlan) -> GmlstPlanOption:
    return GmlstPlanOption(modes=list(plan.modes), schemes=dict(plan.schemes))


def build_options(
    selection: ToolSelection,
    *,
    registry: PathogenRegistry | None = None,
    catalog: Mapping[str, DbCatalogEntry] | None = None,
    gmlst_catalog: Mapping[str, GmlstScheme] | None = None,
    species: str | None = None,
    selection_path: str = "",
    legacy_selection: bool = False,
) -> OptionsDocument:
    """The AI/CLI option document: species defaults + live tool catalogs."""
    reg = registry or load_registry()
    wanted: str | None = None
    if species:
        if species.upper() == UNK:
            wanted = UNK
        else:
            wanted = reg.resolve(species)
            if wanted is None:
                raise SelectionError(f"unknown species: {species!r}")

    species_rows: list[SpeciesOption] = []
    for code, spec in sorted(reg.pathogens.items()):
        if wanted is not None and code != wanted:
            continue
        defaults = default_gspec_databases(code, registry=reg)
        effective = selection.effective_gspec_databases(code, registry=reg)
        gmlst_defaults = default_gmlst_plan(code, registry=reg)
        gmlst_effective = selection.effective_gmlst(code, registry=reg)
        gmlst_candidates: set[str] | None = None
        if wanted is not None and gmlst_catalog:
            gmlst_candidates = set(gmlst_defaults.schemes.values()) | set(
                gmlst_effective.schemes.values()
            )
            gmlst_candidates |= {
                name
                for name, entry in gmlst_catalog.items()
                if _scheme_matches_species(entry, list(spec.gside_labels))
            }
        species_rows.append(
            SpeciesOption(
                code=code,
                display_name=spec.display_name,
                labels=list(spec.gside_labels),
                defaults=defaults,
                effective=effective,
                databases=_catalog_options(
                    catalog,
                    defaults=defaults,
                    effective=effective,
                    include_all=wanted is not None,
                ),
                gmlst=GmlstSpeciesOption(
                    defaults=_plan_option(gmlst_defaults),
                    effective=_plan_option(gmlst_effective),
                    schemes=_gmlst_options(
                        gmlst_catalog,
                        defaults=gmlst_defaults,
                        effective=gmlst_effective,
                        include_all=wanted is not None,
                        candidates=gmlst_candidates,
                    ),
                ),
            )
        )

    if wanted == UNK:
        effective = selection.effective_gspec_databases(UNK, registry=reg)
        gmlst_effective = selection.effective_gmlst(UNK, registry=reg)
        species_rows.append(
            SpeciesOption(
                code=UNK,
                display_name="未识别",
                labels=["Unknown"],
                defaults=[],
                effective=effective,
                databases=_catalog_options(
                    catalog, defaults=[], effective=effective, include_all=True
                ),
                gmlst=GmlstSpeciesOption(
                    defaults=GmlstPlanOption(),
                    effective=_plan_option(gmlst_effective),
                    schemes=_gmlst_options(
                        gmlst_catalog,
                        defaults=GmlstPlan(),
                        effective=gmlst_effective,
                        include_all=True,
                    ),
                ),
            )
        )

    all_options = _catalog_options(
        catalog, defaults=[], effective=[], include_all=True
    )
    all_scheme_names: set[str] = set()
    for row in species_rows:
        all_scheme_names |= set(row.gmlst.defaults.schemes.values())
        all_scheme_names |= set(row.gmlst.effective.schemes.values())
    all_schemes = _gmlst_options(
        gmlst_catalog,
        defaults=GmlstPlan(),
        effective=GmlstPlan(),
        include_all=True,
        candidates=all_scheme_names,
    )
    return OptionsDocument(
        selection_path=selection_path,
        legacy_selection=legacy_selection,
        catalog_available=bool(catalog),
        catalog_hash=catalog_hash(catalog) if catalog else "",
        gmlst_catalog_available=bool(gmlst_catalog),
        gmlst_catalog_hash=gmlst_catalog_hash(gmlst_catalog) if gmlst_catalog else "",
        registry_signature=reg.signature(),
        species=species_rows,
        databases=all_options,
        gmlst_schemes=all_schemes,
    )


def diff_against_defaults(
    selection: ToolSelection,
    *,
    registry: PathogenRegistry | None = None,
) -> SelectionDiff:
    """Only the species/samples whose effective plan differs from the registry."""
    reg = registry or load_registry()
    rows: list[SpeciesDiff] = []
    for code in sorted(reg.pathogens):
        defaults = default_gspec_databases(code, registry=reg)
        effective = selection.effective_gspec_databases(code, registry=reg)
        gmlst_defaults = default_gmlst_plan(code, registry=reg)
        gmlst_effective = selection.effective_gmlst(code, registry=reg)
        gspec_changed = defaults != effective
        gmlst_changed = gmlst_defaults != gmlst_effective
        if not gspec_changed and not gmlst_changed:
            continue
        rows.append(
            SpeciesDiff(
                code=code,
                defaults=defaults,
                effective=effective,
                added=[name for name in effective if name not in defaults],
                removed=[name for name in defaults if name not in effective],
                gmlst=(
                    GmlstPlanDiff(
                        defaults=_plan_option(gmlst_defaults),
                        effective=_plan_option(gmlst_effective),
                    )
                    if gmlst_changed
                    else None
                ),
            )
        )
    return SelectionDiff(
        species=rows,
        samples={
            sample: list(entry.gspec.databases)
            for sample, entry in sorted(selection.samples.items())
            if entry.gspec is not None
        },
        gmlst_samples={
            sample: GmlstPlanOption(
                modes=list(entry.gmlst.modes or []),
                schemes=dict(entry.gmlst.schemes),
            )
            for sample, entry in sorted(selection.samples.items())
            if entry.gmlst is not None
        },
    )
