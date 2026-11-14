"""样本/菌株身份模型只读接口（v1.10.27 P2）。

覆盖 `/api/v1/specimens`、`/api/v1/isolates` 的列表/详情、库行归属与 404。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.web import create_app
from bacmap.store.isolates import IsolateService
from bacmap.store.specimens import SpecimenService

_TSV = (
    "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform\tchecksum\tspecimen\n"
    "LIB-1\tSAL\t\t\t\ta.fasta\tISO-1\tilm\t\tA03-SN-001\n"
    "LIB-2\tSAL\t\t\t\tb.fasta\tISO-1\tont\t\tA03-SN-001\n"
    "LIB-3\tSAL\t\t\t\tc.fasta\tISO-2\tilm\t\t\n"
)


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    cfg = home / "workflows" / "bacmap" / "config"
    cfg.mkdir(parents=True)
    (cfg / "samples.tsv").write_text(_TSV, encoding="utf-8")
    db = home / "data" / "bacmap.sqlite"
    with SpecimenService(db) as specimens:
        specimens.ensure("A03-SN-001")
    with IsolateService(db) as isolates:
        isolates.ensure("ISO-1", specimen_id="A03-SN-001")
        isolates.ensure("ISO-2")
    return home


def test_specimens_and_isolates_lists_and_details(tmp_path):
    engine = eng.DbosTaskEngine(_home(tmp_path))
    try:
        client = TestClient(create_app(engine))
        items = client.get("/api/v1/specimens").json()["items"]
        assert items[0]["specimen_id"] == "A03-SN-001"
        assert items[0]["n_isolates"] == 1

        detail = client.get("/api/v1/specimens/A03-SN-001").json()
        isolate = detail["isolates"][0]
        assert isolate["isolate_id"] == "ISO-1"
        assert {lib["library_id"] for lib in isolate["libraries"]} == {"LIB-1", "LIB-2"}

        isolates = client.get("/api/v1/isolates").json()["items"]
        by_id = {row["isolate_id"]: row for row in isolates}
        assert by_id["ISO-1"]["n_libraries"] == 2
        assert by_id["ISO-2"]["n_libraries"] == 1

        isolate_detail = client.get("/api/v1/isolates/ISO-1").json()
        assert isolate_detail["specimen"]["specimen_id"] == "A03-SN-001"
        assert len(isolate_detail["libraries"]) == 2
    finally:
        eng.shutdown_dbos()


def test_unknown_ids_and_missing_db(tmp_path):
    engine = eng.DbosTaskEngine(_home(tmp_path))
    try:
        client = TestClient(create_app(engine))
        assert client.get("/api/v1/specimens/NOPE").status_code == 404
        assert client.get("/api/v1/isolates/NOPE").status_code == 404
    finally:
        eng.shutdown_dbos()

    empty = tmp_path / "fresh"
    empty.mkdir()
    engine = eng.DbosTaskEngine(empty)
    try:
        client = TestClient(create_app(engine))
        assert client.get("/api/v1/specimens").json()["items"] == []
        assert client.get("/api/v1/isolates").json()["items"] == []
    finally:
        eng.shutdown_dbos()


def test_search_identity_and_isolate_wet_lab(tmp_path):
    home = _home(tmp_path)
    db = home / "data" / "bacmap.sqlite"
    from bacmap.store.lab_results import LabResultService
    from bacmap.store.strain_metadata import StrainMetadataService

    with StrainMetadataService(db) as meta:
        meta.upsert("ISO-1", {"province": "ZJ", "patient_age": "42"})
    with LabResultService(db) as lab:
        lab.add("ISO-1", "antimicrobial", "meropenem", "R", unit="mg/L")

    engine = eng.DbosTaskEngine(home)
    try:
        client = TestClient(create_app(engine))
        by_specimen = client.get("/api/v1/search/identity?q=A03").json()
        assert [row["specimen_id"] for row in by_specimen["specimens"]] == ["A03-SN-001"]
        by_isolate = client.get("/api/v1/search/identity?q=ISO-1").json()
        assert by_isolate["isolates"][0]["isolate_id"] == "ISO-1"

        detail = client.get("/api/v1/isolates/ISO-1").json()
        assert detail["metadata"]["province"] == "ZJ"
        assert detail["lab_results"][0]["test_name"] == "meropenem"
        assert detail["lab_results"][0]["result"] == "R"
    finally:
        eng.shutdown_dbos()


def test_delete_specimen_endpoint(tmp_path):
    home = _home(tmp_path)
    engine = eng.DbosTaskEngine(home)
    try:
        client = TestClient(create_app(engine))
        db = home / "data" / "bacmap.sqlite"

        # 有关联菌株：默认 409，不删任何东西
        response = client.post("/api/v1/specimens/A03-SN-001/delete", json={"force": False})
        assert response.status_code == 409
        with SpecimenService(db) as specimens:
            assert specimens.get("A03-SN-001") is not None

        # force：解除关联后删除，菌株与测序数据保留
        response = client.post("/api/v1/specimens/A03-SN-001/delete", json={"force": True})
        assert response.status_code == 200
        payload = response.json()
        assert payload["deleted"] is True
        assert payload["unlinked_isolates"] == 1
        assert payload["updated_tsv_rows"] == 2
        with SpecimenService(db) as specimens:
            assert specimens.get("A03-SN-001") is None
        with IsolateService(db) as isolates:
            assert isolates.get("ISO-1")["specimen_id"] is None
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        assert "A03-SN-001" not in tsv.read_text()

        # 不存在的样本 → 404
        assert (
            client.post("/api/v1/specimens/NOPE/delete", json={"force": True}).status_code
            == 404
        )
    finally:
        eng.shutdown_dbos()


def test_assign_specimen_endpoint(tmp_path):
    home = _home(tmp_path)
    engine = eng.DbosTaskEngine(home)
    try:
        client = TestClient(create_app(engine))
        response = client.post(
            "/api/v1/specimens/assign",
            json={"specimen_id": "B04-SN-002", "isolates": ["ISO-2"]},
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 1
        db = home / "data" / "bacmap.sqlite"
        with IsolateService(db) as isolates:
            assert isolates.get("ISO-2")["specimen_id"] == "B04-SN-002"
        with SpecimenService(db) as specimens:
            assert specimens.get("B04-SN-002") is not None
        assert client.post("/api/v1/specimens/assign", json={"specimen_id": "X"}).status_code == 400
    finally:
        eng.shutdown_dbos()
