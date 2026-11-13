from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only: avoids the circular import with analysis.deterministic_verifier
    # (which imports parse_mlst from this module at load time). The runtime
    # import lives inside parse_cgmlst_profile(s).
    from .analysis.cgmlst_types import CgmlstProfile


_MLST_META_COLUMNS = frozenset({"file", "scheme", "st"})


def _mlst_from_native(payload: dict[str, Any]) -> dict[str, Any]:
    """gmlst ``typing mlst --format json`` → 归一结构（st/scheme/alleles）。"""
    rows = payload.get("data")
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    raw_calls = row.get("allele_calls")
    calls: dict[str, Any] = raw_calls if isinstance(raw_calls, dict) else {}
    alleles: dict[str, str] = {}
    for locus, call in calls.items():
        if not isinstance(call, dict):
            continue
        allele_id = call.get("allele_id")
        if allele_id not in (None, ""):
            alleles[str(locus).lower()] = str(allele_id)
    result: dict[str, Any] = {
        "st": "N/A" if row.get("st") in (None, "") else str(row.get("st")),
        "scheme": str(row.get("scheme") or ""),
        "alleles": alleles,
    }
    for key in ("score", "status"):
        if row.get(key) is not None:
            result[key] = row[key]
    return result


def _mlst_from_tsv(text: str) -> dict[str, Any]:
    """旧版 ``gmlst typing mlst`` TSV（header + 数据行）→ 归一结构。"""
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return {"st": "N/A", "scheme": "", "alleles": {}}
    header = lines[0].split("\t")
    data = lines[1].split("\t")
    result: dict[str, Any] = {"st": "N/A", "scheme": "", "alleles": {}}
    for i, col in enumerate(header):
        if i >= len(data):
            break
        key = col.strip().lower()
        value = data[i]
        if key == "st":
            result["st"] = value
        elif key == "scheme":
            result["scheme"] = value
        elif key == "file":
            continue
        else:
            result["alleles"][key] = value
    return result


def parse_mlst(value: Any) -> dict[str, Any]:
    """MLST 结果 → ``{"st", "scheme", "alleles"}``（三形态兼容，v1.10.26）。

    结果产物统一为 JSON（``typing/mlst.json``，gmlst ``--format json``）；
    这里同时接受：

    - 已归一的 dict（summary ``steps.mlst``）；
    - gmlst 原生 JSON（dict 或 JSON 文本，``{"schema_version","data":[...]}``）；
    - 旧版 TSV 文本（header + 数据行；FILE/SCHEME/ST 为元列，兼容旧运行目录）。
    """
    if isinstance(value, dict):
        if isinstance(value.get("data"), list):
            return _mlst_from_native(value)
        raw_alleles = value.get("alleles")
        alleles: dict[str, str] = {}
        if isinstance(raw_alleles, dict):
            for locus, allele in raw_alleles.items():
                key = str(locus).lower()
                if key not in _MLST_META_COLUMNS:
                    alleles[key] = str(allele)
        st = value.get("st")
        result: dict[str, Any] = {
            "st": "N/A" if st in (None, "") else str(st),
            "scheme": str(value.get("scheme") or ""),
            "alleles": alleles,
        }
        for key in ("score", "status"):
            if value.get(key) is not None:
                result[key] = value[key]
        return result
    if not isinstance(value, str) or not value.strip() or value.strip() == "N/A":
        return {"st": "N/A", "scheme": "", "alleles": {}}
    text = value.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            return {"st": "N/A", "scheme": "", "alleles": {}}
        return parse_mlst(payload) if isinstance(payload, dict) else {
            "st": "N/A",
            "scheme": "",
            "alleles": {},
        }
    return _mlst_from_tsv(text)


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
        rows.append(dict(zip(header, parts, strict=False)))  # 行超长时截断多余列
    return rows


