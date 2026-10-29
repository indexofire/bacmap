"""MCP 接口测试（ADR-12 / V11④：write 工具不得暴露；提交/状态回环）。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.interfaces.mcp.profiles import (
    McpProfile,
    ProfileNotAllowedError,
    ProfileSpec,
    resolve_profile,
)
from bacmap.interfaces.mcp.server import DEFAULT_PROFILE, build_server, exposed_specs
from bacmap.tasks.spec import TaskState
from bacmap.tools import registry as tool_registry
from bacmap.tools.spec import DataClass

TRUSTED = ProfileSpec(
    profile=McpProfile.LOCAL_TRUSTED, max_data_class=DataClass.D4, actor="mcp-test-trusted"
)

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
        names = _list_tool_names(build_server(profile=TRUSTED))
        for expected in ("bio_seq_stats", "bio_get_result", "bio_search_samples", "bio_gene_scan"):
            assert expected in names

    def test_task_tools_absacent_without_engine(self):
        names = _list_tool_names(build_server())
        assert "bacmap_submit_task" not in names
        assert "bacmap_task_status" not in names

    def test_input_schema_generated_from_legacy(self):
        server = build_server(profile=TRUSTED)
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
        server = build_server(profile=TRUSTED)
        out = _call(server, "bio_seq_stats", {"params": {"file": str(fa)}})
        assert "error" not in out, out
        dumped = json.dumps(out)
        ok = out.get("n_sequences") == 2 or out.get("total_sequences") == 2 or "stats" in dumped
        assert ok, out

    def test_missing_required_param_raises_validation(self):
        server = build_server(profile=TRUSTED)
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
        monkeypatch.setattr(eng, "_generate_report_for", lambda s, *a: {"sample_id": s})
        monkeypatch.setattr(eng, "_memory_arbiter", _noop_arbiter)
        engine = eng.DbosTaskEngine(tmp_path)
        srv = build_server(engine, TRUSTED)
        srv.engine_for_test = engine
        yield srv
        eng.shutdown_dbos()

    def test_submit_and_poll_to_succeeded(self, server):
        out = _call(
            server,
            "bacmap_submit_task",
            {"task_type": "analyze", "samples": ["SAM-001"]},
        )
        assert "task_id" in out, out
        tid = out["task_id"]
        # 提交者身份由服务端 Profile 决定（v1.5 审计链），不来自客户端参数
        rows = {t["task_id"]: t for t in server.engine_for_test.list_tasks(10)}
        assert rows[tid]["submitted_by"] == "mcp-test-trusted"

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

    def test_submit_analyze_without_samples_error(self, server):
        out = _call(server, "bacmap_submit_task", {"task_type": "analyze"})
        assert "error" in out and "sample" in out["error"]

    def test_unknown_task_status_error(self, server):
        out = _call(server, "bacmap_task_status", {"task_id": "no-such"})
        assert "error" in out


class TestProfileDataClassFiltering:
    """v1.5（ADR-16）：MCP 默认 cloud Profile，按 output_data_class 裁剪工具带。"""

    def test_default_profile_hides_d2_and_above(self):
        names = _list_tool_names(build_server())
        for spec in tool_registry.list_specs():
            if spec.output_data_class > DataClass.D1:
                assert spec.name not in names, spec.name
        assert "bio_query_metadata" not in names  # D4
        assert "bio_seq_stats" not in names  # D3
        assert "bio_get_result" not in names  # D2

    def test_default_profile_keeps_low_class_read_tools(self):
        names = _list_tool_names(build_server())
        assert "bio_list_reference_genomes" in names  # D0
        # 注册表工具按 Profile 裁剪；能力协商工具始终可用（不涉及数据）
        assert names == {s.name for s in exposed_specs(DEFAULT_PROFILE)} | {"bacmap_capabilities"}

    def test_hidden_tool_call_rejected(self, tmp_path: Path):
        fa = tmp_path / "x.fa"
        fa.write_text(">c\nACGT\n", encoding="utf-8")
        with pytest.raises(Exception, match=r"(?i)unknown tool|not found"):
            asyncio.run(build_server().call_tool("bio_seq_stats", {"params": {"file": str(fa)}}))

    def test_trusted_profile_exposes_d4_but_never_write(self):
        names = _list_tool_names(build_server(profile=TRUSTED))
        assert "bio_query_metadata" in names
        assert not (names & WRITE_TOOLS)

    def test_resolve_cloud_follows_data_policy(self, tmp_path: Path):
        (tmp_path / "config.toml").write_text(
            "[llm.endpoints.api]\nkind='openai_compatible'\nlocation='cloud'\n"
            "base_url='https://example.invalid/v1'\nmodel='m'\ntier='T2'\n"
            "[llm.data_policy]\ncloud_max_data_class='D2'\n",
            encoding="utf-8",
        )
        spec = resolve_profile("cloud", tmp_path, "stdio")
        assert spec.max_data_class == DataClass.D2
        assert spec.actor.startswith("mcp-stdio:cloud:")

    def test_resolve_cloud_default_is_d1(self, tmp_path: Path):
        spec = resolve_profile("cloud", tmp_path, "http")
        assert spec.max_data_class == DataClass.D1
        assert spec.actor == "mcp-http:cloud"

    def test_local_trusted_requires_admin_opt_in(self, tmp_path: Path):
        with pytest.raises(ProfileNotAllowedError, match="allow_local_trusted"):
            resolve_profile("local-trusted", tmp_path, "stdio")
        (tmp_path / "config.toml").write_text(
            "[mcp]\nallow_local_trusted = 'yes'\n", encoding="utf-8"
        )
        with pytest.raises(ProfileNotAllowedError):  # 必须是布尔 true，不接受真值字符串
            resolve_profile("local-trusted", tmp_path, "stdio")
        (tmp_path / "config.toml").write_text(
            "[mcp]\nallow_local_trusted = true\n", encoding="utf-8"
        )
        assert resolve_profile("local-trusted", tmp_path, "stdio").max_data_class == DataClass.D4

    def test_unknown_profile_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            resolve_profile("root", tmp_path, "stdio")

    def test_launch_refuses_disabled_profile(self, tmp_path: Path):
        from bacmap.interfaces.mcp.launch import serve

        def _no_engine(home: Path):
            raise AssertionError("engine must not be built when profile is refused")

        with pytest.raises(SystemExit, match="allow_local_trusted"):
            serve(
                home=tmp_path, profile_name="local-trusted", read_only=False,
                transport="stdio", host="127.0.0.1", port=0, uds="",
                token_env="X", engine_factory=_no_engine,
            )


class TestPlanTools:
    """v1.5.1（ADR-21）：Harness 只能创建/修订/查询计划，确认不在 MCP。"""

    @pytest.fixture
    def server(self, tmp_path: Path):
        engine = eng.DbosTaskEngine(tmp_path)
        srv = build_server(engine)  # 默认 cloud Profile 也可建计划
        srv.engine_for_test = engine
        yield srv
        eng.shutdown_dbos()

    def test_plan_tools_exposed_but_no_confirm(self, server):
        names = _list_tool_names(server)
        assert {"bacmap_create_plan", "bacmap_revise_plan", "bacmap_get_plan"} <= names
        # 本地弹窗工具是"人点击"通道（v1.9.0），不是模型确认；不允许存在普通确认工具。
        assert "bacmap_confirm_plan_locally" in names
        assert not any("approve" in n or n == "bacmap_confirm_plan" for n in names)

    def test_plan_tools_absent_in_read_only(self):
        names = _list_tool_names(build_server())
        assert "bacmap_create_plan" not in names

    def test_create_revise_get_roundtrip(self, server):
        out = _call(
            server,
            "bacmap_create_plan",
            {"tasks": [{"task_type": "analyze", "samples": ["SAM-001"]}], "rationale": "r"},
        )
        assert out["state"] == "awaiting_confirmation" and out["version"] == 1
        assert out["created_by"].startswith("mcp-stdio:cloud:")
        assert "bacmap plan confirm" in out["next_step"]
        assert server.engine_for_test.list_tasks(10) == []  # 未确认，不执行

        rev = _call(
            server,
            "bacmap_revise_plan",
            {"plan_id": out["plan_id"], "tasks": [{"task_type": "curate"}]},
        )
        assert rev["version"] == 2
        got = _call(server, "bacmap_get_plan", {"plan_id": out["plan_id"], "version": 1})
        assert got["state"] == "superseded"

    def test_invalid_tasks_rejected(self, server):
        with pytest.raises(Exception, match=r"(?i)bogus|task_type|discriminator|tag"):
            asyncio.run(
                server.call_tool("bacmap_create_plan", {"tasks": [{"task_type": "bogus"}]})
            )

    def test_open_path_plan_is_accepted(self, server):
        out = _call(
            server,
            "bacmap_create_plan",
            {
                "tasks": [
                    {
                        "task_type": "mine",
                        "objective": "按 ST 统计",
                        "script": "print(1)",
                        "input_paths": [],
                    }
                ],
                "rationale": "open path",
            },
        )
        assert out["state"] == "awaiting_confirmation" and out["version"] == 1
        out = _call(server, "bacmap_get_plan", {"plan_id": "nope"})
        assert out["code"] == "not_found"


class TestSkillResources:
    """v1.5.2（ADR-12/21）：角色说明书以 skill:// 资源发布，带内容摘要（版本可追溯）。"""

    def test_listed_with_digest(self):
        import hashlib

        from bacmap.agent import roledef

        res = {str(r.uri): r for r in asyncio.run(build_server().list_resources())}
        uri = "skill://bacmap/analyst/SKILL.md"
        assert uri in res and res[uri].mime_type == "text/markdown"
        raw = roledef.skill_markdown("analyst")
        assert res[uri].meta["sha256"] == hashlib.sha256(raw.encode()).hexdigest()

    def test_read_returns_skill(self):
        from bacmap.agent import roledef

        contents = asyncio.run(build_server().read_resource("skill://bacmap/analyst/SKILL.md"))
        text = "".join(getattr(c, "content", "") or getattr(c, "text", "") for c in contents)
        assert text == roledef.skill_markdown("analyst")


