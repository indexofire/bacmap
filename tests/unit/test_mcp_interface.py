"""MCP 接口测试（ADR-12 / V11④：write 工具不得暴露；提交/状态回环）。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.mcp.server import build_server
from bacmap.tasks.spec import TaskState

WRITE_TOOLS = {"bio_analyze_pathogen", "bio_add_metadata", "bio_add_lab_result"}


class _NoopArbiter:
    @contextlib.contextmanager
    def heavy_step(self):
        yield


def _noop_arbiter() -> _NoopArbiter:
    return _NoopArbiter()


def _list_tool_names(server) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def _call(server, name: str, arguments: dict) -> dict:
    res = asyncio.run(server.call_tool(name, arguments))
    return json.loads(res.content[0].text)


class TestToolExposure:
    def test_write_tools_not_exposed_v11d4(self):
        names = _list_tool_names(build_server())
        assert not (names & WRITE_TOOLS), "V11④ 违规：write 工具出现在 MCP 暴露面"

    def test_read_compute_tools_exposed(self):
        names = _list_tool_names(build_server())
        for expected in ("bio_seq_stats", "bio_get_result", "bio_search_samples", "bio_gene_scan"):
            assert expected in names

    def test_task_tools_absacent_without_engine(self):
        names = _list_tool_names(build_server())
        assert "bacmap_submit_task" not in names
        assert "bacmap_task_status" not in names

    def test_input_schema_generated_from_legacy(self):
        server = build_server()
        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        schema = tools["bio_seq_stats"].input_schema
        props = schema.get("properties", {})
        assert "params" in props
        assert "$ref" in props["params"]  # SDK 以 $defs/$ref 包装模型参数
        inner = schema["$defs"]["bio_seq_statsInput"]["properties"]
        assert "file" in inner
        assert "file" in schema["$defs"]["bio_seq_statsInput"].get("required", [])


class TestReadToolRoundtrip:
    def test_bio_seq_stats(self, tmp_path: Path):
        fa = tmp_path / "x.fa"
        fa.write_text(">c1\nACGTACGTAC\n>c2\nGGGG\n", encoding="utf-8")
        server = build_server()
        out = _call(server, "bio_seq_stats", {"params": {"file": str(fa)}})
        assert "error" not in out, out
        dumped = json.dumps(out)
        ok = out.get("n_sequences") == 2 or out.get("total_sequences") == 2 or "stats" in dumped
        assert ok, out

    def test_missing_required_param_raises_validation(self):
        server = build_server()
        with pytest.raises(Exception, match="Field required"):
            asyncio.run(server.call_tool("bio_seq_stats", {"params": {}}))


def _sal_summary() -> dict:
    return {
        "sample": "SAM-001",
        "steps": {
            "species": {"verdict": "Salmonella"},
            "mlst": "FILE\tSCHEME\tST\taroC\ncontigs\tsalmonella_2\t19\t2",
            "serotype": {"sistr": "Typhimurium"},
            "amr": {"abricate_card": [{"GENE": "blaCTX-M-15"}]},
            "qc": {"after_filtering": {"total_reads": 1000}},
            "dec": {},
        },
    }


class _Proc:
    returncode = 0


class TestTaskToolsRoundtrip:
    @pytest.fixture
    def server(self, tmp_path: Path, monkeypatch):
        rep = tmp_path / "results" / "SAM-001" / "report"
        rep.mkdir(parents=True)
        (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
        monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc())
        monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "mcp-run-1"})
        monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
        monkeypatch.setattr(eng, "_generate_report_for", lambda s: {"sample_id": s})
        monkeypatch.setattr(eng, "_memory_arbiter", _noop_arbiter)
        engine = eng.DbosTaskEngine(tmp_path)
        srv = build_server(engine)
        yield srv
        eng.shutdown_dbos()

    def test_submit_and_poll_to_succeeded(self, server):
        out = _call(
            server,
            "bacmap_submit_task",
            {"task_type": "analyze", "samples": ["SAM-001"], "submitted_by": "mcp-test"},
        )
        assert "task_id" in out, out
        tid = out["task_id"]

        deadline = time.time() + 30
        state = None
        while time.time() < deadline:
            st = _call(server, "bacmap_task_status", {"task_id": tid})
            state = st.get("state")
            if state != TaskState.RUNNING.value:
                break
            time.sleep(0.2)
        assert state == TaskState.SUCCEEDED.value

    def test_unknown_task_type_error(self, server):
        out = _call(server, "bacmap_submit_task", {"task_type": "deploy"})
        assert "error" in out

    def test_submit_rejects_path_traversal_sample(self, server):
        out = _call(
            server,
            "bacmap_submit_task",
            {"task_type": "analyze", "samples": ["../../etc/passwd"]},
        )
        assert "error" in out
        assert "invalid sample" in out["error"]

    def test_submit_rejects_open_path_task_types(self, server):
        for tt in ("mine", "write"):
            out = _call(server, "bacmap_submit_task", {"task_type": tt})
            assert "error" in out, (tt, out)

    def test_submit_rejects_mixed_invalid_samples(self, server):
        out = _call(
            server,
            "bacmap_submit_task",
            {"task_type": "analyze", "samples": ["SAM-001", "bad/slash"]},
        )
        assert "error" in out

    def test_unknown_task_status_error(self, server):
        out = _call(server, "bacmap_task_status", {"task_id": "no-such"})
        assert "error" in out
