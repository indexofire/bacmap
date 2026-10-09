"""cgMLST type definitions — profile dataclass for the cgMLST pipeline.

The ``CgmlstProfile`` dataclass holds a parsed sample profile produced by
``gmlst typing cgmlst --format tsv`` (see
https://indexofire.github.io/gmlst/en/cgmlst_guide/ for the marker table).

Distance and projection logic lives elsewhere (``analysis/cgmlst_projection.py``
and ``analysis/cgmlst_distance.py``); this module is data-only on purpose so it
can be imported by ``utils.py`` without pulling in heavier dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CgmlstProfile:
    """A single sample's cgMLST allele profile.

    Attributes:
        sample_id: Sample identifier (``File`` column of the gmlst TSV).
        scheme: cgMLST scheme name, e.g. ``senterica_2``, ``ecoli_2``,
            ``vparahaemolyticus_3`` (all EnteroBase schemes).
        st_raw: Raw ``ST`` column value. For cgMLST schemes this is typically
            ``"-"`` because cgMLST uses HierCC clusters rather than a single ST;
            stored verbatim with no special handling.
        alleles: Locus name → called allele number. ``None`` for any of the
            non-exact marker classes (missing, novel, partial, ambiguous).
        n_called: Count of loci with an exact integer allele call. Equals the
            number of non-``None`` values in ``alleles``.
        n_total: Total number of loci in the scheme (``len(alleles)``).
        missing_loci: Loci whose call was ``-`` (missing) or ``NN?`` (partial /
            insufficient coverage). Stored verbatim, order preserved.
        novel_loci: Loci whose call was ``~NN`` (novel / closest allele).
        ambiguous_loci: Loci whose call was ``N,M`` (conflicting multicopy /
            paralogs).
    """

    sample_id: str
    scheme: str
    st_raw: str
    alleles: dict[str, int | None] = field(default_factory=dict)
    n_called: int = 0
    n_total: int = 0
    missing_loci: list[str] = field(default_factory=list)
    novel_loci: list[str] = field(default_factory=list)
    ambiguous_loci: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        ``alleles`` and the three locus lists are copied so the returned dict
        can be mutated without aliasing the dataclass's internal state.
        """
        return {
            "sample_id": self.sample_id,
            "scheme": self.scheme,
            "st_raw": self.st_raw,
            "alleles": dict(self.alleles),
            "n_called": self.n_called,
            "n_total": self.n_total,
            "missing_loci": list(self.missing_loci),
            "novel_loci": list(self.novel_loci),
            "ambiguous_loci": list(self.ambiguous_loci),
        }