class TestTaskControlTools:
    """v1.5.2：取消只限本主体的任务；结果按 Profile 数据级别裁剪；cloud 不回传任务消息。"""

    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        monkeypatch.setattr(task_engine.DBOS, "cancel_workflow", lambda wid: None)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def test_cancel_own_task(self, engine):
        server = build_server(engine, TRUSTED)
        tid = _call(server, "bacmap_submit_task", {"task_type": "analyze", "samples": ["S1"]})[
            "task_id"
        ]
        out = _call(server, "bacmap_task_cancel", {"task_id": tid})
        assert out["state"] == "cancelled"
        again = _call(server, "bacmap_task_cancel", {"task_id": tid})
        assert again["code"] == "conflict"

    def test_cannot_cancel_foreign_task(self, engine):
        from bacmap.tasks.spec import TaskType

        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "cli:someone")
        out = _call(build_server(engine, TRUSTED), "bacmap_task_cancel", {"task_id": tid})
        assert out["code"] == "forbidden"
        assert engine.status(tid).state.value == "running"
        assert _call(build_server(engine, TRUSTED), "bacmap_task_cancel", {"task_id": "x"})[
            "code"
        ] == "not_found"

    def test_can_cancel_task_of_own_plan(self, engine):
        server = build_server(engine, TRUSTED)
        plan = _call(
            server,
            "bacmap_create_plan",
            {"tasks": [{"task_type": "analyze", "samples": ["S1"]}]},
        )
        from bacmap.application.plans import PlanService

        done = PlanService(engine, engine.db).confirm(
            plan["plan_id"], 1, plan["plan_hash"], "cli:ann"
        )
        out = _call(server, "bacmap_task_cancel", {"task_id": done.task_ids[0]})
        assert out["state"] == "cancelled"

    def test_cloud_status_withholds_message(self, engine):
        from bacmap.tasks.spec import TaskState, TaskType

        tid = engine.submit(TaskType.ANALYZE, {"samples": ["S1"]}, "x")
        engine._update_state(tid, TaskState.FAILED, "snakemake failed on S1 at /home/x")
        cloud = _call(build_server(engine), "bacmap_task_status", {"task_id": tid})
        assert cloud["state"] == "failed" and cloud["message"] == ""
        assert cloud["message_withheld"] is True
        trusted = _call(build_server(engine, TRUSTED), "bacmap_task_status", {"task_id": tid})
        assert "S1" in trusted["message"]