def parse_gspec_report(json_text: str) -> list[dict[str, str]]:
    """Parse a ``gspec screen --format json`` report into abricate-shaped rows.

    v1.10.19：screen 规则以 JSON 为主输出（保留 schema/工具版本/参数等
    provenance）。为使报告、collect_summary 与 NLI 事实提取等既有消费方
    零改动，这里把 hits 映射回 abricate 列名（GENE / %IDENTITY / …），
    数值统一转字符串（下游本就按字符串渲染/转义）。
    旧运行目录的 TSV 由 ``load_screen_hits`` 回退处理。
    """
    if not json_text:
        return []
    try:
        report = json.loads(json_text)
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, str]] = []
    for f in report.get("files", []) if isinstance(report, dict) else []:
        if not isinstance(f, dict):
            continue
        for hit in f.get("hits", []) or []:
            if not isinstance(hit, dict):
                continue
            rows.append(
                {
                    "#FILE": str(hit.get("file", f.get("file", "")) or ""),
                    "SEQUENCE": str(hit.get("sequence", "")),
                    "START": str(hit.get("start", "")),
                    "END": str(hit.get("end", "")),
                    "STRAND": str(hit.get("strand", "")),
                    "GENE": str(hit.get("gene", "")),
                    "COVERAGE": str(hit.get("coverage", "")),
                    "COVERAGE_MAP": str(hit.get("coverage_map", "")),
                    "GAPS": str(hit.get("gaps", "")),
                    "%COVERAGE": str(hit.get("coverage_pct", "")),
                    "%IDENTITY": str(hit.get("identity_pct", "")),
                    "DATABASE": str(hit.get("database", "")),
                    "ACCESSION": str(hit.get("accession", "")),
                    "PRODUCT": str(hit.get("product", "")),
                    "RESISTANCE": str(hit.get("resistance", "")),
                }
            )
    return rows


def load_screen_hits(sample_dir: str | Path, kind: str) -> list[dict[str, str]]:
    """读取一个样本的 gspec screen 结果（JSON 优先，回退旧 TSV 布局）。

    ``kind`` 为 ``card`` / ``vfdb`` / ``plasmidfinder``；JSON 布局
    ``gspec/<kind>.json``（v1.10.19+），TSV 布局 ``amr/abricate_<kind>.tsv``
    （或 plasmid 的 ``plasmid/abricate_plasmidfinder.tsv``）供旧运行目录
    兼容。两者都缺 → 空列表。
    """
    root = Path(sample_dir)
    json_path = root / "gspec" / f"{kind}.json"
    if json_path.is_file():
        rows = parse_gspec_report(json_path.read_text(encoding="utf-8"))
        if rows or json_path.stat().st_size > 0:
            return rows
    tsv_candidates = (
        [root / "plasmid" / "abricate_plasmidfinder.tsv"]
        if kind == "plasmidfinder"
        else [root / "amr" / f"abricate_{kind}.tsv"]
    )
    for tsv_path in tsv_candidates:
        if tsv_path.is_file():
            return parse_abricate_tsv(tsv_path.read_text(encoding="utf-8"))
    return []


