"""``bacmap record``（v1.7）：记录类任务只经任务层提交。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import bacmap.interfaces.cli.main as cli


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []
        self.error: ValueError | None = None

    def submit(self, task_type, params, submitted_by):
        self.calls.append((str(task_type), dict(params), submitted_by))
        if self.error is not None:
            raise self.error
        return "t" * 32


@pytest.fixture
def engine(monkeypatch):
    e = _Engine()
    monkeypatch.setattr(cli, "_engine", lambda home: e)
    return e


def _run(capsys, *argv: str) -> str:
    cli.main(list(argv))
    return capsys.readouterr().out


def test_metadata_record(engine, capsys, tmp_path: Path):
    out = _run(
        capsys, "record", "metadata", "--strain-id", "S1",
        "--field", "province=Guangdong", "--field", "sample_source=food",
        "--home", str(tmp_path), "--json",
    )
    assert json.loads(out)["kind"] == "metadata"
    kind, params, by = engine.calls[0]
    assert kind == "record"
    assert params["strain_id"] == "S1" and params["sample_id"] == "S1"
    assert params["fields"] == {"province": "Guangdong", "sample_source": "food"}
    assert params["kind"] == "metadata" and by == "cli"


def test_lab_record(engine, capsys, tmp_path: Path):
    _run(
        capsys, "record", "lab", "--strain-id", "S1", "--category", "mic",
        "--test-name", "meropenem", "--result", "0.25", "--unit", "mg/L",
        "--home", str(tmp_path),
    )
    params = engine.calls[0][1]
    assert params["kind"] == "lab_result" and params["unit"] == "mg/L"
    assert "result" in params and params["category"] == "mic"


def test_knowledge_import_and_approve(engine, capsys, tmp_path: Path):
    _run(
        capsys, "record", "knowledge-import", "--title", "Paper",
        "--identifier", "PMID:123", "--year", "2025", "--home", str(tmp_path),
    )
    params = engine.calls[0][1]
    assert params["kind"] == "knowledge_import" and params["entry_kind"] == "literature"
    assert "authors" not in params  # 空值不提交，交由模型默认

    _run(capsys, "record", "knowledge-approve", "7", "--home", str(tmp_path), "--json")
    assert engine.calls[1][1] == {"entry_id": 7, "kind": "knowledge_approve"}


def test_bad_field_and_engine_error(engine, capsys, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BACMAP_LANG", "zh")
    with pytest.raises(SystemExit, match="k=v"):
        _run(capsys, "record", "metadata", "--strain-id", "S1", "--field", "province",
             "--home", str(tmp_path))
    engine.error = ValueError("invalid record: metadata.strain_id: Field required")
    with pytest.raises(SystemExit, match="提交失败"):
        _run(capsys, "record", "metadata", "--strain-id", "S1", "--home", str(tmp_path))


def test_record_is_in_help(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["bacmap", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "record" in out and "task" in out


def test_import_xlsx_batch(engine, capsys, tmp_path: Path):
    from openpyxl import Workbook

    from bacmap.store.isolates import IsolateService

    with IsolateService(tmp_path / "data" / "bacmap.sqlite") as isolates:
        isolates.ensure("ISO-1")
        isolates.ensure("ISO-2")

    book = Workbook()
    meta = book.active
    meta.title = "metadata"
    meta.append(["菌株编号", "省份", "自定义字段"])
    meta.append(["ISO-1", "Guangdong", "custom-value"])
    lab = book.create_sheet("lab")
    lab.append(["菌株编号", "类别", "检验项目", "结果", "单位", "备注"])
    lab.append(["ISO-2", "mic", "meropenem", 0.25, "mg/L", "panel-A"])
    path = tmp_path / "wetlab.xlsx"
    book.save(path)

    out = _run(
        capsys,
        "record",
        "import",
        str(path),
        "--home",
        str(tmp_path),
        "--json",
    )
    body = json.loads(out)
    assert body["isolate_rows"] == 1 and body["lab_rows"] == 1
    kind, params, by = engine.calls[0]
    assert kind == "record" and params["kind"] == "batch" and by == "cli:import"
    rows = params["rows"]
    assert {row["kind"] for row in rows} == {"metadata", "lab_result"}
    metadata_row = next(row for row in rows if row["kind"] == "metadata")
    assert metadata_row["strain_id"] == "ISO-1"
    assert metadata_row["fields"]["province"] == "Guangdong"
    assert metadata_row["extra"]["自定义字段"] == "custom-value"
    lab_row = next(row for row in rows if row["kind"] == "lab_result")
    assert lab_row["strain_id"] == "ISO-2"
    assert lab_row["result"] == "0.25" and lab_row["unit"] == "mg/L"


def test_import_dry_run_does_not_submit(engine, capsys, tmp_path: Path):
    from bacmap.store.isolates import IsolateService

    with IsolateService(tmp_path / "data" / "bacmap.sqlite") as isolates:
        isolates.ensure("ISO-1")
    path = tmp_path / "wetlab.tsv"
    path.write_text("菌株编号\t省份\nISO-1\tGuangdong\n", encoding="utf-8")
    _run(capsys, "record", "import", str(path), "--home", str(tmp_path), "--dry-run")
    assert engine.calls == []


def test_import_four_layer_xlsx(engine, capsys, tmp_path: Path):
    from openpyxl import Workbook

    from bacmap.store.isolates import IsolateService
    from bacmap.store.specimens import SpecimenService

    db = tmp_path / "data" / "bacmap.sqlite"
    with SpecimenService(db) as specimens:
        specimens.ensure("SP-1")
    with IsolateService(db) as isolates:
        isolates.ensure("ISO-1", specimen_id="SP-1")
    cfg = tmp_path / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "samples.tsv").write_text(
        "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
        "\tchecksum\tspecimen\n"
        "LIB-1\tSAL\t\t\t\ta.fasta\tISO-1\tilm\t\tSP-1\n",
        encoding="utf-8",
    )

    book = Workbook()
    specimen = book.active
    specimen.title = "specimen"
    specimen.append(["样本编号", "患者姓名", "采样日期"])
    specimen.append(["SP-1", "张三", "2026-10-01"])
    isolate = book.create_sheet("isolate")
    isolate.append(["菌株编号", "分离日期", "省份"])
    isolate.append(["ISO-1", "2026-10-02", "广东"])
    library = book.create_sheet("library")
    library.append(["测序数据编号", "平台", "测序日期"])
    library.append(["LIB-1", "illumina", "2026-10-03"])
    lab = book.create_sheet("lab")
    lab.append(["测序数据编号", "类别", "检验项目", "结果"])
    lab.append(["LIB-1", "mic", "meropenem", "0.25"])
    path = tmp_path / "wetlab-four.xlsx"
    book.save(path)

    out = _run(
        capsys, "record", "import", str(path), "--home", str(tmp_path), "--json"
    )
    body = json.loads(out)
    assert body["specimen_rows"] == 1
    assert body["isolate_rows"] == 1
    assert body["library_rows"] == 1
    assert body["lab_rows"] == 1
    rows = engine.calls[0][1]["rows"]
    assert {row["kind"] for row in rows} == {
        "specimen_metadata", "metadata", "library_metadata", "lab_result"
    }
    specimen_row = next(row for row in rows if row["kind"] == "specimen_metadata")
    assert specimen_row["specimen_id"] == "SP-1"
    assert specimen_row["data"]["患者姓名"] == "张三"
    library_row = next(row for row in rows if row["kind"] == "library_metadata")
    assert library_row["library_id"] == "LIB-1"
    assert library_row["isolate_id"] == "ISO-1"
    assert library_row["specimen_id"] == "SP-1"
    lab_row = next(row for row in rows if row["kind"] == "lab_result")
    assert lab_row["subject_type"] == "isolate"
    assert lab_row["subject_id"] == "ISO-1"


def test_lab_can_target_specimen(engine, capsys, tmp_path: Path):
    from openpyxl import Workbook

    from bacmap.store.specimens import SpecimenService

    with SpecimenService(tmp_path / "data" / "bacmap.sqlite") as specimens:
        specimens.ensure("SP-1")
    book = Workbook()
    lab = book.active
    lab.title = "lab"
    lab.append(["样本编号", "类别", "检验项目", "结果"])
    lab.append(["SP-1", "mngs", "blaCTX-M", "positive"])
    path = tmp_path / "specimen-lab.xlsx"
    book.save(path)
    _run(
        capsys,
        "record",
        "import",
        str(path),
        "--lab-subject",
        "specimen",
        "--home",
        str(tmp_path),
        "--json",
    )
    row = engine.calls[0][1]["rows"][0]
    assert row["kind"] == "lab_result"
    assert row["subject_type"] == "specimen" and row["subject_id"] == "SP-1"
