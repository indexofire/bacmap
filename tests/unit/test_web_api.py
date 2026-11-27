"""版本化 JSON API（v1.5.2）：/api/v1 能力协商、任务/计划/事件/样本分页、SSE 续传。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.application.plans import PlanService, plan_task_id
from bacmap.interfaces.web import create_app
from bacmap.tasks.params import AnalyzeParams
from bacmap.tasks.spec import TaskType


@pytest.fixture(autouse=True)
def _no_debug_mode(monkeypatch):
    """v1.10.24：鉴权测试对本地 [debug] enabled 配置免疫（debug 下 Web 免鉴权）。"""
    monkeypatch.setattr("bacmap.config.debug_mode", lambda: False)


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    from bacmap.tasks.engine import task_engine

    started: list[str] = []
    monkeypatch.setattr(
        task_engine.DBOS, "start_workflow", lambda wf, p: started.append(p["task_id"])
    )
    monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
    metrics = {
        "S1": (5_000_000, 100, 50.0),
        "S2": (4_000_000, 50, 45.0),
        "S3": None,  # 缺组装字段：排序时必须排在最后
    }
    for sid in ("S1", "S2", "S3"):
        rep = tmp_path / "results" / sid / "report"
        rep.mkdir(parents=True)
        steps: dict[str, object] = {"species": {"verdict": "Salmonella"}}
        if metrics[sid] is not None:
            size, contigs, gc = metrics[sid]
            steps["assembly_quast"] = (
                "Assembly\t# contigs\tTotal length\tGC (%)\n"
                f"assembly\t{contigs}\t{size}\t{gc}"
            )
        (rep / f"{sid}_summary.json").write_text(
            json.dumps({"sample": sid, "steps": steps})
        )
    engine = eng.DbosTaskEngine(tmp_path)
    yield engine, TestClient(create_app(engine)), started
    eng.shutdown_dbos()


def _sse_events(text: str) -> list[dict]:
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":")
        )
        if "data" in fields:
            out.append({"id": int(fields["id"]), "event": fields["event"], **json.loads(fields["data"])})
    return out


class TestCapabilities:
    def test_versioned_and_leaks_no_paths(self, env):
        _, c, _ = env
        body = c.get("/api/v1/capabilities").json()
        assert body["api_version"] == "1"
        assert set(body["plannable_task_types"]) == {
            "analyze", "reanalyze", "curate", "mine", "write", "research",
        }
        assert "events.sse" in body["features"]
        assert "/" not in json.dumps({k: v for k, v in body.items() if k != "endpoints"})

    def test_stats_endpoint(self, env):
        _, c, _ = env
        body = c.get("/api/v1/stats").json()
        assert body["schema"] == "bacmap.stats/1"
        assert "tasks" in body and "strains" in body and "gom" in body
        assert body["results"]["sample_reports"] == 3


class TestTasks:
    def test_list_detail_cancel(self, env):
        engine, c, _ = env
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        assert [t["task_id"] for t in c.get("/api/v1/tasks").json()["items"]] == [tid]
        assert c.get(f"/api/v1/tasks/{tid}").json()["state"] == "running"
        assert c.post(f"/api/v1/tasks/{tid}/cancel").json()["state"] == "cancelled"
        again = c.post(f"/api/v1/tasks/{tid}/cancel")
        assert again.status_code == 409 and again.json()["code"] == "conflict"
        missing = c.get("/api/v1/tasks/nope")
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"

    def test_submit_returns_metadata(self, env):
        _, c, _ = env
        r = c.post(
            "/api/v1/tasks",
            json={"task_type": "analyze", "samples": "S1,S2", "submitted_by": "spa"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["task_type"] == "analyze" and body["submitted_by"] == "web"
        assert body["state"] == "running"
        assert c.get(f"/api/v1/tasks/{body['task_id']}").json()["task_type"] == "analyze"

    def test_submit_rejects_open_path_and_bad_scope(self, env):
        _, c, _ = env
        assert c.post("/api/v1/tasks", json={"task_type": "mine", "samples": "S1"}).status_code == 400
        assert (
            c.post("/api/v1/tasks", json={"task_type": "analyze", "samples": "S1", "scope": "[]"}).status_code
            == 400
        )

    def test_approve_validation(self, env):
        engine, c, _ = env
        tid = engine.submit(TaskType.CURATE, {"scope": {}}, "cli")
        bad = c.post(
            f"/api/v1/tasks/{tid}/approve",
            json={"approver": "ann", "decision": "approve", "signature": "sig"},
        )
        assert bad.status_code == 409  # 仍在 running，审批门未到
        missing = c.post(
            "/api/v1/tasks/nope/approve",
            json={"approver": "ann", "decision": "approve", "signature": "sig"},
        )
        assert missing.status_code == 404

    def test_overview_and_search(self, env):
        _, c, _ = env
        overview = c.get("/api/v1/overview").json()
        assert "BACMAP_HOME" in overview["paths"]
        assert overview["cloud_max_data_class"] in ("D1", "D2")
        assert overview["ai_max_data_class"] in ("D0", "D1", "D2", "D3", "D4")
        hits = c.get("/api/v1/search?q=Salmonella").json()["items"]
        assert {row["sample_id"] for row in hits} == {"S1", "S2", "S3"}

    def test_search_by_sample_id(self, env):
        _, c, _ = env
        hits = c.get("/api/v1/search?q=S1").json()["items"]
        assert {row["sample_id"] for row in hits} == {"S1"}

    def test_record_submit(self, env):
        _, c, _ = env
        r = c.post(
            "/api/v1/records/metadata",
            json={"strain_id": "S1", "fields": {"collection_date": "2026-01-01"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["task_type"] == "record" and body["state"] == "running"



class TestWetlabEdit:
    def test_edit_endpoints_submit_record_tasks(self, env):
        engine, c, _ = env
        cfg = engine.home / "workflows" / "bacmap" / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "samples.tsv").write_text(
            "sample\tspecies\tR1\tR2\tlongread\tassembly\tisolate\tplatform"
            "\tchecksum\tspecimen\n"
            "LIB-WEB\tSAL\t\t\t\ta.fasta\tISO-WEB\tilm\t\tSP-WEB\n",
            encoding="utf-8",
        )
        from bacmap.store.isolates import IsolateService
        from bacmap.store.specimens import SpecimenService

        db = engine.home / "data" / "bacmap.sqlite"
        with SpecimenService(db) as specimens:
            specimens.ensure("SP-WEB")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-WEB", specimen_id="SP-WEB")

        created = c.post(
            "/api/v1/wetlab/specimens",
            json={"specimen_id": "SP-NEW", "origin": "manual"},
        )
        assert created.status_code == 200, created.text
        assert created.json()["kind"] == "specimen_create"
        isolate_created = c.post(
            "/api/v1/wetlab/isolates",
            json={"isolate_id": "ISO-NEW", "specimen_id": "SP-WEB"},
        )
        assert isolate_created.status_code == 200, isolate_created.text
        assert isolate_created.json()["kind"] == "isolate_create"

        specimen = c.post(
            "/api/v1/wetlab/specimens/SP-WEB/metadata",
            json={"data": {"patient_name": "张三", "province": "广东"}},
        )
        assert specimen.status_code == 200, specimen.text
        assert specimen.json()["kind"] == "specimen_metadata"

        assigned = c.post(
            "/api/v1/wetlab/specimens/SP-WEB/assign",
            json={"isolates": ["ISO-WEB"], "datasets": ["LIB-WEB"]},
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["kind"] == "specimen_assign"

        isolate = c.post(
            "/api/v1/wetlab/isolates/ISO-WEB/metadata",
            json={
                "data": {"patient_phone": "13800000000", "custom_lab": "x"},
                "sample_id": "SP-WEB",
            },
        )
        assert isolate.status_code == 200, isolate.text
        assert isolate.json()["kind"] == "metadata"

        library = c.post(
            "/api/v1/wetlab/libraries/LIB-WEB/metadata",
            json={"data": {"run_id": "R1"}},
        )
        assert library.status_code == 200, library.text
        assert library.json()["kind"] == "library_metadata"

        lab = c.post(
            "/api/v1/wetlab/lab",
            json={
                "subject_type": "specimen",
                "subject_id": "SP-WEB",
                "category": "mngs",
                "test_name": "blaCTX-M",
                "result": "positive",
            },
        )
        assert lab.status_code == 200, lab.text
        assert lab.json()["kind"] == "lab_result"

        assert c.post(
            "/api/v1/wetlab/specimens/NOPE/metadata", json={"data": {}}
        ).status_code == 404
        assert c.post(
            "/api/v1/wetlab/isolates/NOPE/metadata", json={"data": {}}
        ).status_code == 404
        assert c.post(
            "/api/v1/wetlab/libraries/NOPE/metadata", json={"data": {}}
        ).status_code == 404
        assert c.post(
            "/api/v1/wetlab/lab",
            json={
                "subject_type": "isolate",
                "subject_id": "NOPE",
                "category": "mic",
                "test_name": "x",
                "result": "1",
            },
        ).status_code == 404

    def test_lab_update_and_metadata_delete_endpoints(self, env):
        engine, c, _ = env
        db = engine.home / "data" / "bacmap.sqlite"
        from bacmap.store.isolates import IsolateService
        from bacmap.store.lab_results import LabResultService
        from bacmap.store.specimen_metadata import SpecimenMetadataService
        from bacmap.store.specimens import SpecimenService

        with SpecimenService(db) as specimens:
            specimens.ensure("SP-DEL")
        with IsolateService(db) as isolates:
            isolates.ensure("ISO-DEL", specimen_id="SP-DEL")
        with SpecimenMetadataService(db) as store:
            store.upsert("SP-DEL", {"patient_name": "张三"})
        with LabResultService(db) as store:
            row = store.add("ISO-DEL", "mic", "meropenem", "0.25")

        updated = c.post(
            f"/api/v1/wetlab/lab/{row.id}",
            json={"result": "1.0", "notes": "rechecked"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["kind"] == "lab_result_update"
        assert c.post(
            "/api/v1/wetlab/lab/nope", json={"result": "1"}
        ).status_code == 404

        deleted = c.post("/api/v1/wetlab/specimens/SP-DEL/metadata/delete")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["kind"] == "specimen_metadata_delete"
        assert c.post("/api/v1/wetlab/isolates/ISO-DEL/metadata/delete").status_code == 200
        assert c.post(f"/api/v1/wetlab/lab/{row.id}/delete").status_code == 200
        assert c.post("/api/v1/wetlab/lab/nope/delete").status_code == 404

class TestPlans:
    def test_list_get_confirm_reject(self, env):
        engine, c, started = env
        svc = PlanService(engine, engine.db)
        rec = svc.create([AnalyzeParams(samples=["S1"])], "", "mcp-x")
        assert c.get("/api/v1/plans").json()["items"][0]["plan_id"] == rec.plan_id
        assert c.get(f"/api/v1/plans/{rec.plan_id}").json()["plan_hash"] == rec.plan_hash
        bad = c.post(
            f"/api/v1/plans/{rec.plan_id}/confirm",
            json={"version": 1, "plan_hash": "0" * 64, "confirmer": "ann"},
        )
        assert bad.status_code == 409 and started == []
        ok = c.post(
            f"/api/v1/plans/{rec.plan_id}/confirm",
            json={"version": 1, "plan_hash": rec.plan_hash, "confirmer": "ann"},
        )
        assert ok.json()["state"] == "submitted" and ok.json()["confirmed_by"] == "api:ann"
        assert started == [plan_task_id(rec.plan_id, 1, 0)]
        rec2 = svc.create([AnalyzeParams(samples=["S2"])], "", "mcp-x")
        rj = c.post(f"/api/v1/plans/{rec2.plan_id}/reject", json={"version": 1, "reason": "no"})
        assert rj.json()["state"] == "rejected"

    def test_validation_errors(self, env):
        _, c, _ = env
        r = c.post("/api/v1/plans/x/confirm", json={"version": "one"})
        assert r.status_code == 422
        assert c.get("/api/v1/plans/nope").status_code == 404


class TestEvents:
    def test_poll_with_cursor(self, env):
        engine, c, _ = env
        engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        first = c.get("/api/v1/events").json()
        assert [e["type"] for e in first["events"]] == ["task.submitted"]
        engine.submit(TaskType.ANALYZE, {"samples": ["S2"]}, "cli")
        nxt = c.get(f"/api/v1/events?after={first['last_seq']}").json()
        assert len(nxt["events"]) == 1 and nxt["events"][0]["seq"] > first["last_seq"]

    def test_sse_backlog_and_last_event_id(self, env):
        engine, c, _ = env
        engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        engine.submit(TaskType.ANALYZE, {"samples": ["S2"]}, "cli")
        r = c.get("/api/v1/events/stream?timeout=0")
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse_events(r.text)
        assert [e["event"] for e in events] == ["task.submitted", "task.submitted"]
        resumed = c.get(
            "/api/v1/events/stream?timeout=0", headers={"Last-Event-ID": str(events[0]["id"])}
        )
        assert [e["id"] for e in _sse_events(resumed.text)] == [events[1]["id"]]


class TestSamples:
    def test_cursor_pagination(self, env):
        _, c, _ = env
        p1 = c.get("/api/v1/samples?limit=2").json()
        assert [s["sample_id"] for s in p1["items"]] == ["S1", "S2"] and p1["next_cursor"] == "S2"
        p2 = c.get(f"/api/v1/samples?limit=2&cursor={p1['next_cursor']}").json()
        assert [s["sample_id"] for s in p2["items"]] == ["S3"] and p2["next_cursor"] is None

    def test_sort_by_assembly_metrics(self, env):
        _, c, _ = env
        desc = c.get("/api/v1/samples?sort=genome_size&order=desc&offset=0&limit=10").json()
        assert [s["sample_id"] for s in desc["items"]] == ["S1", "S2", "S3"]
        assert desc["items"][0]["genome_size"] == 5_000_000
        asc = c.get("/api/v1/samples?sort=contigs&order=asc&offset=0&limit=10").json()
        assert [s["sample_id"] for s in asc["items"]] == ["S2", "S1", "S3"]
        assert asc["total"] == 3 and asc["items"][0]["contigs"] == 50
        assert c.get("/api/v1/samples?sort=bogus").status_code == 400
        assert c.get("/api/v1/samples?sort=contigs&order=sideways").status_code == 400

    def test_sample_detail(self, env):
        _, c, _ = env
        body = c.get("/api/v1/samples/S1").json()
        assert body["digest"]["sample_id"] == "S1"
        assert body["digest"]["verdict"] == "Salmonella"
        assert body["digest"]["has_report"] is False
        assert c.get("/api/v1/samples/nope").status_code == 404

    def test_page_parses_only_requested_rows(self, env, monkeypatch):
        import bacmap.interfaces.views as views

        _, c, _ = env
        parsed: list[str] = []
        real = views._read_summary
        monkeypatch.setattr(views, "_read_summary", lambda p: parsed.append(p.name) or real(p))
        c.get("/api/v1/samples?limit=1")
        assert parsed == ["S1_summary.json"]


class TestCookieMode:
    def test_post_requires_csrf_header(self, env, monkeypatch):
        engine, _, _ = env
        monkeypatch.setenv("BACMAP_WEB_AUTH", "cookie")
        monkeypatch.setenv("BACMAP_WEB_SECRET", "s3cr3t-sign")
        c = TestClient(create_app(engine, auth_token="tok"))
        assert c.get("/api/v1/capabilities").status_code == 401
        c.post("/login", data={"token": "tok", "next": "/"})
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        h = {"origin": "http://testserver"}
        assert c.post(f"/api/v1/tasks/{tid}/cancel", headers=h).status_code == 403
        h["x-csrf-token"] = c.cookies.get("bacmap_csrf")
        assert c.post(f"/api/v1/tasks/{tid}/cancel", headers=h).status_code == 200


class TestDnsRebindingProtection:
    """Host 白名单（任何模式）+ 无鉴权时拒绝浏览器跨站状态变更。"""

    def test_foreign_host_rejected_without_token(self, env, monkeypatch):
        engine, _, _ = env
        monkeypatch.delenv("BACMAP_WEB_ALLOWED_HOSTS", raising=False)
        c = TestClient(create_app(engine), base_url="http://127.0.0.1:8800")
        assert c.get("/api/v1/tasks").status_code == 200
        assert c.get("/api/v1/tasks", headers={"host": "localhost:8800"}).status_code == 200
        assert c.get("/api/v1/tasks", headers={"host": "[::1]:8800"}).status_code == 200
        r = c.get("/api/v1/tasks", headers={"host": "evil.example:8800"})
        assert r.status_code == 400
        assert r.headers["x-frame-options"] == "DENY"
        assert c.post("/api/v1/tasks", headers={"host": "evil.example:8800"}).status_code == 400

    def test_foreign_host_rejected_with_token(self, env, monkeypatch):
        engine, _, _ = env
        monkeypatch.delenv("BACMAP_WEB_ALLOWED_HOSTS", raising=False)
        c = TestClient(create_app(engine, auth_token="tok"), base_url="http://127.0.0.1:8800")
        h = {"Authorization": "Bearer tok"}
        assert c.get("/api/v1/tasks", headers=h).status_code == 200
        h["host"] = "evil.example"
        assert c.get("/api/v1/tasks", headers=h).status_code == 400

    def test_bind_host_and_env_extras_allowed(self, env, monkeypatch):
        engine, _, _ = env
        monkeypatch.setenv("BACMAP_WEB_ALLOWED_HOSTS", "bacmap.lab.example, *")
        c = TestClient(create_app(engine, host="10.0.0.5"), base_url="http://10.0.0.5:8800")
        assert c.get("/api/v1/tasks").status_code == 200
        ok = {"host": "bacmap.lab.example"}
        assert c.get("/api/v1/tasks", headers=ok).status_code == 200
        # 无鉴权时 "*" 被忽略：Host 校验保持开启。
        assert c.get("/api/v1/tasks", headers={"host": "evil.example"}).status_code == 400

    def test_cross_site_post_rejected_without_token(self, env):
        engine, c, _ = env
        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        url = f"/api/v1/tasks/{tid}/cancel"
        assert c.post(url, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert c.post(url, headers={"origin": "http://evil.example"}).status_code == 403
        assert c.post(url, headers={"origin": "null"}).status_code == 403
        assert c.post(url, headers={"sec-fetch-site": "same-origin"}).status_code == 200

class TestPaginationContract:
    """v1.10.31：数据列表统一 offset/limit + total 分页。"""

    def test_tasks_offset_and_total(self, env):
        engine, c, _ = env
        for _ in range(3):
            engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli")
        body = c.get("/api/v1/tasks?limit=2&offset=1").json()
        assert body["total"] == 3
        assert body["offset"] == 1 and body["limit"] == 2
        assert len(body["items"]) == 2

    def test_samples_offset_and_total(self, env):
        _, c, _ = env
        body = c.get("/api/v1/samples?limit=1&offset=1").json()
        assert body["total"] == 3
        assert body["offset"] == 1 and body["limit"] == 1
        assert len(body["items"]) == 1

    def test_search_offset_and_total(self, env):
        _, c, _ = env
        body = c.get("/api/v1/search?limit=2&offset=0").json()
        assert body["total"] == 3
        assert body["offset"] == 0 and body["limit"] == 2
        assert len(body["items"]) == 2

    def test_other_lists_return_page_shape(self, env):
        _, c, _ = env
        for path in (
            "/api/v1/runs",
            "/api/v1/gom/objects",
            "/api/v1/specimens",
            "/api/v1/isolates",
            "/api/v1/records",
        ):
            body = c.get(f"{path}?limit=10&offset=0").json()
            assert set(body) >= {"items", "total", "offset", "limit"}, path
            assert body["offset"] == 0 and body["limit"] == 10


class TestResearchDagApi:
    def test_dag_endpoint(self, env):
        import json as _json

        from bacmap.research.dagstore import DagStore

        engine, client, _started = env
        with DagStore(Path(engine.home)) as store:
            store.ensure_run("t1", "hash", 2)
            store.put_artifact(
                type_="Table", value={"a": 1}, task_id="t1", node_id="n1"
            )
            store.mark_running("t1", "n1", "stats.assoc@1.0")
        res = client.get("/api/v1/research/dag/t1")
        assert res.status_code == 200
        body = res.json()
        assert body["run"]["task_id"] == "t1"
        assert body["nodes"][0]["node_id"] == "n1"
        assert len(body["artifacts"]) == 1
        assert _json.dumps(body)  # JSON-serialisable

    def test_dag_endpoint_missing(self, env):
        _engine, client, _started = env
        assert client.get("/api/v1/research/dag/nope").status_code == 404

    def test_dag_artifact_content_and_scope(self, env):
        import urllib.parse

        from bacmap.research.dagstore import DagStore

        engine, client, _started = env
        with DagStore(Path(engine.home)) as store:
            store.ensure_run("t1", "hash", 2)
            artifact = store.put_artifact(
                type_="Text", value={"markdown": "# hello"}, task_id="t1", node_id="n1"
            )
            # 另一个任务的产物不可通过 t1 读取
            store.put_artifact(
                type_="Text", value={"markdown": "secret"}, task_id="t2", node_id="n2"
            )
        encoded = urllib.parse.quote(artifact, safe="")
        res = client.get(f"/api/v1/research/dag/t1/artifacts/{encoded}")
        assert res.status_code == 200
        assert res.json()["value"]["markdown"] == "# hello"
        other = client.get(
            "/api/v1/research/dag/t1/artifacts/" + urllib.parse.quote("sha256:" + "0" * 64)
        )
        assert other.status_code == 404
