from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only: avoids the circular import with analysis.deterministic_verifier
    # (which imports parse_mlst from this module at load time). The runtime
    # import lives inside parse_cgmlst_profile(s).
    from .analysis.cgmlst_types import CgmlstProfile


def parse_mlst(mlst_tsv: str) -> dict[str, Any]:
    """Parse MLST TSV output into structured dict.

    Handles gmlst output format: header line + data line, tab-separated.
    Returns {"st": str, "alleles": {locus: allele}}.
    """
    if not mlst_tsv or mlst_tsv == "N/A":
        return {"st": "N/A", "alleles": {}}

    lines = mlst_tsv.strip().split("\n")
    if len(lines) < 2:
        return {"st": "N/A", "alleles": {}}

    header = lines[0].split("\t")
    data = lines[1].split("\t")

    result: dict[str, Any] = {"alleles": {}}
    for i, col in enumerate(header):
        if i >= len(data):
            break
        col_lower = col.lower()
        if col_lower == "st":
            result["st"] = data[i]
        else:
            result["alleles"][col_lower] = data[i]

    if "st" not in result:
        st_header_idx = None
        for i, col in enumerate(header):
            if col.lower() == "st":
                st_header_idx = i
                break
        if st_header_idx is not None and st_header_idx < len(data):
            result["st"] = data[st_header_idx]
        else:
            result["st"] = "N/A"

    return result


def parse_db_header(sseqid: str) -> tuple[str, str, str, str]:
    """Parse a 'db~~~gene~~~accession~~~product' FASTA/BLAST header.

    Returns (gene, accession, product, reserved); missing fields are "".
    Single implementation shared by gene_scanner and the KMA backend.
    """
    fields = sseqid.split("~~~")
    if len(fields) >= 4:
        return fields[1].strip(), fields[2].strip(), fields[3].strip(), ""
    if len(fields) >= 3:
        return fields[1].strip(), fields[2].strip(), "", ""
    if len(fields) >= 2:
        return fields[1].strip(), "", "", ""
    return sseqid.strip(), "", "", ""


def parse_abricate_tsv(tsv_text: str) -> list[dict[str, str]]:
    """Parse abricate-format TSV into list of dicts."""
    if not tsv_text:
        return []
    lines = tsv_text.strip().split("\n")
    if len(lines) < 2:
        return []
    header = [h.lstrip("#") for h in lines[0].split("\t")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))
        rows.append(dict(zip(header, parts)))
    return rows