class TestTaskResultTool:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        rep = tmp_path / "results" / "SAM-001" / "report"
        rep.mkdir(parents=True)
        (rep / "SAM-001_summary.json").write_text(json.dumps(_sal_summary()), encoding="utf-8")
        monkeypatch.setattr(eng, "_run_snakemake", lambda params: _Proc())
        monkeypatch.setattr(eng, "_step_create_run", lambda params: {"run_id": "mcp-run-9"})
        monkeypatch.setattr(eng, "_step_finish_run", lambda run_id, params: None)
        monkeypatch.setattr(eng, "_generate_report_for", lambda s, *a: {"sample_id": s})
        monkeypatch.setattr(eng, "_memory_arbiter", _noop_arbiter)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def _finished(self, engine):
        from bacmap.tasks.spec import TaskType

        tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-001"]}, "x")
        deadline = time.time() + 30
        while time.time() < deadline and engine.status(tid).state.value == "running":
            time.sleep(0.2)
        return tid

    def test_trusted_gets_per_sample_verdicts(self, engine):
        tid = self._finished(engine)
        out = _call(build_server(engine, TRUSTED), "bacmap_task_result", {"task_id": tid})
        assert out["run_id"] == "mcp-run-9"
        assert set(out["gates"]) == {"SAM-001"}
        assert "/" not in json.dumps(out["gates"])

    def test_cloud_gets_counts_only(self, engine):
        tid = self._finished(engine)
        out = _call(build_server(engine), "bacmap_task_result", {"task_id": tid})
        assert "gates" not in out and sum(out["gate_counts"].values()) == 1
        assert "SAM-001" not in json.dumps(out)

    def test_unfinished_or_unknown(self, engine):
        out = _call(build_server(engine, TRUSTED), "bacmap_task_result", {"task_id": "nope"})
        assert out["code"] == "not_found"


