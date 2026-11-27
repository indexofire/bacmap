"""``bacmap record import``：湿实验元数据/化验结果的 XLSX/CSV/TSV 批量导入。

导入仍然只提交一个 ``record`` 任务（kind=batch），由任务层写入
``specimen_metadata`` / ``strain_metadata`` / ``library_metadata`` /
``lab_results``；CLI 只做解析、列名映射和身份校验。

支持的输入：

- XLSX/XLSM：按 sheet 名/表头识别 specimen、isolate、library、lab；也可用
  ``--specimen-sheet``/``--isolate-sheet``/``--library-sheet``/``--lab-sheet``
  显式指定。
- CSV/TSV：按表头自动判断目标。
- specimen 用样本编号；isolate 用菌株编号；library 用测序数据编号；
  也接受交叉 ID（library/specimen）解析到目标，一个样本多个菌株时拒绝。
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.store.strain_metadata import METADATA_FIELDS
from bacmap.tasks.records import (
    BatchRecord,
    LabResultRecord,
    LibraryMetadataRecord,
    MetadataRecord,
    SpecimenMetadataRecord,
)


def _norm(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("\ufeff", "")
        .replace(" ", "_")
        .replace("-", "_")
    )


_STRAIN_HEADERS = {
    "strain_id",
    "isolate_id",
    "isolate",
    "strain",
    "菌株编号",
    "菌株id",
    "菌株_id",
    "菌株",
    "菌株号",
}
_SAMPLE_HEADERS = {
    "sample",
    "sample_id",
    "library",
    "library_id",
    "dataset",
    "dataset_id",
    "测序数据",
    "测序数据编号",
    "文库",
    "文库编号",
}
_SPECIMEN_HEADERS = {"specimen", "specimen_id", "样本", "样本编号", "送检编号"}

_ISOLATE_SHEET_HINTS = {
    "metadata",
    "meta",
    "wetlab",
    "wet_lab",
    "湿实验",
    "元数据",
    "菌株信息",
    "菌株",
    "isolate",
    "isolates",
}
_SPECIMEN_SHEET_HINTS = {
    "specimen",
    "specimens",
    "样本信息",
    "样本",
    "送检信息",
    "患者信息",
    "sample_info",
}
_LIBRARY_SHEET_HINTS = {
    "library",
    "libraries",
    "测序数据",
    "测序信息",
    "文库",
    "sequencing",
}
_LAB_SHEET_HINTS = {
    "lab",
    "labs",
    "lab_result",
    "lab_results",
    "化验",
    "化验结果",
    "检验",
    "药敏",
    "mic",
    "检测结果",
}

_METADATA_ALIASES = {
    "sample": "sample_id",
    "sample_id": "sample_id",
    "样本编号": "sample_id",
    "样品编号": "sample_id",
    "送检单位": "submitting_lab",
    "送检日期": "submit_date",
    "接收人": "receiver",
    "患者编号": "patient_id",
    "病人编号": "patient_id",
    "患者姓名": "patient_name",
    "病人姓名": "patient_name",
    "年龄": "patient_age",
    "患者年龄": "patient_age",
    "性别": "patient_gender",
    "患者性别": "patient_gender",
    "电话": "patient_phone",
    "联系电话": "patient_phone",
    "分离日期": "isolation_date",
    "省份": "province",
    "省": "province",
    "城市": "city",
    "市": "city",
    "区县": "district",
    "区/县": "district",
    "机构": "facility",
    "来源": "sample_source",
    "样本来源": "sample_source",
    "样本类型": "sample_type",
    "食品类别": "food_category",
    "食品名称": "food_name",
    "采集日期": "collection_date",
    "采样日期": "collection_date",
    "症状": "symptoms",
    "发病日期": "onset_date",
    "诊断": "diagnosis",
    "转归": "outcome",
    "医院": "hospital",
    "暴发编号": "outbreak_id",
    "聚集性编号": "outbreak_id",
    "聚集性备注": "cluster_note",
    "备注": "cluster_note",
    "cluster_note": "cluster_note",
}

_LAB_ALIASES = {
    "category": "category",
    "类别": "category",
    "分类": "category",
    "检验类别": "category",
    "试验类别": "category",
    "test_name": "test_name",
    "项目": "test_name",
    "检验项目": "test_name",
    "检测项目": "test_name",
    "药敏项目": "test_name",
    "药物": "test_name",
    "抗菌药物": "test_name",
    "result": "result",
    "结果": "result",
    "检验结果": "result",
    "检测结果": "result",
    "值": "result",
    "mic": "result",
    "unit": "unit",
    "单位": "unit",
    "method": "method",
    "方法": "method",
    "检测方法": "method",
    "interpretation": "interpretation",
    "判读": "interpretation",
    "结果判读": "interpretation",
    "解释": "interpretation",
    "standard": "standard",
    "标准": "standard",
    "判读标准": "standard",
    "tested_date": "tested_date",
    "日期": "tested_date",
    "检测日期": "tested_date",
    "检验日期": "tested_date",
    "tested_by": "tested_by",
    "检测人": "tested_by",
    "检验人": "tested_by",
    "lab": "lab",
    "实验室": "lab",
    "检测机构": "lab",
    "notes": "notes",
    "说明": "notes",
    "备注": "notes",
}


def is_blank(value: Any) -> bool:
    return not _text(value)


def canonical_metadata_field(header: str) -> str:
    key = _norm(header)
    if key in METADATA_FIELDS:
        return key
    return _METADATA_ALIASES.get(key, "")


def canonical_lab_field(header: str) -> str:
    key = _norm(header)
    if key in {
        "category",
        "test_name",
        "result",
        "unit",
        "method",
        "interpretation",
        "standard",
        "tested_date",
        "tested_by",
        "lab",
        "notes",
    }:
        return key
    return _LAB_ALIASES.get(key, "")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, str)):
        return str(value).strip()
    return str(value).strip()


def _age(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _csv_rows(path: Path, delimiter: str) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        rows = list(reader)
    return _rows_from_matrix(rows)


def _rows_from_matrix(rows: list[list[Any]]) -> list[tuple[int, dict[str, str]]]:
    header: list[str] | None = None
    out: list[tuple[int, dict[str, str]]] = []
    for number, raw in enumerate(rows, start=1):
        cells = [_text(cell) for cell in raw]
        if not any(cells):
            continue
        if header is None:
            while cells and not cells[-1]:
                cells.pop()
            header = cells
            seen: set[str] = set()
            for h in header:
                if not h:
                    raise ValueError(f"empty column header at row {number}")
                key = _norm(h)
                if key in seen:
                    raise ValueError(f"duplicate column header: {h!r}")
                seen.add(key)
            continue
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        out.append((number, dict(zip(header, cells, strict=False))))
    if header is None:
        raise ValueError("input has no header row")
    return out


def _workbook_rows(
    path: Path,
) -> dict[str, list[tuple[int, dict[str, str]]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover — pixi 环境默认安装
        raise ValueError(
            "reading .xlsx requires openpyxl; run `pixi install` or use CSV/TSV"
        ) from exc
    wb = load_workbook(path, read_only=True, data_only=True)
    out: dict[str, list[tuple[int, dict[str, str]]]] = {}
    try:
        for sheet in wb.worksheets:
            out[sheet.title] = _rows_from_matrix(
                [list(row) for row in sheet.iter_rows(values_only=True)]
            )
    finally:
        wb.close()
    return out


def _classify(headers: Iterable[str]) -> str:
    keys = {_norm(h) for h in headers}
    if keys & {"category", "test_name", "result", "类别", "项目", "结果", "检验项目"}:
        return "lab"
    return "metadata"


def _lookup_tables(
    home: Path,
) -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, list[str]],
    set[str],
    dict[str, str],
    set[str],
    dict[str, str],
]:
    """返回 (isolates, library→isolate, specimen→isolates, specimens,
    isolate→specimen, libraries)，全部只读。"""
    import sqlite3

    from bacmap.store.catalog import cached_libraries

    db = home / "data" / "bacmap.sqlite"
    isolates: dict[str, str] = {}
    specimens: dict[str, list[str]] = {}
    specimen_ids: set[str] = set()
    isolate_specimen: dict[str, str] = {}
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                for isolate_id, specimen in conn.execute(
                    "SELECT isolate_id, specimen_id FROM isolates"
                ):
                    value = str(isolate_id or "")
                    if not value:
                        continue
                    isolates[value] = value
                    if specimen:
                        isolate_specimen[value] = str(specimen)
                        specimens.setdefault(str(specimen), []).append(value)
                for (specimen_id,) in conn.execute("SELECT specimen_id FROM specimens"):
                    specimen_ids.add(str(specimen_id))
        except sqlite3.Error:
            # 旧库/尚未迁移：身份表不存在时按空表处理；导入会在提交前报未知菌株。
            pass
    library_rows = cached_libraries(home)
    libraries = {
        str(row.get("sample") or ""): str(row.get("isolate") or "")
        for row in library_rows
        if row.get("sample")
    }
    library_ids = {str(row.get("sample")) for row in library_rows if row.get("sample")}
    library_specimens = {
        str(row.get("sample") or ""): str(row.get("specimen") or "")
        for row in library_rows
        if row.get("sample")
    }
    return (
        isolates,
        libraries,
        specimens,
        specimen_ids,
        isolate_specimen,
        library_ids,
        library_specimens,
    )


def _resolve_strain(
    key: str,
    *,
    isolates: dict[str, str],
    libraries: dict[str, str],
    specimens: dict[str, list[str]],
) -> str:
    """菌株标识 → isolate_id；支持测序数据 ID 与唯一菌株的样本编号。"""
    value = key.strip()
    if value in isolates:
        return value
    mapped = libraries.get(value, "")
    if mapped and mapped in isolates:
        return mapped
    candidates = specimens.get(value, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(
            f"{value!r} is a specimen with {len(candidates)} isolates; "
            "use the isolate or library ID instead"
        )
    raise ValueError(f"unknown isolate/library/specimen: {value!r}")


def _resolve_specimen(
    key: str,
    *,
    isolates: dict[str, str],
    libraries: dict[str, str],
    specimen_ids: set[str],
    isolate_specimen: dict[str, str],
    library_specimens: dict[str, str],
) -> str:
    value = key.strip()
    if value in specimen_ids:
        return value
    mapped = libraries.get(value, "")
    if mapped and mapped in isolate_specimen:
        return isolate_specimen[mapped]
    linked_specimen = library_specimens.get(value, "")
    if linked_specimen:
        return linked_specimen
    if value in isolates and value in isolate_specimen:
        return isolate_specimen[value]
    raise ValueError(f"unknown specimen/specimen-linked id: {value!r}")


def _row_key(row: dict[str, str]) -> str:
    """返回行内的菌株/测序数据/样本标识（调用方再解析到 isolate）。"""
    for header, value in row.items():
        if is_blank(value):
            continue
        key = _norm(header)
        if key in _STRAIN_HEADERS or key in _SAMPLE_HEADERS or key in _SPECIMEN_HEADERS:
            return value
    return ""


def _metadata_row(
    row: dict[str, str],
    isolate_id: str,
) -> MetadataRecord:
    fields: dict[str, Any] = {}
    extra: dict[str, str | int | float | bool | None] = {}
    sample_id = ""
    for header, value in row.items():
        if is_blank(value):
            continue
        key = _norm(header)
        if key in _STRAIN_HEADERS or key in _SAMPLE_HEADERS or key in _SPECIMEN_HEADERS:
            if key in _SAMPLE_HEADERS or key in _SPECIMEN_HEADERS:
                sample_id = _text(value)
            continue
        canonical = canonical_metadata_field(header)
        if canonical == "sample_id":
            sample_id = _text(value)
        elif canonical:
            fields[canonical] = (
                _age(value) if canonical == "patient_age" else _text(value)
            )
        else:
            extra[str(header).strip()] = _text(value)
    if "patient_age" in fields and fields["patient_age"] is None:
        fields.pop("patient_age")
    return MetadataRecord(
        strain_id=isolate_id,
        sample_id=sample_id,
        fields=fields,
        extra=extra,
    )


def _specimen_row(row: dict[str, str], specimen_id: str) -> SpecimenMetadataRecord:
    data: dict[str, str | int | float | bool | None] = {}
    for header, value in row.items():
        if is_blank(value):
            continue
        key = _norm(header)
        if key in _SPECIMEN_HEADERS or key in _STRAIN_HEADERS or key in _SAMPLE_HEADERS:
            continue
        data[str(header).strip()] = _text(value)
    return SpecimenMetadataRecord(specimen_id=specimen_id, data=data)


def _library_row(row: dict[str, str], library_id: str, home: Path) -> LibraryMetadataRecord:
    from bacmap.store.catalog import library_links

    links = library_links(home, library_id)
    data: dict[str, str | int | float | bool | None] = {}
    for header, value in row.items():
        if is_blank(value):
            continue
        key = _norm(header)
        if key in _SPECIMEN_HEADERS or key in _STRAIN_HEADERS or key in _SAMPLE_HEADERS:
            continue
        data[str(header).strip()] = _text(value)
    return LibraryMetadataRecord(
        library_id=library_id,
        specimen_id=links["specimen_id"],
        isolate_id=links["isolate_id"],
        data=data,
    )


def _lab_row(
    row: dict[str, str],
    subject_type: str,
    subject_id: str,
) -> LabResultRecord:
    values: dict[str, Any] = {}
    extra: dict[str, str | int | float | bool | None] = {}
    for header, value in row.items():
        if is_blank(value):
            continue
        key = _norm(header)
        if key in _STRAIN_HEADERS or key in _SAMPLE_HEADERS or key in _SPECIMEN_HEADERS:
            continue
        canonical = canonical_lab_field(header)
        if canonical:
            values[canonical] = _text(value)
        else:
            extra[str(header).strip()] = _text(value)
    missing = [
        key for key in ("category", "test_name", "result") if not values.get(key)
    ]
    if missing:
        raise ValueError(f"missing required lab field(s): {', '.join(missing)}")
    return LabResultRecord(
        strain_id=subject_id,
        subject_type="specimen" if subject_type == "specimen" else "isolate",
        subject_id=subject_id,
        category=str(values["category"]),
        test_name=str(values["test_name"]),
        result=str(values["result"]),
        unit=str(values.get("unit", "")),
        method=str(values.get("method", "")),
        interpretation=str(values.get("interpretation", "")),
        standard=str(values.get("standard", "")),
        tested_date=str(values.get("tested_date", "")),
        tested_by=str(values.get("tested_by", "")),
        lab=str(values.get("lab", "")),
        notes=str(values.get("notes", "")),
        extra=extra,
    )


def _target(name: str, headers: Iterable[str]) -> str:
    keys = {_norm(h) for h in headers}
    sheet = _norm(name)
    if keys & {"category", "test_name", "result", "类别", "项目", "结果", "检验项目"}:
        return "lab"
    # 表头语义优先于 sheet 名：名为 metadata 但只有样本编号/患者列的表
    # 仍应落到 specimen，而不是被误写成菌株元数据。
    if keys & _STRAIN_HEADERS:
        return "isolate"
    if keys & _SPECIMEN_HEADERS:
        return "specimen"
    if keys & _SAMPLE_HEADERS:
        return "library"
    if sheet in _SPECIMEN_SHEET_HINTS:
        return "specimen"
    if sheet in _LIBRARY_SHEET_HINTS:
        return "library"
    if sheet in _ISOLATE_SHEET_HINTS:
        return "isolate"
    return "isolate"


def _select_tables(
    path: Path,
    *,
    metadata_sheet: str,
    specimen_sheet: str,
    isolate_sheet: str,
    library_sheet: str,
    lab_sheet: str,
) -> list[tuple[str, list[tuple[int, dict[str, str]]]]]:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv", ".txt"}:
        delimiter = "\t" if suffix in {".tsv", ".txt"} else ","
        return [("input", _csv_rows(path, delimiter))]
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError(f"unsupported input type: {path.suffix} (use .xlsx/.csv/.tsv)")
    sheets = _workbook_rows(path)
    chosen: list[tuple[str, list[tuple[int, dict[str, str]]]]] = []
    for label, sheet in (
        ("specimen", specimen_sheet),
        ("isolate", isolate_sheet or metadata_sheet),
        ("library", library_sheet),
        ("lab", lab_sheet),
    ):
        if not sheet:
            continue
        if sheet not in sheets:
            raise ValueError(f"{label} sheet not found: {sheet!r}")
        chosen.append((sheet, sheets[sheet]))
    if chosen:
        return chosen
    for name, rows in sheets.items():
        if _norm(name) in (
            _ISOLATE_SHEET_HINTS
            | _SPECIMEN_SHEET_HINTS
            | _LIBRARY_SHEET_HINTS
            | _LAB_SHEET_HINTS
        ):
            chosen.append((name, rows))
    if chosen:
        return chosen
    if len(sheets) == 1:
        name, rows = next(iter(sheets.items()))
        return [(name, rows)]
    raise ValueError(
        "cannot identify sheets; use --specimen-sheet/--isolate-sheet/"
        "--library-sheet/--lab-sheet "
        f"(sheets: {', '.join(sheets)})"
    )


def _build_rows(
    path: Path,
    *,
    metadata_sheet: str,
    specimen_sheet: str,
    isolate_sheet: str,
    library_sheet: str,
    lab_sheet: str,
    lab_subject: str,
    home: Path,
) -> tuple[
    list[MetadataRecord],
    list[SpecimenMetadataRecord],
    list[LibraryMetadataRecord],
    list[LabResultRecord],
    list[str],
]:
    (
        isolates,
        libraries,
        specimens,
        specimen_ids,
        isolate_specimen,
        library_ids,
        library_specimens,
    ) = _lookup_tables(home)
    metadata: list[MetadataRecord] = []
    specimen_metadata: list[SpecimenMetadataRecord] = []
    library_metadata: list[LibraryMetadataRecord] = []
    labs: list[LabResultRecord] = []
    errors: list[str] = []
    for sheet_name, rows in _select_tables(
        path,
        metadata_sheet=metadata_sheet,
        specimen_sheet=specimen_sheet,
        isolate_sheet=isolate_sheet,
        library_sheet=library_sheet,
        lab_sheet=lab_sheet,
    ):
        if not rows:
            continue
        target = _target(sheet_name, rows[0][1].keys())
        for line_no, row in rows:
            key = _row_key(row)
            if not key:
                if any(not is_blank(value) for value in row.values()):
                    errors.append(f"{sheet_name}:{line_no}: missing id column")
                continue
            try:
                if target == "lab":
                    subject_type = lab_subject
                    if subject_type == "auto":
                        subject_type = (
                            "specimen"
                            if key.strip() in specimen_ids
                            and key.strip() not in isolates
                            and key.strip() not in library_ids
                            else "isolate"
                        )
                    if subject_type == "specimen":
                        subject_id = _resolve_specimen(
                            key,
                            isolates=isolates,
                            libraries=libraries,
                            specimen_ids=specimen_ids,
                            isolate_specimen=isolate_specimen,
                            library_specimens=library_specimens,
                        )
                    else:
                        subject_id = _resolve_strain(
                            key,
                            isolates=isolates,
                            libraries=libraries,
                            specimens=specimens,
                        )
                    labs.append(_lab_row(row, subject_type, subject_id))
                elif target == "specimen":
                    specimen_id = _resolve_specimen(
                        key,
                        isolates=isolates,
                        libraries=libraries,
                        specimen_ids=specimen_ids,
                        isolate_specimen=isolate_specimen,
                        library_specimens=library_specimens,
                    )
                    specimen_metadata.append(_specimen_row(row, specimen_id))
                elif target == "library":
                    if key.strip() not in library_ids:
                        raise ValueError(f"unknown library: {key!r}")
                    library_metadata.append(_library_row(row, key.strip(), home))
                else:
                    isolate_id = _resolve_strain(
                        key, isolates=isolates, libraries=libraries, specimens=specimens
                    )
                    metadata.append(_metadata_row(row, isolate_id))
            except ValueError as exc:
                errors.append(f"{sheet_name}:{line_no}: {exc}")
    return metadata, specimen_metadata, library_metadata, labs, errors


def _summary(
    metadata: list[MetadataRecord],
    specimen_metadata: list[SpecimenMetadataRecord],
    library_metadata: list[LibraryMetadataRecord],
    labs: list[LabResultRecord],
) -> dict[str, Any]:
    return {
        "isolate_rows": len(metadata),
        "specimen_rows": len(specimen_metadata),
        "library_rows": len(library_metadata),
        "lab_rows": len(labs),
        "isolates": sorted(
            {row.strain_id for row in metadata} | {row.strain_id for row in labs}
        ),
        "specimens": sorted({row.specimen_id for row in specimen_metadata}),
        "libraries": sorted({row.library_id for row in library_metadata}),
        "isolate_fields": sorted(
            {key for row in metadata for key in (*row.fields.keys(), *row.extra.keys())}
        ),
        "specimen_fields": sorted(
            {key for row in specimen_metadata for key in row.data}
        ),
        "library_fields": sorted(
            {key for row in library_metadata for key in row.data}
        ),
        "lab_fields": sorted(
            {
                key
                for row in labs
                for key, value in row.model_dump().items()
                if value not in ("", None)
                and key not in ("kind", "strain_id", "extra")
            }
            | {key for row in labs for key in row.extra}
        ),
    }


def parse_import_file(
    path: Path,
    *,
    home: Path,
    specimen_sheet: str = "",
    isolate_sheet: str = "",
    library_sheet: str = "",
    lab_sheet: str = "",
    metadata_sheet: str = "",
    lab_subject: str = "auto",
) -> tuple[BatchRecord | None, dict[str, Any], list[str]]:
    """解析湿实验文件为 batch 记录（Web/CLI 共用），不写入任何数据。

    返回 ``(record, summary, errors)``；errors 非空时 record 为 None。
    """
    metadata, specimen_metadata, library_metadata, labs, errors = _build_rows(
        path,
        metadata_sheet=metadata_sheet,
        specimen_sheet=specimen_sheet,
        isolate_sheet=isolate_sheet,
        library_sheet=library_sheet,
        lab_sheet=lab_sheet,
        lab_subject=lab_subject,
        home=home,
    )
    summary = _summary(metadata, specimen_metadata, library_metadata, labs)
    if errors:
        return None, summary, errors
    try:
        record = BatchRecord(
            rows=[*metadata, *specimen_metadata, *library_metadata, *labs]
        )
    except ValueError as exc:
        return None, summary, [str(exc)]
    return record, summary, []


def run_import(args: argparse.Namespace) -> None:
    path = Path(args.path).expanduser()
    if not path.is_file():
        raise SystemExit(T(f"file not found: {path}", f"文件不存在：{path}"))
    home = Path(args.home)
    try:
        record, summary, errors = parse_import_file(
            path,
            home=home,
            metadata_sheet=args.metadata_sheet,
            specimen_sheet=args.specimen_sheet,
            isolate_sheet=args.isolate_sheet,
            library_sheet=args.library_sheet,
            lab_sheet=args.lab_sheet,
            lab_subject=getattr(args, "lab_subject", "isolate"),
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(T(f"import parse failed: {exc}", f"导入解析失败：{exc}")) from exc
    if errors:
        preview = "\n".join(f"  - {line}" for line in errors[:20])
        more = f"\n  ... {len(errors) - 20} more" if len(errors) > 20 else ""
        raise SystemExit(
            T(
                f"import rejected: {len(errors)} invalid row(s)\n{preview}{more}",
                f"导入被拒绝：{len(errors)} 行无效\n{preview}{more}",
            )
        )
    if record is None:
        raise SystemExit(T("no data rows found", "没有可导入的数据行"))
    if args.dry_run:
        if args.json:
            print(json.dumps({**summary, "dry_run": True}, ensure_ascii=False, indent=2))
        else:
            print(
                T(
                    f"dry-run: isolate {summary['isolate_rows']}, "
                    f"specimen {summary['specimen_rows']}, "
                    f"library {summary['library_rows']}, lab {summary['lab_rows']} row(s), "
                    f"{len(summary['isolates'])} isolate(s)",
                    f"dry-run：菌株 {summary['isolate_rows']} 行、"
                    f"样本 {summary['specimen_rows']} 行、"
                    f"测序数据 {summary['library_rows']} 行、"
                    f"化验 {summary['lab_rows']} 行，"
                    f"涉及 {len(summary['isolates'])} 个菌株",
                )
            )
        return
    total = (
        summary["isolate_rows"]
        + summary["specimen_rows"]
        + summary["library_rows"]
        + summary["lab_rows"]
    )
    if total > 5000:
        raise SystemExit(T("too many rows (max 5000)", "行数过多（最多 5000）"))
    from bacmap.interfaces.cli.main import _engine
    from bacmap.tasks.spec import TaskType

    try:
        tid = _engine(args.home).submit(
            TaskType.RECORD,
            {"kind": "batch", "rows": [row.model_dump(mode="json") for row in record.rows]},
            args.by,
        )
    except ValueError as exc:
        raise SystemExit(T(f"submission failed: {exc}", f"提交失败：{exc}")) from exc
    if args.json:
        print(
            json.dumps(
                {**summary, "task_id": tid, "kind": "batch"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(
        T(
            f"submitted batch record task {tid}: isolate {summary['isolate_rows']}, "
            f"specimen {summary['specimen_rows']}, library {summary['library_rows']}, "
            f"lab {summary['lab_rows']} row(s); use `bacmap task show {tid}`",
            f"已提交批量记录任务 {tid}：菌株 {summary['isolate_rows']} 行、"
            f"样本 {summary['specimen_rows']} 行、测序数据 {summary['library_rows']} 行、"
            f"化验 {summary['lab_rows']} 行；用 `bacmap task show {tid}` 查看结果",
        )
    )