def read_json_file(path: str | Path) -> dict[str, Any] | None:
    """Read and parse a JSON file, return None if missing or invalid."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        data: dict[str, Any] = json.loads(p.read_text())
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def _classify_cgmlst_allele(value: str) -> tuple[int | None, str]:
    """Classify a raw cgMLST allele cell into a (number, category) pair.

    Categories: ``"called"``, ``"novel"``, ``"missing"``, ``"ambiguous"``.
    The 6 documented gmlst markers (see
    https://indexofire.github.io/gmlst/en/cgmlst_guide/) are handled as:

        ``23``   → (23, "called")        exact call
        ``23*``  → (23, "called")        multicopy same allele, ``*`` stripped
        ``~23``  → (None, "novel")       novel / closest allele
        ``15?``  → (None, "missing")     partial / insufficient coverage
        ``1,2``  → (None, "ambiguous")   conflicting multicopy / paralogs
        ``-``    → (None, "missing")     missing locus

    Empty cells and any unrecognised tokens fall back to ``missing`` so a
    malformed TSV never crashes the parser.
    """
    v = value.strip()
    if v == "-" or v == "":
        return (None, "missing")
    if v.startswith("~"):
        return (None, "novel")
    if "," in v:
        return (None, "ambiguous")
    if v.endswith("*"):
        body = v[:-1]
        try:
            return (int(body), "called")
        except ValueError:
            return (None, "missing")
    if v.endswith("?"):
        return (None, "missing")
    try:
        return (int(v), "called")
    except ValueError:
        return (None, "missing")


def _cgmlst_header_indices(header: list[str]) -> tuple[int, int, int]:
    """Locate the File / Scheme / ST columns in a cgMLST header row.

    Returns ``(file_idx, scheme_idx, st_idx)``. Defaults to ``(0, 1, 2)`` which
    is the standard gmlst output order; columns are also matched case-insensitively
    so a lowercase header still resolves correctly.
    """
    file_idx, scheme_idx, st_idx = 0, 1, 2
    for i, col in enumerate(header):
        col_lower = col.lower()
        if col_lower == "file":
            file_idx = i
        elif col_lower == "scheme":
            scheme_idx = i
        elif col_lower == "st":
            st_idx = i
    return (file_idx, scheme_idx, st_idx)


def parse_cgmlst_profiles(tsv_text: str) -> list[CgmlstProfile]:
    """Parse a (possibly multi-sample) cgMLST TSV into a list of profiles.

    Format produced by ``gmlst typing cgmlst --format tsv``::

        File\\tScheme\\tST\\t<locus_1>\\t...\\t<locus_N>
        <sample>\\t<scheme>\\t<ST>\\t<allele_1>\\t...\\t<allele_N>

    All 6 gmlst allele markers are handled (see
    ``_classify_cgmlst_allele`` for the marker table).

    Empty / ``"N/A"`` / header-only input returns ``[]`` (matches the
    ``parse_mlst`` convention of returning defaults rather than raising).

    The fallback 3-column row ``File\\tScheme\\tST\\n<sample>\\t<scheme>\\tN/A``
    (emitted when the gmlst binary is unavailable — see typing_amr.smk) parses
    gracefully to a profile with ``n_total=0`` and all locus lists empty.
    """
    # Lazy import: analysis.deterministic_verifier imports parse_mlst from this
    # module at load time, so a top-level import here would create a cycle.
    from .analysis.cgmlst_types import CgmlstProfile

    if not tsv_text or tsv_text == "N/A":
        return []

    lines = tsv_text.strip().split("\n")
    if len(lines) < 2:
        return []

    header = lines[0].split("\t")
    file_idx, scheme_idx, st_idx = _cgmlst_header_indices(header)

    reserved = {file_idx, scheme_idx, st_idx}
    locus_cols = [(i, col) for i, col in enumerate(header) if i not in reserved]

    profiles: list[CgmlstProfile] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")

        sample_id = parts[file_idx] if file_idx < len(parts) else ""
        scheme = parts[scheme_idx] if scheme_idx < len(parts) else ""
        st_raw = parts[st_idx] if st_idx < len(parts) else ""

        alleles: dict[str, int | None] = {}
        missing_loci: list[str] = []
        novel_loci: list[str] = []
        ambiguous_loci: list[str] = []
        n_called = 0

        for col_idx, locus_name in locus_cols:
            raw = parts[col_idx] if col_idx < len(parts) else ""
            allele, category = _classify_cgmlst_allele(raw)
            alleles[locus_name] = allele
            if category == "called":
                n_called += 1
            elif category == "novel":
                novel_loci.append(locus_name)
            elif category == "ambiguous":
                ambiguous_loci.append(locus_name)
            else:
                missing_loci.append(locus_name)

        profiles.append(
            CgmlstProfile(
                sample_id=sample_id,
                scheme=scheme,
                st_raw=st_raw,
                alleles=alleles,
                n_called=n_called,
                n_total=len(locus_cols),
                missing_loci=missing_loci,
                novel_loci=novel_loci,
                ambiguous_loci=ambiguous_loci,
            )
        )

    return profiles


def parse_cgmlst_profile(tsv_text: str) -> CgmlstProfile:
    """Parse a single-sample cgMLST TSV. See ``parse_cgmlst_profiles`` for format.

    Expects exactly one data row. If two or more rows are present, raises
    ``ValueError`` directing the caller to ``parse_cgmlst_profiles`` rather
    than silently returning only the first profile.

    Empty / ``"N/A"`` / header-only input returns an empty ``CgmlstProfile``
    (``sample_id=""``, ``st_raw="N/A"``, ``n_called=0``, ``n_total=0``, all
    locus lists empty) — matches the ``parse_mlst`` convention.
    """
    # Lazy import — see parse_cgmlst_profiles for the cycle rationale.
    from .analysis.cgmlst_types import CgmlstProfile

    profiles = parse_cgmlst_profiles(tsv_text)
    if len(profiles) >= 2:
        raise ValueError(
            f"parse_cgmlst_profile received {len(profiles)} data rows; "
            "use parse_cgmlst_profiles for multi-sample input"
        )
    if not profiles:
        return CgmlstProfile(sample_id="", scheme="", st_raw="N/A")
    return profiles[0]