class TestCapabilitiesTool:
    """v1.6.1：`bacmap_capabilities` 让客户端在调用前了解 Profile、可计划任务与 Tasks 扩展状态。"""

    def test_reports_profile_and_extension_status(self):
        out = _call(build_server(), "bacmap_capabilities", {})
        assert out["profile"] == "cloud" and out["max_data_class"] == "D1"
        assert out["plannable_task_types"] == ["analyze", "curate", "mine", "write"]
        assert out["tasks_extension"] == "unsupported_by_sdk"
        assert "bacmap_create_plan" in out["recommended_write_path"]
        assert out["bacmap_version"]

    def test_trusted_profile_reports_d4(self):
        out = _call(build_server(profile=TRUSTED), "bacmap_capabilities", {})
        assert out["profile"] == "local-trusted" and out["max_data_class"] == "D4"

    def test_available_in_read_only_mode(self):
        assert "bacmap_capabilities" in _list_tool_names(build_server())


class TestRecordDataTool:
    """自然语言数据管理（v1.8.4）：D4 Profile 下智能体可提交 record 任务。"""

    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def test_hidden_on_cloud_profile(self, engine):
        assert "bacmap_record_data" not in _list_tool_names(build_server(engine))

    def test_trusted_profile_submits_metadata(self, engine):
        server = build_server(engine, TRUSTED)
        out = _call(
            server,
            "bacmap_record_data",
            {"record": {"kind": "metadata", "strain_id": "S1",
                        "fields": {"province": "Guangdong"}}},
        )
        assert out["kind"] == "metadata" and out["task_id"]
        row = engine.list_tasks(1)[0]
        assert row["task_type"] == "record" and row["submitted_by"].startswith("mcp-")

    def test_invalid_record_rejected(self, engine):
        out = _call(
            build_server(engine, TRUSTED),
            "bacmap_record_data",
            {"record": {"kind": "metadata", "fields": {"nope": 1}}},
        )
        assert out["code"] == "validation_error"


