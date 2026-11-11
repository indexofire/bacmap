"""gvixb 的只读结果适配器。

只消费 bacmap 已生成的结果，不在 Web 层执行生信分析。历史运行始终读取
``results/runs/<task_id>`` 的物理目录；样本页的“最新结果”入口是单独、明确的
latest scope，不会被历史运行接口复用。
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field

from bacmap.core.utils import parse_abricate_tsv, parse_gspec_report
from bacmap.interfaces.views import run_detail
from bacmap.store.results_layout import run_results_dir
from bacmap.tasks.spec import TaskId, TaskState, TaskType
from bacmap.tools._common import _validate_sample_id

_GROUP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_JSON_BYTES = 24 * 1024 * 1024
_MAX_FASTA_BYTES = 64 * 1024 * 1024
_MAX_TABLE_BYTES = 96 * 1024 * 1024
_MAX_ASSEMBLY_BP = 50_000_000
_MAX_CONTIGS = 10_000
_MAX_ANNOTATED_FEATURES = 20_000
_TRACK_WINDOW = 10_000
_READ_CHUNK = 1 << 20
_GFF_KINDS = {"CDS", "tRNA", "rRNA", "tmRNA", "ncRNA", "sorf", "pseudogene"}


class GvixbModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class GvixbLink(GvixbModel):
    id: str
    kind: Literal["genome", "tree", "mst", "circle"]
    label: str
    context: str
    url: str
    data_url: str


class GvixbManifest(GvixbModel):
    schema_id: Literal["gvixb.manifest/v1"] = Field(default="gvixb.manifest/v1", alias="schema")
    run_id: str
    views: list[GvixbLink]


class Track(GvixbModel):
    window: int
    step: int
    pos: list[int]
    gc: list[float]
    skew: list[float]


class Contig(GvixbModel):
    id: str
    name: str
    length: int
    gc: float
    topology: Literal["linear"] = "linear"
    track: Track


class AssemblyFeature(GvixbModel):
    id: str
    contig: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    strand: str
    gene: str
    product: str
    database: str
    kind: Literal["amr", "vir"]
    identity: float | None = None
    coverage: float | None = None


class AssemblyPayload(GvixbModel):
    schema_id: Literal["gvixb.assembly/v1"] = Field(default="gvixb.assembly/v1", alias="schema")
    demo: Literal[False] = False
    sample: str
    organism: str
    run_id: str | None
    scope: Literal["run", "latest"]
    source: str
    annotation_status: str
    total_bp: int
    contigs: list[Contig]
    features: list[AssemblyFeature]


class TreePayload(GvixbModel):
    schema_id: Literal["gvixb.phylogeny/v1"] = Field(default="gvixb.phylogeny/v1", alias="schema")
    demo: Literal[False] = False
    source: str
    run_id: str
    cohort: Literal["snp", "cgmlst"]
    group: str
    organism: str
    newick: str
    distanceLabel: str
    metadata: dict[str, dict[str, Any]] = {}
    samples: list[str]
    n_snp_sites: int | None = None
    n_loci: int | None = None
    scheme: str = ""
    missing_rate: float | None = None


class MstNode(GvixbModel):
    id: str
    label: str


class MstEdge(GvixbModel):
    source: str
    target: str
    weight: float = Field(ge=0)


class MstPayload(GvixbModel):
    schema_id: Literal["gvixb.mst/v1"] = Field(default="gvixb.mst/v1", alias="schema")
    demo: Literal[False] = False
    source: str
    run_id: str
    group: str
    organism: str
    scheme: str = ""
    n_loci: int = 0
    samples: list[str]
    nodes: list[MstNode]
    edges: list[MstEdge]


class AnnotationReplicon(GvixbModel):
    id: str
    name: str
    length: int
    gc: float | None = None
    topology: Literal["circular", "linear"]
    type: Literal["chromosome", "plasmid", "contig"] = "contig"
    track: Track | None = None


class AnnotationFeature(GvixbModel):
    clinical_gene: str = ""
    clinical_database: str = ""
    id: str
    contig: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    strand: str
    kind: str
    category: str = "unknown"
    flag: Literal["amr", "vir"] | None = None
    gene: str = ""
    locus: str = ""
    protein_id: str = ""
    product: str = ""
    ec: list[str] = []
    go: list[str] = []
    kegg_ko: list[str] = []
    kegg_pathways: list[str] = []
    pfams: list[str] = []
    eggnog_ogs: list[str] = []
    preferred_name: str = ""


class AnnotatedGenomePayload(GvixbModel):
    schema_id: Literal["gvixb.annotated-genome/v1"] = Field(
        default="gvixb.annotated-genome/v1", alias="schema"
    )
    demo: Literal[False] = False
    sample: str
    organism: str
    run_id: str | None
    scope: Literal["run", "latest"]
    source: str
    eggnog_available: bool
    eggnog_matched: int
    eggnog_total: int
    linear_contigs: int
    replicons: list[AnnotationReplicon]
    features: list[AnnotationFeature]
    categories: list[str]


@dataclass(frozen=True)
class _Scope:
    root: Path
    run_id: str | None
    kind: Literal["run", "latest"]


def _run_scope(engine: Any, run_id: str) -> tuple[_Scope, dict[str, Any]]:
    run = run_detail(engine.home, run_id)
    if run is None:
        raise FileNotFoundError("运行记录不存在")
    try:
        task = engine.get_task(TaskId(run["task_id"]))
    except KeyError as exc:
        raise FileNotFoundError("运行对应的分析任务不存在") from exc
    if task.get("task_type") != TaskType.ANALYZE.value:
        raise PermissionError("仅分析任务支持 gvixb")
    if task.get("state") != TaskState.SUCCEEDED.value:
        raise RuntimeError("分析尚未成功完成")
    return _Scope(run_results_dir(engine.home, run["task_id"]), run_id, "run"), run


def _latest_scope(engine: Any, sample_id: str) -> _Scope:
    if not _validate_sample_id(sample_id):
        raise PermissionError("非法样本 ID")
    return _Scope(Path(engine.home) / "results" / sample_id, None, "latest")


def _artifact(scope: _Scope, relative: Path, *, required: bool = False) -> Path | None:
    """Resolve one fixed artifact and reject symlink escapes outside this scope."""
    try:
        root = scope.root.resolve(strict=True)
    except OSError:
        root = None
    if root is None or not root.is_dir():
        if required:
            raise FileNotFoundError("结果目录不存在")
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError("结果文件越过运行目录边界") from exc
    if not candidate.is_file():
        if required:
            raise FileNotFoundError("该运行没有所需结果文件")
        return None
    return candidate


def _resolve_sample_artifact(
    scope: _Scope, sample_id: str, relatives: tuple[Path, ...]
) -> Path | None:
    """按候选顺序解析样本产物；每个候选透明回退 ``.gz`` 冷产物变体。

    现行 pipeline 用菌株名命名产物（v1.10.22 assembly 改名；Bakta/eggNOG 本就带
    prefix），v1.10.20 起注释目录整体 gzip（``annotation/bakta``、
    ``annotation/eggnog``）。历史运行与展开后的目录仍按旧名读取。
    候选一律经过 ``_artifact`` 的运行目录边界检查（含符号链接逃逸拒绝）。
    """
    for relative in relatives:
        variants = (relative, Path(f"{relative}.gz"))
        for variant in variants:
            path = _artifact(scope, _sample_relative(scope, sample_id, variant))
            if path is not None:
                return path
    return None


def _read_text(path: Path, limit: int, what: str) -> str:
    """读文本，透明支持 ``.gz`` 冷产物；解压后超过 limit 抛 ValueError。"""
    total = 0
    chunks: list[str] = []
    try:
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:
            while chunk := handle.read(_READ_CHUNK):
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"{what}超过 gvixb 的安全上限")
                chunks.append(chunk)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{what}无法读取") from exc
    return "".join(chunks)


def _read_json(scope: _Scope, relative: Path, *, required: bool = True) -> dict[str, Any] | None:
    path = _artifact(scope, relative, required=required)
    if path is None:
        return None
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("结果 JSON 超过 gvixb 的 24 MiB 安全上限")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("结果 JSON 无法解析") from exc
    if not isinstance(value, dict):
        raise ValueError("结果 JSON 顶层必须是对象")
    return value


def _organism(summary: dict[str, Any] | None) -> str:
    species = ((summary or {}).get("steps", {}) or {}).get("species", {}) or {}
    if not isinstance(species, dict):
        return ""
    verdict = species.get("verdict")
    if isinstance(verdict, dict):
        verdict = verdict.get("species")
    value = verdict or species.get("species") or ""
    return str(value).replace("_", " ") if value else ""


def _track(sequence: str) -> Track:
    pos: list[int] = []
    gc: list[float] = []
    skew: list[float] = []
    for start in range(0, len(sequence), _TRACK_WINDOW):
        window = sequence[start : start + _TRACK_WINDOW].upper()
        a, c = window.count("A"), window.count("C")
        g, t = window.count("G"), window.count("T")
        called = a + c + g + t
        if not called:
            continue
        pos.append(start + len(window) // 2)
        gc.append(round(100 * (g + c) / called, 3))
        skew.append(round((g - c) / (g + c), 5) if g + c else 0.0)
    return Track(window=_TRACK_WINDOW, step=_TRACK_WINDOW, pos=pos, gc=gc, skew=skew)


def _read_fasta(path: Path) -> list[Contig]:
    if not path.name.endswith(".gz") and path.stat().st_size > _MAX_FASTA_BYTES:
        raise ValueError("组装 FASTA 超过 gvixb 的 64 MiB 安全上限")
    contigs: list[Contig] = []
    current_id = ""
    current_name = ""
    chunks: list[str] = []
    total_bp = 0

    def finish() -> None:
        nonlocal total_bp
        if not current_id:
            return
        sequence = "".join(chunks)
        if not sequence:
            raise ValueError("组装 FASTA 含空 contig")
        total_bp += len(sequence)
        if total_bp > _MAX_ASSEMBLY_BP:
            raise ValueError("组装总长度超过 gvixb 的 50 Mbp 安全上限")
        upper = sequence.upper()
        called = sum(upper.count(base) for base in "ACGT")
        contigs.append(
            Contig(
                id=current_id,
                name=current_name,
                length=len(sequence),
                gc=round(100 * (upper.count("G") + upper.count("C")) / called, 3)
                if called
                else 0.0,
                track=_track(sequence),
            )
        )

    try:
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rt", encoding="ascii") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    finish()
                    header = line[1:]
                    current_id = header.split()[0]
                    current_name = header or current_id
                    chunks = []
                    if any(contig.id == current_id for contig in contigs):
                        raise ValueError("组装 FASTA 含重复 contig ID")
                    if len(contigs) >= _MAX_CONTIGS:
                        raise ValueError("contig 数量超过 gvixb 的 10000 条安全上限")
                else:
                    if not current_id or not re.fullmatch(r"[A-Za-z*.-]+", line):
                        raise ValueError("组装 FASTA 格式无效")
                    chunks.append(line)
            finish()
    except (OSError, UnicodeError) as exc:
        raise ValueError("组装 FASTA 无法读取") from exc
    if not contigs:
        raise ValueError("组装 FASTA 不含序列")
    return contigs


def _optional_float(row: dict[str, str], key: str) -> float | None:
    try:
        return float(row[key]) if row.get(key) else None
    except ValueError:
        return None


def _sample_relative(scope: _Scope, sample_id: str, suffix: Path) -> Path:
    return Path(sample_id) / suffix if scope.kind == "run" else suffix


def _screen_rows(scope: _Scope, sample_id: str, kind: str) -> list[dict[str, str]]:
    """一个库的基因筛查行：gspec screen JSON（v1.10.19+）优先，旧 abricate TSV 回退。

    行结构统一映射为 abricate 列名（见 ``parse_gspec_report``），两个布局的
    消费逻辑完全一致；候选文件都经过 ``_artifact`` 的运行目录边界检查。
    """
    candidates = (
        Path("gspec") / f"{kind}.json",
        Path("amr") / f"abricate_{kind}.tsv",
    )
    for relative in candidates:
        path = _artifact(scope, _sample_relative(scope, sample_id, relative))
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"基因筛查结果文件无法读取：{relative}") from exc
        if path.suffix == ".json":
            rows = parse_gspec_report(text)
            if rows or path.stat().st_size > 0:
                return rows
            continue
        return parse_abricate_tsv(text)
    return []


def _screen_features(
    scope: _Scope, sample_id: str, contigs: list[Contig]
) -> list[AssemblyFeature]:
    known = {contig.id: contig for contig in contigs}
    features: list[AssemblyFeature] = []
    specs: tuple[tuple[str, Literal["amr", "vir"]], ...] = (
        ("card", "amr"),
        ("vfdb", "vir"),
    )
    for kind, feature_kind in specs:
        for row in _screen_rows(scope, sample_id, kind):
            contig_id = row.get("SEQUENCE", "")
            if contig_id not in known:
                raise ValueError("基因筛查结果引用了组装中不存在的 contig")
            start, end = int(row["START"]) - 1, int(row["END"])
            if start < 0 or end <= start or end > known[contig_id].length:
                raise ValueError("基因筛查结果坐标超出 contig 边界")
            features.append(
                AssemblyFeature(
                    id=f"{feature_kind}:{len(features)}",
                    contig=contig_id,
                    start=start,
                    end=end,
                    strand=row.get("STRAND") or "+",
                    gene=row.get("GENE") or f"{feature_kind}_{len(features)}",
                    product=row.get("PRODUCT") or "",
                    database=row.get("DATABASE") or kind,
                    kind=feature_kind,
                    identity=_optional_float(row, "%IDENTITY"),
                    coverage=_optional_float(row, "%COVERAGE"),
                )
            )
    return features


def assembly_payload(engine: Any, run_id: str, sample_id: str) -> AssemblyPayload:
    scope, run = _run_scope(engine, run_id)
    if not _validate_sample_id(sample_id) or sample_id not in run["strain_ids"]:
        raise PermissionError("样本不属于该运行")
    return _assembly_payload(scope, sample_id)


def latest_assembly_payload(engine: Any, sample_id: str) -> AssemblyPayload:
    return _assembly_payload(_latest_scope(engine, sample_id), sample_id)


def _assembly_artifact(scope: _Scope, sample_id: str) -> Path | None:
    """组装 FASTA：现行菌株名（``{sample}.fasta``）优先，旧 ``contigs.fasta`` 回退。"""
    return _resolve_sample_artifact(
        scope,
        sample_id,
        (Path("assembly") / f"{sample_id}.fasta", Path("assembly") / "contigs.fasta"),
    )


def _assembly_payload(scope: _Scope, sample_id: str) -> AssemblyPayload:
    fasta = _assembly_artifact(scope, sample_id)
    if fasta is None:
        raise FileNotFoundError("该运行没有组装结果文件")
    contigs = _read_fasta(fasta)
    features = _screen_features(scope, sample_id, contigs)
    summary_path = _sample_relative(scope, sample_id, Path("report") / f"{sample_id}_summary.json")
    summary = _read_json(scope, summary_path, required=False)
    annotation_path = _sample_relative(scope, sample_id, Path("annotation") / "annotation.json")
    annotation = _read_json(scope, annotation_path, required=False) or {}
    status = str(annotation.get("status") or "unavailable")
    source = (
        f"bacmap 运行 {scope.run_id} · 同一运行的组装与筛查结果"
        if scope.kind == "run"
        else "bacmap 样本最新结果别名 · 非历史运行视图"
    )
    return AssemblyPayload(
        sample=sample_id,
        organism=_organism(summary),
        run_id=scope.run_id,
        scope=scope.kind,
        source=source,
        annotation_status=status,
        total_bp=sum(contig.length for contig in contigs),
        contigs=contigs,
        features=features,
    )


def tree_payload(engine: Any, run_id: str, cohort: str, group: str) -> TreePayload:
    scope, _ = _run_scope(engine, run_id)
    if cohort not in ("snp", "cgmlst") or not _GROUP_RE.fullmatch(group):
        raise PermissionError("非法队列类型或分组")
    cohort_kind: Literal["snp", "cgmlst"] = "snp" if cohort == "snp" else "cgmlst"
    summary = _read_json(scope, Path(cohort_kind) / group / f"{cohort_kind}_summary.json")
    if summary is None:
        raise FileNotFoundError("队列汇总不存在")
    newick = summary.get("tree_newick")
    if not isinstance(newick, str) or not newick.strip():
        raise ValueError("队列结果不含 Newick 树")
    samples = [str(value) for value in summary.get("samples", []) if value is not None]
    return TreePayload(
        source=f"bacmap 运行 {run_id} · {cohort} 队列结果",
        run_id=run_id,
        cohort=cohort_kind,
        group=group,
        organism=str(summary.get("organism") or ""),
        newick=newick,
        distanceLabel="SNP 分支长度" if cohort == "snp" else "MST 转换树的分支长度",
        samples=samples,
        n_snp_sites=_optional_int(summary.get("n_snp_sites")),
        n_loci=_optional_int(summary.get("n_loci")),
        scheme=str(summary.get("scheme") or ""),
        missing_rate=_optional_float_value(summary.get("missing_rate")),
    )


def _table_lines(path: Path) -> list[str]:
    return _read_text(path, _MAX_TABLE_BYTES, "注释表格").splitlines()


def _attrs(field: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in field.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = unquote(value.strip())
    return out


def _split_values(value: Any) -> list[str]:
    return [
        item.strip() for item in str(value or "").split(",")
        if item.strip() and item.strip() != "-"
    ]


def _cog_letters(value: Any) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Z]", str(value or ""))))


def _replicon_table(scope: _Scope, sample_id: str) -> dict[str, dict[str, str]]:
    path = _resolve_sample_artifact(
        scope,
        sample_id,
        (
            Path("annotation") / "bakta" / f"{sample_id}.replicons.tsv",
            Path("annotation") / "bakta" / "replicons.tsv",
        ),
    )
    if path is None:
        return {}
    rows = _table_lines(path)
    if not rows:
        return {}
    header: dict[str, int] | None = None
    start = 0
    lowered = [cell.strip().lower() for cell in rows[0].split("\t")]
    if any("original" in cell or "new" in cell or "topology" in cell for cell in lowered):
        header = {cell: i for i, cell in enumerate(lowered)}
        start = 1

    def cell(row: list[str], name: str, default: int) -> str:
        index = header.get(name, default) if header else default
        return row[index].strip() if index < len(row) else ""

    out: dict[str, dict[str, str]] = {}
    for raw in rows[start:]:
        row = raw.split("\t")
        if not row or not row[0].strip():
            continue
        original = cell(row, "original locus id", 0).strip()
        new = cell(row, "new locus id", 1).strip()
        if new in {"", "-"}:
            new = original
        topology = cell(row, "topology", 3).strip().lower()
        topology = "circular" if topology in {"c", "circular"} else "linear"
        kind = cell(row, "type", 2).strip().lower()
        kind = {
            "c": "chromosome", "chromosome": "chromosome",
            "p": "plasmid", "plasmid": "plasmid",
        }.get(kind, "contig")
        name = cell(row, "name", 4).strip()
        clean_name = "" if name in {"-", ""} else name
        out[new] = {
            "original": original, "topology": topology,
            "type": kind, "name": clean_name,
        }
    return out


def _parse_eggNOG(scope: _Scope, sample_id: str) -> tuple[dict[str, dict[str, Any]], int, bool]:
    path = _resolve_sample_artifact(
        scope,
        sample_id,
        (
            Path("annotation") / "eggnog" / f"{sample_id}.emapper.annotations",
            Path("annotation") / "eggnog" / "emapper.annotations",
            Path("annotation") / "eggnog" / "emapper.annotations.tsv",
        ),
    )
    if path is not None:
        rows = _table_lines(path)
        header: list[str] | None = None
        records: list[dict[str, Any]] = []
        for raw in rows:
            if not raw or raw.startswith("##"):
                continue
            if raw.startswith("#"):
                names = [cell.lstrip("#").strip().lower() for cell in raw.split("\t")]
                if "query" in names:
                    header = names
                continue
            cells = raw.split("\t")
            if header:
                record = dict(zip(header, cells, strict=False))
            elif len(cells) >= 22:
                # eggNOG v2/v3 documented default when --no_file_comments was used.
                record = dict(zip(
                    ["query", "seed_ortholog", "evalue", "score", "eggnog_ogs", "tax_ceiling",
                     "farthest_donor_lineage", "cog_category", "preferred_name", "gos", "ec",
                     "kegg_ko", "kegg_pathway", "kegg_module", "kegg_reaction", "kegg_rclass",
                     "brite", "kegg_tc", "cazy", "bigg_reaction", "pfams", "annotation_confidence"],
                    cells, strict=False,
                ))
            else:
                raise ValueError("eggNOG 注释表缺少可识别表头")
            if record.get("query"):
                records.append(record)
        return {str(row["query"]): row for row in records}, len(records), True
    return {}, 0, False


def _gff_sequence_line(
    line: str, seq_ids: list[str], seq_lengths: dict[str, int]
) -> bool | None:
    """Consume directives/embedded FASTA; True=sequence body, False=handled directive."""
    if line.startswith("##FASTA"):
        return False
    if line.startswith(">"):
        seq_id = line[1:].split()[0]
        if seq_id not in seq_ids:
            seq_ids.append(seq_id)
        return True
    if line.startswith("##sequence-region"):
        cells = line[len("##sequence-region") :].split()
        if len(cells) >= 3:
            seq_id, length = cells[0], int(cells[2])
            seq_lengths[seq_id] = length
            if seq_id not in seq_ids:
                seq_ids.append(seq_id)
        return False
    return None


def _parse_gff_features(path: Path) -> tuple[list[str], dict[str, int], list[dict[str, Any]]]:
    seq_ids: list[str] = []
    seq_lengths: dict[str, int] = {}
    features: list[dict[str, Any]] = []
    seen_features: set[tuple[str, str]] = set()
    in_fasta = False
    text = _read_text(path, _MAX_TABLE_BYTES, "Bakta GFF3")
    try:
        for raw in text.splitlines():
            line = raw.rstrip("\n\r")
            if line.startswith("##FASTA"):
                in_fasta = True
                continue
            if in_fasta:
                if line.startswith(">"):
                    _gff_sequence_line(line, seq_ids, seq_lengths)
                continue
            if _gff_sequence_line(line, seq_ids, seq_lengths) is not None:
                continue
            if not line or line.startswith("#"):
                continue
            cells = line.split("\t")
            if len(cells) < 9:
                continue
            seq_id, _source, kind, start, end, _score, strand, _phase, attr_field = cells[:9]
            if kind not in _GFF_KINDS:
                continue
            attrs = _attrs(attr_field)
            feature_id = attrs.get("ID") or f"{seq_id}:{start}:{end}:{strand}"
            if (seq_id, feature_id) in seen_features:
                continue
            seen_features.add((seq_id, feature_id))
            if seq_id not in seq_ids:
                seq_ids.append(seq_id)
            features.append({
                "seqid": seq_id,
                "gff_id": feature_id,
                "kind": kind.lower(),
                "start": int(start) - 1,
                "end": int(end),
                "strand": strand if strand in "+-" else "+",
                "gene": attrs.get("gene") or attrs.get("Name") or "",
                "locus": attrs.get("locus_tag") or "",
                "product": attrs.get("product") or "",
                "protein_id": attrs.get("protein_id") or "",
                "cog": _cog_letters(attrs.get("cog_category") or attrs.get("COG")),
                "ec": _split_values(attrs.get("EC")),
            })
            if len(features) > _MAX_ANNOTATED_FEATURES:
                raise ValueError("注释特征超过 gvixb 的 20000 条安全上限")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("Bakta GFF3 无法适配") from exc
    return seq_ids, seq_lengths, features


def _gff_annotation(
    scope: _Scope, sample_id: str, contigs: list[Contig]
) -> tuple[dict[str, int], list[AnnotationReplicon], list[dict[str, Any]]]:
    path = _resolve_sample_artifact(
        scope,
        sample_id,
        (
            Path("annotation") / "bakta" / f"{sample_id}.gff3",
            Path("annotation") / "bakta" / "annotation.gff3",
        ),
    )
    if path is None:
        raise FileNotFoundError("该运行没有 Bakta GFF3 注释")
    seq_ids, seq_lengths, features = _parse_gff_features(path)
    assembly_by_id = {contig.id: contig for contig in contigs}
    replicon_table = _replicon_table(scope, sample_id)

    replicons: list[AnnotationReplicon] = []
    assembly_to_replicon: dict[str, int] = {}
    for seq_id in seq_ids:
        table = replicon_table.get(seq_id, {})
        source_id = seq_id if seq_id in assembly_by_id else table.get("original", "")
        source = assembly_by_id.get(source_id)
        length = seq_lengths.get(seq_id) or (source.length if source else 0)
        if length <= 0:
            continue
        raw_type = table.get("type", "contig")
        replicon_type: Literal["chromosome", "plasmid", "contig"] = (
            "chromosome" if raw_type == "chromosome"
            else "plasmid" if raw_type == "plasmid"
            else "contig"
        )
        topology: Literal["circular", "linear"] = (
            "circular" if table.get("topology") == "circular" else "linear"
        )
        replicon = AnnotationReplicon(
            id=seq_id,
            name=table.get("name") or source_id or seq_id,
            length=length,
            gc=source.gc if source else None,
            topology=topology,
            type=replicon_type,
            track=source.track if source else None,
        )
        if source_id:
            assembly_to_replicon[source_id] = len(replicons)
        replicons.append(replicon)

    known_replicons = {replicon.id for replicon in replicons}
    for feature in features:
        if feature["seqid"] not in known_replicons:
            raise ValueError("Bakta GFF3 特征引用未知复制子")
    return assembly_to_replicon, replicons, features


def _annotate_features(
    scope: _Scope,
    sample_id: str,
    contigs: list[Contig],
    assembly_to_replicon: dict[str, int],
    replicons: list[AnnotationReplicon],
    raw_features: list[dict[str, Any]],
) -> tuple[list[AnnotationFeature], int, int, bool]:
    eggnog, eggnog_total, eggnog_available = _parse_eggNOG(scope, sample_id)
    eggnog_matched = 0
    for feature in raw_features:
        record = None
        for key in (feature["locus"], feature["protein_id"], feature.get("gff_id", "")):
            if key and str(key) in eggnog:
                record = eggnog[str(key)]
                break
        if record:
            eggnog_matched += 1
            feature["eggnog"] = True
            feature["preferred_name"] = str(record.get("preferred_name") or "")
            feature["cog"] = _cog_letters(record.get("cog_category")) or feature["cog"]
            feature["ec"] = _split_values(record.get("ec")) or feature["ec"]
            feature["go"] = _split_values(record.get("gos"))
            feature["kegg_ko"] = _split_values(record.get("kegg_ko"))
            feature["kegg_pathways"] = _split_values(record.get("kegg_pathway"))
            feature["pfams"] = _split_values(record.get("pfams"))
            feature["eggnog_ogs"] = _split_values(record.get("eggnog_ogs"))

    screens = _screen_features(scope, sample_id, contigs)
    replicon_features: dict[int, list[int]] = {}
    for index, feature in enumerate(raw_features):
        replicon_index = next(
            (i for i, replicon in enumerate(replicons) if replicon.id == feature["seqid"]), None
        )
        if replicon_index is not None:
            replicon_features.setdefault(replicon_index, []).append(index)

    for screen in screens:
        replicon_index = assembly_to_replicon.get(screen.contig)
        targets = replicon_features.get(replicon_index, []) if replicon_index is not None else []
        best_index, best_overlap = None, 0
        for index in targets:
            candidate = raw_features[index]
            overlap = min(candidate["end"], screen.end) - max(candidate["start"], screen.start)
            if overlap > best_overlap:
                best_index, best_overlap = index, overlap
        if best_index is not None and best_overlap > 0:
            raw_features[best_index]["flag"] = screen.kind
            raw_features[best_index]["clinical_gene"] = screen.gene
            raw_features[best_index]["clinical_database"] = screen.database

    output: list[AnnotationFeature] = []
    for index, feature in enumerate(raw_features):
        kind = str(feature["kind"])
        cog = feature.get("cog") or []
        category = cog[0] if cog else {
            "cds": "cds", "trna": "trna", "rrna": "rrna", "tmrna": "tmrna",
            "ncrna": "ncrna", "sorf": "sorf", "pseudogene": "pseudogene",
        }.get(kind, "unknown")
        output.append(AnnotationFeature(
            id=f"feature:{index}",
            contig=feature["seqid"],
            start=int(feature["start"]),
            end=int(feature["end"]),
            strand=str(feature["strand"]),
            kind=kind,
            category=category,
            flag=feature.get("flag"),
            gene=feature.get("gene") or feature.get("preferred_name") or "",
            locus=feature.get("locus") or "",
            product=feature.get("product") or "",
            protein_id=feature.get("protein_id") or "",
            ec=feature.get("ec", []),
            go=feature.get("go", []),
            kegg_ko=feature.get("kegg_ko", []),
            kegg_pathways=feature.get("kegg_pathways", []),
            pfams=feature.get("pfams", []),
            eggnog_ogs=feature.get("eggnog_ogs", []),
            preferred_name=feature.get("preferred_name") or "",
            clinical_gene=feature.get("clinical_gene") or "",
            clinical_database=feature.get("clinical_database") or "",
        ))
    return output, eggnog_total, eggnog_matched, eggnog_available


def _annotated_payload(scope: _Scope, sample_id: str) -> AnnotatedGenomePayload:
    fasta = _assembly_artifact(scope, sample_id)
    if fasta is None:
        raise FileNotFoundError("该运行没有组装结果文件")
    contigs = _read_fasta(fasta)
    assembly_to_replicon, replicons, raw_features = _gff_annotation(scope, sample_id, contigs)
    features, eggnog_total, eggnog_matched, eggnog_available = _annotate_features(
        scope, sample_id, contigs, assembly_to_replicon, replicons, raw_features
    )
    summary_path = _sample_relative(scope, sample_id, Path("report") / f"{sample_id}_summary.json")
    summary = _read_json(scope, summary_path, required=False)
    tools = ["Bakta GFF3"] + (["eggNOG-mapper"] if eggnog_available else [])
    prefix = (
        f"bacmap 运行 {scope.run_id}" if scope.kind == "run"
        else "bacmap 样本最新结果别名"
    )
    return AnnotatedGenomePayload(
        sample=sample_id,
        organism=_organism(summary),
        run_id=scope.run_id,
        scope=scope.kind,
        source=f"{prefix} · {' + '.join(tools)} 坐标与功能注释",
        eggnog_available=eggnog_available,
        eggnog_matched=eggnog_matched,
        eggnog_total=eggnog_total,
        linear_contigs=sum(1 for replicon in replicons if replicon.topology == "linear"),
        replicons=replicons,
        features=features,
        categories=list(dict.fromkeys(feature.category for feature in features)),
    )


def annotated_genome_payload(engine: Any, run_id: str, sample_id: str) -> AnnotatedGenomePayload:
    scope, run = _run_scope(engine, run_id)
    if not _validate_sample_id(sample_id) or sample_id not in run["strain_ids"]:
        raise PermissionError("样本不属于该运行")
    return _annotated_payload(scope, sample_id)


def latest_annotated_genome_payload(engine: Any, sample_id: str) -> AnnotatedGenomePayload:
    return _annotated_payload(_latest_scope(engine, sample_id), sample_id)


def _has_bakta_annotation(scope: _Scope, sample_id: str) -> bool:
    return _resolve_sample_artifact(
        scope,
        sample_id,
        (
            Path("annotation") / "bakta" / f"{sample_id}.gff3",
            Path("annotation") / "bakta" / "annotation.gff3",
        ),
    ) is not None


def latest_annotation_link(engine: Any, sample_id: str) -> GvixbLink | None:
    try:
        scope = _latest_scope(engine, sample_id)
    except PermissionError:
        return None
    if not _has_bakta_annotation(scope, sample_id):
        return None
    return GvixbLink(
        id=f"circle:{sample_id}",
        kind="circle",
        label=f"3D 注释圈图 · {sample_id}",
        context="最新结果 · Bakta",
        url=f"/gvixb/samples/{sample_id}/annotation",
        data_url=f"/api/v1/gvixb/samples/{sample_id}/annotated-genome",
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _optional_float_value(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def mst_payload(engine: Any, run_id: str, group: str) -> MstPayload:
    scope, _ = _run_scope(engine, run_id)
    if not _GROUP_RE.fullmatch(group):
        raise PermissionError("非法 cgMLST 分组")
    raw = _read_json(scope, Path("cgmlst") / group / "mst_payload.json")
    if raw is None:
        raise FileNotFoundError("MST 结果不存在")
    graph: dict[str, Any] = raw
    if not ("nodes" in graph and "edges" in graph) and isinstance(raw.get("data"), dict):
        graph = raw["data"]
    nodes_raw, edges_raw = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError("gmlst MST 载荷缺少 nodes/edges")
    nodes = [
        MstNode(id=str(node["id"]), label=str(node.get("label") or node["id"]))
        for node in nodes_raw
        if isinstance(node, dict) and "id" in node
    ]
    if len(nodes) != len(nodes_raw) or len({node.id for node in nodes}) != len(nodes):
        raise ValueError("gmlst MST 节点 ID 缺失或重复")
    known = {node.id for node in nodes}
    edges: list[MstEdge] = []
    for edge in edges_raw:
        if not isinstance(edge, dict):
            raise ValueError("gmlst MST 边格式无效")
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source not in known or target not in known:
            raise ValueError("gmlst MST 边引用未知节点")
        edges.append(MstEdge(source=source, target=target, weight=float(edge["weight"])))
    summary_path = Path("cgmlst") / group / "cgmlst_summary.json"
    summary = _read_json(scope, summary_path, required=False) or {}
    return MstPayload(
        source=f"bacmap 运行 {run_id} · gmlst visual mst 原始拓扑",
        run_id=run_id,
        group=group,
        organism=str(summary.get("organism") or ""),
        scheme=str(summary.get("scheme") or ""),
        n_loci=_optional_int(summary.get("n_loci")) or 0,
        samples=[str(value) for value in summary.get("samples", [])],
        nodes=nodes,
        edges=edges,
    )


def run_visualizations(engine: Any, run_id: str) -> list[GvixbLink]:
    """Capabilities are derived from actual artifacts; no speculative buttons."""
    try:
        scope, run = _run_scope(engine, run_id)
    except (FileNotFoundError, PermissionError, RuntimeError):
        return []
    views: list[GvixbLink] = []
    for sample in run["strain_ids"]:
        if not _validate_sample_id(sample):
            continue
        if _assembly_artifact(scope, sample) is None:
            continue
        views.append(
            GvixbLink(
                id=f"genome:{sample}",
                kind="genome",
                label=f"3D 基因组 · {sample}",
                context=sample,
                url=f"/gvixb/runs/{run_id}/genome/{sample}",
                data_url=f"/api/v1/gvixb/runs/{run_id}/genome/{sample}",
            )
        )
        if _has_bakta_annotation(scope, sample):
            views.append(
                GvixbLink(
                    id=f"circle:{sample}",
                    kind="circle",
                    label=f"3D 注释圈图 · {sample}",
                    context=sample,
                    url=f"/gvixb/runs/{run_id}/annotation/{sample}",
                    data_url=f"/api/v1/gvixb/runs/{run_id}/annotated-genome/{sample}",
                )
            )
    for cohort in ("snp", "cgmlst"):
        base = scope.root / cohort
        if not base.is_dir():
            continue
        for directory in sorted(base.iterdir()):
            group = directory.name
            if not directory.is_dir() or not _GROUP_RE.fullmatch(group):
                continue
            if _artifact(scope, Path(cohort) / group / f"{cohort}_summary.json") is not None:
                views.append(
                    GvixbLink(
                        id=f"tree:{cohort}:{group}",
                        kind="tree",
                        label=f"3D {'SNP' if cohort == 'snp' else 'cgMLST'} 树 · {group}",
                        context=f"{cohort} / {group}",
                        url=f"/gvixb/runs/{run_id}/tree/{cohort}/{group}",
                        data_url=f"/api/v1/gvixb/runs/{run_id}/tree/{cohort}/{group}",
                    )
                )
            if cohort == "cgmlst" and _artifact(
                scope, Path(cohort) / group / "mst_payload.json"
            ) is not None:
                views.append(
                    GvixbLink(
                        id=f"mst:{group}",
                        kind="mst",
                        label=f"3D 最小生成树 · {group}",
                        context=f"cgMLST / {group}",
                        url=f"/gvixb/runs/{run_id}/mst/{group}",
                        data_url=f"/api/v1/gvixb/runs/{run_id}/mst/{group}",
                    )
                )
    return views


def run_manifest(engine: Any, run_id: str) -> GvixbManifest:
    _run_scope(engine, run_id)
    return GvixbManifest(run_id=run_id, views=run_visualizations(engine, run_id))


def latest_genome_link(engine: Any, sample_id: str) -> GvixbLink | None:
    try:
        scope = _latest_scope(engine, sample_id)
    except PermissionError:
        return None
    if _assembly_artifact(scope, sample_id) is None:
        return None
    return GvixbLink(
        id=f"genome:{sample_id}",
        kind="genome",
        label="使用 gvixb 查看 3D 基因组",
        context="最新结果",
        url=f"/gvixb/samples/{sample_id}/genome",
        data_url=f"/api/v1/gvixb/samples/{sample_id}/genome",
    )


def gom_visualizations(engine: Any, obj: dict[str, Any]) -> list[GvixbLink]:
    payload = obj.get("payload", {})
    run_id = payload.get("run_id") if isinstance(payload, dict) else None
    if not isinstance(run_id, str):
        return []
    views = run_visualizations(engine, run_id)
    analysis_type = payload.get("analysis_type")
    if analysis_type == "sample_analysis":
        wanted = {f"genome:{payload.get('sample_id')}", f"circle:{payload.get('sample_id')}"}
    elif analysis_type == "snp_cohort":
        wanted = {f"tree:snp:{payload.get('group')}"}
    elif analysis_type == "cgmlst_cohort":
        group = payload.get("group")
        return [view for view in views if view.id in {f"tree:cgmlst:{group}", f"mst:{group}"}]
    else:
        return []
    return [view for view in views if view.id in wanted]
