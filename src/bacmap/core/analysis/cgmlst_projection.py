"""cgMLST nearest-neighbour projection against a local reference library.

Given a query sample's cgMLST allele profile and a library of reference
profiles, ``project_sample`` ranks the references by Hamming allele distance,
picks the ``top_n`` nearest, and emits a per-species verdict
(``OUTBREAK`` / ``RELATED`` / ``UNRELATED`` / ``UNDETERMINED``) using
thresholds loaded from ``workflows/bacmap/config/config.yaml``.

Distance definition (EnteroBase HierCC convention, Zhou 2020):

    d(A, B) = number of loci where BOTH A and B have a non-None allele call
              AND the calls differ. Loci missing on either side (None) are
              excluded from the comparison -- not counted as differences and
              not counted as matches either. This matches the pairwise rule in
              ``analysis/cgmlst_distance.py`` (cohort) and the reference Hamming
              used by the ``tests/fixtures/cgmlst_reference/synthetic_5.tsv``
              golden-distance contract tests.

Verdict tiering is designed from scratch here: the repo has no pre-existing
tiered verdict pattern. ``deterministic_verifier.py`` uses a binary
``CheckResult(passed: bool)``; only the DATACLASS *style* (frozen value
objects with a details/message field set) is borrowed from it, not any verdict
logic. Threshold numbers are NEVER hardcoded -- they come from
``CgmlstThresholds`` (populated by ``load_thresholds_from_config``).

References:
    * Zhou, Z., Alikhan, N. F., Sergeant, M. J., et al. (2020). The EnteroBase
      user's guide. Genome Res 30:1-14 (HierCC pairwise missing exclusion).
    * Hawkey, J. et al. (2021). Nat Commun (S. sonnei HC5/HC10 unreliable).
    * Achtman, M. et al. (2022). bioRxiv (V. parahaemolyticus HC1090 only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .cgmlst_types import CgmlstProfile

# Caveat strings (single source of truth -- the report card and skill quote
# these verbatim, so keeping them as named constants avoids wording drift).
_S_SONNEI_CAVEAT = "HC5/HC10 unreliable for S. sonnei, confirm with SNV"
_NO_THRESHOLD_CAVEAT = "no published cgMLST outbreak threshold, local calibration required"
_ZERO_CALLED_CAVEAT = "query profile has 0 called loci; distance is uninformative"

# Species-name aliases -> config.yaml ``cgmlst.thresholds.<key>`` normalisation.
# The config keys are lowercase short forms (``ecoli`` / ``vparahaemolyticus``);
# callers may pass full Latin names or the dotted short forms used elsewhere in
# the repo (``E.coli`` / ``V.parahaemolyticus``). All are folded to the key.
_SPECIES_KEY_ALIASES: dict[str, str] = {
    "salmonella": "salmonella",
    "ecoli": "ecoli",
    "escherichiacoli": "ecoli",
    "shigella": "shigella",
    "vparahaemolyticus": "vparahaemolyticus",
    "vibrioparahaemolyticus": "vparahaemolyticus",
}


class Verdict(StrEnum):
    """Per-species cgMLST trace-back verdict for a query sample.

    ``StrEnum`` so ``str(Verdict.OUTBREAK) == "outbreak"`` -- the bio_cgmlst
    tool (todo 10) serialises verdicts to JSON without a custom encoder.
    """

    OUTBREAK = "outbreak"
    RELATED = "related"
    UNRELATED = "unrelated"
    UNDETERMINED = "undetermined"


@dataclass(frozen=True)
class CgmlstThresholds:
    """Per-species allele-distance thresholds (loaded from config.yaml).

    All fields may be ``None`` for species with no published outbreak boundary
    (V. parahaemolyticus): both ``None`` -> verdict ``UNDETERMINED`` with the
    "no published threshold" caveat.

    Attributes:
        outbreak_allele_dist: Max allele distance for the OUTBREAK tier
            (e.g. Salmonella HC5/HC10 = 10, Zhou 2020). ``None`` means no
            published outbreak boundary.
        related_allele_dist: Max allele distance for the RELATED tier (e.g.
            HierCC HC50 = 50). Distances above this are UNRELATED. ``None``
            means the related tier cannot be resolved either.
        clonal_allele_dist: Optional tighter clonal sub-threshold (e.g.
            Salmonella ST11/ST34 = 3, Ferrato 2023). Carried for audit/reporting
            only; the current verdict logic does not introduce a separate
            CLONAL tier (kept as an informational field for downstream skill /
            report rendering).
    """

    outbreak_allele_dist: int | None
    related_allele_dist: int | None
    clonal_allele_dist: int | None = None


@dataclass(frozen=True)
class NearestMatch:
    """A single reference sample ranked by distance to the query.

    Attributes:
        sample_id: Reference sample identifier (``File`` column).
        distance: Hamming allele distance query -> this reference (HierCC
            convention: missing-on-either excluded).
    """

    sample_id: str
    distance: int


@dataclass(frozen=True)
class ProjectionResult:
    """Outcome of projecting one query profile against a reference library.

    Attributes:
        sample_id: The query sample id.
        nearest: The ``top_n`` nearest references, ascending by distance with a
            deterministic sample-id tie-break. May be shorter than ``top_n`` if
            the reference library is smaller.
        verdict: Per-species tiered verdict.
        threshold_used: The thresholds applied to reach ``verdict``. ``None`` is
            allowed for callers that project without thresholds (verdict will be
            ``UNDETERMINED``); ``project_sample`` always forwards the thresholds
            it was given.
        species: The species string the caller used to select thresholds /
            caveats (verbatim, e.g. ``"Salmonella"``, ``"Shigella sonnei"``).
        caveats: Free-form warning strings (S. sonnei SNV-confirm, Vpara
            no-threshold, 0-called-loci, etc.). Empty when no caveat applies.
        n_comparable_loci: Number of loci where BOTH the query AND the nearest
            reference have a non-None allele call -- i.e. the denominator that
            produced ``nearest[0].distance``. Low values weaken the verdict.
    """

    sample_id: str
    nearest: list[NearestMatch] = field(default_factory=list)
    verdict: Verdict = Verdict.UNDETERMINED
    threshold_used: CgmlstThresholds | None = None
    species: str = ""
    caveats: list[str] = field(default_factory=list)
    n_comparable_loci: int = 0


def _hamming_with_comparable(
    a: dict[str, int | None],
    b: dict[str, int | None],
) -> tuple[int, int]:
    """Return ``(distance, n_comparable_loci)`` for two allele dicts.

    HierCC convention: a locus counts as comparable only when BOTH profiles
    have a non-None call; among comparable loci, distance is the count that
    differ. Iterates ``a`` and looks up ``b`` -- symmetric in practice because
    profiles share the same cgMLST scheme locus keys.
    """
    diff = 0
    comparable = 0
    for locus, a_allele in a.items():
        b_allele = b.get(locus)
        if a_allele is not None and b_allele is not None:
            comparable += 1
            if a_allele != b_allele:
                diff += 1
    return diff, comparable


def _is_ssonnei(species: str) -> bool:
    """True when the species string refers to Shigella sonnei.

    Accepts ``"Shigella sonnei"``, ``"S. sonnei"``, bare ``"sonnei"`` etc.
    (case-insensitive substring match). S. sonnei's HC5/HC10 clusters are
    unreliable (Hawkey 2021; Weill 2022) -> SNV confirmation caveat.
    """
    return "sonnei" in species.lower()


def _normalize_species_key(species: str) -> str:
    """Fold a caller-supplied species name to a ``cgmlst.thresholds.<key>``.

    Lowercases, strips dots/spaces, and applies the alias map so both the
    repo's short forms (``E.coli`` / ``V.parahaemolyticus``) and full Latin
    names (``Escherichia coli`` / ``Vibrio parahaemolyticus``) resolve to the
    config key. Unknown names are returned folded-but-unchanged so the caller
    gets a clear "no thresholds for <key>" error from the lookup.
    """
    folded = species.lower().replace(".", "").replace(" ", "")
    return _SPECIES_KEY_ALIASES.get(folded, folded)


def project_sample(
    profile: CgmlstProfile,
    reference: list[CgmlstProfile],
    thresholds: CgmlstThresholds,
    species: str,
    top_n: int = 10,
) -> ProjectionResult:
    """Project a query profile against a reference library + assign a verdict.

    Args:
        profile: The query sample's cgMLST profile.
        reference: Non-empty list of reference profiles to compare against.
        thresholds: Per-species thresholds (may carry ``None`` fields for
            species without a published outbreak boundary).
        species: Species string used both to select caveats (S. sonnei) and as
            an audit label on the result.
        top_n: Maximum number of nearest references to return. Defaults to 10
            (the ``cgmlst.projection.top_n`` config default).

    Returns:
        A populated ``ProjectionResult``. ``nearest`` is sorted ascending by
        ``(distance, sample_id)`` for a deterministic tie-break.

    Raises:
        ValueError: If ``reference`` is empty.

    Notes:
        * The query is NOT excluded from ``reference`` -- callers typically pass
          a reference library that does not contain the query; if it does, the
          query will appear at distance 0.
        * A query with 0 called loci yields ``Verdict.UNDETERMINED`` regardless
          of thresholds (the all-zero distances would be a false OUTBREAK).
        * Thresholds with both fields ``None`` yield ``Verdict.UNDETERMINED``
          and the "no published threshold" caveat (V. parahaemolyticus case).
    """
    if not reference:
        raise ValueError("project_sample requires at least one reference profile")

    matches: list[NearestMatch] = []
    comparable_by_id: dict[str, int] = {}
    for ref in reference:
        dist, comp = _hamming_with_comparable(profile.alleles, ref.alleles)
        matches.append(NearestMatch(sample_id=ref.sample_id, distance=dist))
        comparable_by_id[ref.sample_id] = comp

    # Deterministic ordering: distance ascending, then sample id alphabetically
    # so ties (common among outbreak-level near-identical profiles) are stable.
    matches.sort(key=lambda m: (m.distance, m.sample_id))
    nearest = matches[:top_n] if top_n > 0 else []

    min_dist = matches[0].distance
    # n_comparable_loci is reported against the nearest reference (the distance
    # that actually drove the verdict). Guard against an empty nearest list.
    nearest_id = nearest[0].sample_id if nearest else ""
    n_comparable = comparable_by_id.get(nearest_id, 0)

    caveats: list[str] = []

    has_any_threshold = (
        thresholds.outbreak_allele_dist is not None or thresholds.related_allele_dist is not None
    )

    if profile.n_called == 0:
        # Every reference distance is 0 (no comparable loci) -> a naive
        # threshold comparison would falsely flag this as OUTBREAK.
        verdict = Verdict.UNDETERMINED
        caveats.append(_ZERO_CALLED_CAVEAT)
    elif not has_any_threshold:
        # V. parahaemolyticus: only HC1090 species boundary is published
        # (Achtman 2022); no numeric outbreak/related threshold ships.
        verdict = Verdict.UNDETERMINED
        caveats.append(_NO_THRESHOLD_CAVEAT)
    else:
        outbreak = thresholds.outbreak_allele_dist
        related = thresholds.related_allele_dist
        if outbreak is not None and min_dist <= outbreak:
            verdict = Verdict.OUTBREAK
        elif related is not None and min_dist <= related:
            verdict = Verdict.RELATED
        else:
            verdict = Verdict.UNRELATED

    if _is_ssonnei(species):
        caveats.append(_S_SONNEI_CAVEAT)

    return ProjectionResult(
        sample_id=profile.sample_id,
        nearest=nearest,
        verdict=verdict,
        threshold_used=thresholds,
        species=species,
        caveats=caveats,
        n_comparable_loci=n_comparable,
    )


def load_thresholds_from_config(config_path: Path, species: str) -> CgmlstThresholds:
    """Load a species' cgMLST thresholds from ``workflows/bacmap/config/config.yaml``.

    Reads ``cgmlst.thresholds.<species>`` where ``<species>`` is the normalised
    key (``"salmonella"`` / ``"ecoli"`` / ``"shigella"`` /
    ``"vparahaemolyticus"``). The ``species`` argument accepts the repo's short
    forms (``"Salmonella"``, ``"E.coli"``, ``"Shigella"``,
    ``"V.parahaemolyticus"``) and full Latin names. Missing numeric fields
    default to ``None`` (the V. parahaemolyticus case, where
    ``outbreak_allele_dist: null`` in the YAML round-trips to ``None``).

    Args:
        config_path: Path to ``config.yaml``.
        species: Species name (any of the accepted aliases).

    Returns:
        A populated ``CgmlstThresholds``.

    Raises:
        ValueError: If the config file does not exist, or has no
            ``cgmlst.thresholds.<species>`` entry, or the entry is malformed.
    """
    if not config_path.exists():
        raise ValueError(f"config file not found: {config_path}")

    # Lazy import: PyYAML ships with snakemake in the pixi env (it is not a
    # direct dependency of the hermes_bacmap package). Mirrors the lazy import
    # in workflows/bacmap/scripts/generate_cgmlst_summary.py:_load_thresholds.
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - env-contract guard
        raise RuntimeError(
            "PyYAML is required to read cgMLST thresholds from config.yaml; "
            "it ships with snakemake in the pixi env"
        ) from e

    cfg: Any = yaml.safe_load(config_path.read_text()) or {}
    species_key = _normalize_species_key(species)
    species_cfg_raw: Any = cfg.get("cgmlst", {}).get("thresholds", {}).get(species_key)
    if not isinstance(species_cfg_raw, dict):
        raise ValueError(
            f"no cgmlst.thresholds.{species_key} block in {config_path} "
            f"(resolved species {species!r} -> key {species_key!r})"
        )

    def _opt_int(key: str) -> int | None:
        value = species_cfg_raw.get(key)
        if value is None:
            return None
        # YAML loads ints natively; reject non-ints defensively so a stray
        # string in the config fails loudly rather than silently coercing.
        if not isinstance(value, int):
            raise ValueError(
                f"cgmlst.thresholds.{species_key}.{key} must be int or null, "
                f"got {type(value).__name__}={value!r}"
            )
        return value

    return CgmlstThresholds(
        outbreak_allele_dist=_opt_int("outbreak_allele_dist"),
        related_allele_dist=_opt_int("related_allele_dist"),
        clonal_allele_dist=_opt_int("clonal_allele_dist"),
    )