def read_json_file(path: str | Path) -> Any | None:
    """Read and parse a JSON file; None if missing, empty, or invalid.

    返回类型标注为 ``Any``（诚实）：JSON 顶层可以是对象、数组或标量，调用方
    自行按预期形态校验——不要假定一定是 dict。
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        return json.loads(p.read_text())
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


def _cgmlst_call_from_json(call: dict[str, Any]) -> tuple[int | None, str]:
    """gmlst JSON 的单个位点调用 → (等位基因号, 类别)。

    优先用 ``call_type``（exact/novel/partial/missing），无法判定时回退到
    等位基因标记语法（``23*``/``~23``/``15?``/``1,2``/``-``）。
    """
    allele_id = call.get("allele_id")
    call_type = str(call.get("call_type") or "").lower()
    allele_ids = call.get("allele_ids")
    if isinstance(allele_ids, list) and len(set(str(a) for a in allele_ids)) > 1:
        return None, "ambiguous"
    if call_type == "exact" and allele_id not in (None, ""):
        try:
            return int(str(allele_id).rstrip("*")), "called"
        except ValueError:
            pass
    if call_type in {"novel", "new"}:
        return None, "novel"
    if call_type in {"partial", "missing"}:
        return None, "missing"
    marker = str(allele_id) if allele_id not in (None, "") else "-"
    return _classify_cgmlst_allele(marker)


def _cgmlst_profiles_from_json(payload: dict[str, Any]) -> list[Any]:
    """gmlst ``typing cgmlst --format json`` → CgmlstProfile 列表。"""
    from .analysis.cgmlst_types import CgmlstProfile

    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    profiles: list[CgmlstProfile] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        calls = row.get("allele_calls")
        calls = calls if isinstance(calls, dict) else {}
        alleles: dict[str, int | None] = {}
        missing_loci: list[str] = []
        novel_loci: list[str] = []
        ambiguous_loci: list[str] = []
        n_called = 0
        for locus, call in calls.items():
            if not isinstance(call, dict):
                continue
            allele, category = _cgmlst_call_from_json(call)
            alleles[str(locus)] = allele
            if category == "called":
                n_called += 1
            elif category == "novel":
                novel_loci.append(str(locus))
            elif category == "ambiguous":
                ambiguous_loci.append(str(locus))
            else:
                missing_loci.append(str(locus))
        st = row.get("st")
        profiles.append(
            CgmlstProfile(
                sample_id=str(row.get("sample_id") or ""),
                scheme=str(row.get("scheme") or ""),
                st_raw="N/A" if st in (None, "") else str(st),
                alleles=alleles,
                n_called=n_called,
                n_total=len(alleles),
                missing_loci=missing_loci,
                novel_loci=novel_loci,
                ambiguous_loci=ambiguous_loci,
            )
        )
    return profiles


def parse_cgmlst_profiles(value: Any) -> list[Any]:
    """Parse cgMLST typing results (JSON primary, legacy TSV fallback).

    Accepts:

    - gmlst native JSON (dict or JSON text, ``{"schema_version","data":[...]}``);
    - legacy ``gmlst typing cgmlst --format tsv`` text::

        File\\tScheme\\tST\\t<locus_1>\\t...\\t<locus_N>
        <sample>\\t<scheme>\\t<ST>\\t<allele_1>\\t...\\t<allele_N>

    All 6 gmlst allele markers are handled (see
    ``_classify_cgmlst_allele`` for the marker table).

    Empty / ``"N/A"`` / header-only input returns ``[]`` (matches the
    ``parse_mlst`` convention of returning defaults rather than raising).

    The fallback 3-column row ``File\\tScheme\\tST\\n<sample>\\t<scheme>\\tN/A``
    (emitted when the gmlst binary is unavailable) parses gracefully to a
    profile with ``n_total=0`` and all locus lists empty.
    """
    # Lazy import: analysis.deterministic_verifier imports parse_mlst from this
    # module at load time, so a top-level import here would create a cycle.
    from .analysis.cgmlst_types import CgmlstProfile

    if isinstance(value, dict):
        return _cgmlst_profiles_from_json(value)
    if not isinstance(value, str) or not value.strip() or value.strip() == "N/A":
        return []

    text = value.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            return []
        return _cgmlst_profiles_from_json(payload) if isinstance(payload, dict) else []

    lines = text.strip().split("\n")
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


def parse_cgmlst_profile(value: Any) -> Any:
    """Parse a single-sample cgMLST result (JSON dict/text or legacy TSV).

    Expects exactly one data row. If two or more rows are present, raises
    ``ValueError`` directing the caller to ``parse_cgmlst_profiles`` rather
    than silently returning only the first profile.

    Empty / ``"N/A"`` / header-only input returns an empty ``CgmlstProfile``
    (``sample_id=""``, ``st_raw="N/A"``, ``n_called=0``, ``n_total=0``, all
    locus lists empty) — matches the ``parse_mlst`` convention.
    """
    # Lazy import — see parse_cgmlst_profiles for the cycle rationale.
    from .analysis.cgmlst_types import CgmlstProfile

    profiles = parse_cgmlst_profiles(value)
    if len(profiles) >= 2:
        raise ValueError(
            f"parse_cgmlst_profile received {len(profiles)} data rows; "
            "use parse_cgmlst_profiles for multi-sample input"
        )
    if not profiles:
        return CgmlstProfile(sample_id="", scheme="", st_raw="N/A")
    return profiles[0]