class TestRedactedFailure:
    """v1.8.5：云端 Profile 不回传任务消息原文，但给出脱敏故障类别与处置建议。"""

    def test_cloud_gets_failure_kind_not_message(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine
        from bacmap.tasks.spec import TaskState, TaskType

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        engine = eng.DbosTaskEngine(tmp_path)
        try:
            tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-1"]}, "x")
            engine._update_state(
                tid,
                TaskState.FAILED,
                "snakemake 退出码 1：no apptainer/podman on PATH（sample SAM-1 at /home/x）",
            )
            out = _call(build_server(engine), "bacmap_task_status", {"task_id": tid})
            assert out["message"] == "" and out["message_withheld"] is True
            assert out["failure"]["kind"] == "sandbox_unavailable"
            assert "SAM-1" not in json.dumps(out["failure"], ensure_ascii=False)
            trusted = _call(
                build_server(engine, TRUSTED), "bacmap_task_status", {"task_id": tid}
            )
            assert "SAM-1" in trusted["message"]
        finally:
            eng.shutdown_dbos()

    def test_success_has_no_failure_block(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine
        from bacmap.tasks.spec import TaskState, TaskType

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        engine = eng.DbosTaskEngine(tmp_path)
        try:
            tid = engine.submit(TaskType.ANALYZE, {"samples": ["SAM-1"]}, "x")
            engine._update_state(tid, TaskState.SUCCEEDED)
            out = _call(build_server(engine), "bacmap_task_status", {"task_id": tid})
            assert out["failure"] is None
        finally:
            eng.shutdown_dbos()


class TestConfirmationChannels:
    """v1.9.0：确认链接（A）、本地弹窗（B）、低风险预授权（C）。"""

    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def _create(self, server):
        return _call(
            server,
            "bacmap_create_plan",
            {"tasks": [{"task_type": "analyze", "samples": ["S1"]}]},
        )

    def test_confirm_url_in_plan(self, engine, monkeypatch):
        monkeypatch.setenv("BACMAP_WEB_URL", "http://10.0.0.5:9000/")
        out = self._create(build_server(engine))
        assert out["confirm_url"] == (
            f"http://10.0.0.5:9000/plans/{out['plan_id']}?version=1"
        )

    def test_local_dialog_confirms(self, engine, monkeypatch):
        import bacmap.interfaces.mcp.confirm as confirm

        monkeypatch.setattr(confirm, "ask_local_confirmation", lambda prompt, timeout=120: True)
        stdio = ProfileSpec(
            profile=McpProfile.LOCAL_TRUSTED,
            max_data_class=DataClass.D4,
            actor="mcp-stdio:local-trusted:test",
        )
        server = build_server(engine, stdio)
        plan = self._create(server)
        out = _call(
            server, "bacmap_confirm_plan_locally",
            {"plan_id": plan["plan_id"], "version": 1},
        )
        assert out["state"] == "submitted"
        row = engine.list_tasks(1)[0]
        assert row["submitted_by"].startswith("local-dialog")

    def test_local_dialog_cancel_leaves_plan(self, engine, monkeypatch):
        import bacmap.interfaces.mcp.confirm as confirm

        monkeypatch.setattr(confirm, "ask_local_confirmation", lambda prompt, timeout=120: False)
        stdio = ProfileSpec(
            profile=McpProfile.LOCAL_TRUSTED,
            max_data_class=DataClass.D4,
            actor="mcp-stdio:local-trusted:test",
        )
        server = build_server(engine, stdio)
        plan = self._create(server)
        out = _call(
            server, "bacmap_confirm_plan_locally",
            {"plan_id": plan["plan_id"], "version": 1},
        )
        assert out["code"] == "conflict"
        assert engine.list_tasks(1) == []

    def test_local_dialog_only_for_stdio(self, engine, monkeypatch):
        import bacmap.interfaces.mcp.confirm as confirm

        monkeypatch.setattr(confirm, "ask_local_confirmation", lambda prompt, timeout=120: True)
        http_profile = ProfileSpec(
            profile=McpProfile.CLOUD, max_data_class=DataClass.D1, actor="mcp-http:cloud"
        )
        server = build_server(engine, http_profile)
        plan = self._create(server)
        out = _call(
            server, "bacmap_confirm_plan_locally",
            {"plan_id": plan["plan_id"], "version": 1},
        )
        assert out["code"] == "forbidden"

    def test_auto_confirm_policy(self, engine, tmp_path: Path):
        (tmp_path / "config.toml").write_text(
            "[plans.auto_confirm]\nenabled = true\nmax_samples = 5\n"
        )
        server = build_server(engine)
        out = self._create(server)
        assert out["state"] == "submitted"
        row = engine.list_tasks(1)[0]
        assert row["submitted_by"].startswith("policy:auto-confirm")

    def test_auto_confirm_skips_mine_and_large_plans(self, engine, tmp_path: Path):
        (tmp_path / "config.toml").write_text(
            "[plans.auto_confirm]\nenabled = true\nmax_samples = 1\n"
        )
        server = build_server(engine)
        mine = _call(
            server, "bacmap_create_plan",
            {"tasks": [{"task_type": "mine", "objective": "x", "script": "print(1)"}]},
        )
        assert mine["state"] == "awaiting_confirmation"
        big = _call(
            server, "bacmap_create_plan",
            {"tasks": [{"task_type": "analyze", "samples": ["S1", "S2"]}]},
        )
        assert big["state"] == "awaiting_confirmation"


class TestAutoConfirmRobustness:
    def test_malformed_policy_does_not_crash(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        (tmp_path / "config.toml").write_text(
            "[plans.auto_confirm]\nenabled = true\nmax_samples = 'many'\n"
        )
        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(tmp_path)
        try:
            out = _call(
                build_server(e), "bacmap_create_plan",
                {"tasks": [{"task_type": "analyze", "samples": ["S1"]}]},
            )
            assert out["state"] == "awaiting_confirmation"  # 配置坏 → 安全回退为需确认
        finally:
            eng.shutdown_dbos()


class TestAutoConfirmInputScope:
    def test_directory_ingestion_never_auto_confirmed(self, tmp_path: Path, monkeypatch):
        """samples=[] + fasta_dir 会绕过 max_samples，预授权必须拒绝。"""
        from bacmap.tasks.engine import task_engine

        (tmp_path / "config.toml").write_text(
            "[plans.auto_confirm]\nenabled = true\nmax_samples = 5\n"
        )
        fasta = tmp_path / "fasta"
        fasta.mkdir()
        (fasta / "S1.fna").write_text(">c\nACGT\n")
        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(tmp_path)
        try:
            out = _call(
                build_server(e),
                "bacmap_create_plan",
                {"tasks": [{"task_type": "analyze", "fasta_dir": str(fasta)}]},
            )
            assert out["state"] == "awaiting_confirmation"
        finally:
            eng.shutdown_dbos()


class TestPlanOwnership:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        from bacmap.tasks.engine import task_engine

        monkeypatch.setattr(task_engine.DBOS, "start_workflow", lambda wf, p: None)
        e = eng.DbosTaskEngine(tmp_path)
        yield e
        eng.shutdown_dbos()

    def _server(self, engine, user: str):
        return build_server(
            engine,
            ProfileSpec(
                profile=McpProfile.CLOUD,
                max_data_class=DataClass.D1,
                actor=f"mcp-stdio:cloud:{user}",
            ),
        )

    def _create(self, engine, user: str) -> str:
        out = _call(
            self._server(engine, user),
            "bacmap_create_plan",
            {"tasks": [{"task_type": "analyze", "samples": ["S1"]}]},
        )
        return out["plan_id"]

    def test_other_client_cannot_read_plan(self, engine, tmp_path: Path):
        plan_id = self._create(engine, "alice")
        out = _call(self._server(engine, "bob"), "bacmap_get_plan", {"plan_id": plan_id})
        assert out["code"] == "forbidden"
        own = _call(self._server(engine, "alice"), "bacmap_get_plan", {"plan_id": plan_id})
        assert own["plan_id"] == plan_id

    def test_other_client_cannot_revise_plan(self, engine, tmp_path: Path):
        plan_id = self._create(engine, "alice")
        out = _call(
            self._server(engine, "bob"),
            "bacmap_revise_plan",
            {
                "plan_id": plan_id,
                "tasks": [{"task_type": "analyze", "samples": ["S2"]}],
            },
        )
        assert out["code"] == "forbidden"
        latest = _call(self._server(engine, "alice"), "bacmap_get_plan", {"plan_id": plan_id})
        assert latest["version"] == 1

    def test_creator_can_revise(self, engine, tmp_path: Path):
        plan_id = self._create(engine, "alice")
        out = _call(
            self._server(engine, "alice"),
            "bacmap_revise_plan",
            {
                "plan_id": plan_id,
                "tasks": [{"task_type": "analyze", "samples": ["S2"]}],
            },
        )
        assert out["version"] == 2
