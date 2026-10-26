"""A+B+D 回归测试：数据登记（零拷贝 + SHA256）、沙箱只读挂载与 fs_scope、
bio_inspect_dataset、mine.input_paths、sandbox_run.datasets。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import bacmap.tasks.engine.dbos_engine as eng
from bacmap.agent.sandbox import SandboxSpec
from bacmap.agent.sandbox.access import allowed_roots, build_access
from bacmap.store.datasets import DatasetRegistry
from bacmap.tasks.spec import TaskState, TaskType
from bacmap.tools import services as tools_services


class _Proc:
    def __init__(self, rc: int) -> None:
        self.returncode = rc


class _FakeSandboxResult:
    def __init__(self, rc: int = 0) -> None:
        self.returncode = rc
        self.stdout = ""
        self.stderr = ""
        self.backend = "fake"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "userdata"
    d.mkdir()
    (d / "a.txt").write_text("alpha", encoding="utf-8")
    (d / "b.txt").write_text("beta", encoding="utf-8")
    return d


class TestDatasetRegistry:
    def test_register_dir_and_sha256(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            ds = reg.register(data_dir, registered_by="tester")
            assert ds.kind == "dir"
            assert ds.total_size == 9  # "alpha" + "beta"
            assert len(ds.entries) == 2
            assert all(e["sha256"] for e in ds.entries)
            assert ds.mount_guest == f"/input/{ds.dataset_id}"
            assert reg.mount_map(ds.dataset_id) == {ds.resolved_path: ds.mount_guest}
        finally:
            reg.close()

    def test_register_file(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            ds = reg.register(data_dir / "a.txt", registered_by="tester")
            assert ds.kind == "file"
            assert ds.mount_guest.endswith("/a.txt")
        finally:
            reg.close()

    def test_content_dedup(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            d1 = reg.register(data_dir, registered_by="a")
            d2 = reg.register(data_dir, registered_by="b")
            assert d1.dataset_id == d2.dataset_id
            assert len(reg.list_all()) == 1
        finally:
            reg.close()

    def test_verify_detects_change_and_missing(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            ds = reg.register(data_dir, registered_by="tester")
            assert reg.verify(ds.dataset_id) is True
            (data_dir / "a.txt").write_text("ALPHA", encoding="utf-8")
            assert reg.verify(ds.dataset_id) is False
            assert reg.get(ds.dataset_id).status == "changed"
            import shutil

            shutil.rmtree(data_dir)
            assert reg.verify(ds.dataset_id) is False
            assert reg.get(ds.dataset_id).status == "missing"
        finally:
            reg.close()

    def test_register_missing_path_raises(self, tmp_path: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            with pytest.raises(FileNotFoundError):
                reg.register(tmp_path / "nope", registered_by="t")
        finally:
            reg.close()


class TestInspectDatasetTool:
    def _register(self, gom_db: Path, data_dir: Path) -> str:
        reg = DatasetRegistry(gom_db)
        try:
            return reg.register(data_dir, registered_by="tester").dataset_id
        finally:
            reg.close()

    def test_list_and_detail(self, tmp_path: Path, data_dir: Path, monkeypatch):
        gom_db = tmp_path / "gom.sqlite"
        did = self._register(gom_db, data_dir)
        monkeypatch.setattr(tools_services, "_GOM_DB", gom_db)

        listing = json.loads(tools_services.inspect_dataset({}))
        assert listing["count"] == 1
        assert listing["datasets"][0]["dataset_id"] == did

        detail = json.loads(tools_services.inspect_dataset({"dataset_id": did}))
        assert detail["dataset_id"] == did
        assert detail["n_entries"] == 2
        assert detail["mount"].startswith("/input/")

    def test_unknown_id(self, tmp_path: Path, monkeypatch):
        gom_db = tmp_path / "gom.sqlite"
        DatasetRegistry(gom_db).close()
        monkeypatch.setattr(tools_services, "_GOM_DB", gom_db)
        out = json.loads(tools_services.inspect_dataset({"dataset_id": "ds-nope"}))
        assert "error" in out

    def test_no_db(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_path / "missing.sqlite")
        out = json.loads(tools_services.inspect_dataset({}))
        assert out["count"] == 0


class TestSandboxScope:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        return ws

    def test_mounts_require_allowlist(self, tmp_path: Path):
        with pytest.raises(ValueError, match="allowed_readonly_roots"):
            SandboxSpec(
                image="i",
                command=["x"],
                workspace=self._ws(tmp_path),
                readonly_mounts={"/etc/passwd": "/x"},
            )

    def test_mount_outside_allowlist_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="越权"):
            SandboxSpec(
                image="i",
                command=["x"],
                workspace=self._ws(tmp_path),
                readonly_mounts={"/etc/passwd": "/x"},
                allowed_readonly_roots=(tmp_path / "allowed",),
            )

    def test_mount_within_allowlist_ok(self, tmp_path: Path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        spec = SandboxSpec(
            image="i",
            command=["x"],
            workspace=self._ws(tmp_path),
            readonly_mounts={str(allowed): "/data"},
            allowed_readonly_roots=(allowed,),
        )
        assert spec.readonly_mounts == {str(allowed): "/data"}


class TestBuildAccess:
    def test_container_uses_guest_paths(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            ds = reg.register(data_dir, registered_by="t")
        finally:
            reg.close()
        results = tmp_path / "results"
        results.mkdir()
        gom = tmp_path / "gom.sqlite"
        mounts, ctx = build_access(
            "apptainer", results_dir=results, gom_db=gom, datasets=[ds]
        )
        assert mounts[str(results)] == "/data/results"
        assert mounts[str(gom)] == "/data/gom.sqlite"
        assert ctx["datasets"][ds.dataset_id] == ds.mount_guest
        assert set(allowed_roots(results_dir=results, gom_db=gom, datasets=[ds])) >= {
            results,
            gom,
            Path(ds.resolved_path),
        }

    def test_direct_uses_host_paths(self, tmp_path: Path, data_dir: Path):
        reg = DatasetRegistry(tmp_path / "gom.sqlite")
        try:
            ds = reg.register(data_dir, registered_by="t")
        finally:
            reg.close()
        results = tmp_path / "results"
        results.mkdir()
        mounts, ctx = build_access(
            "direct", results_dir=results, gom_db=tmp_path / "gom.sqlite", datasets=[ds]
        )
        assert mounts == {}
        assert ctx["results_dir"] == str(results)
        assert ctx["datasets"][ds.dataset_id] == ds.resolved_path


# ---------------------------------------------------------------------------
# mine.input_paths / sandbox_run.datasets 端到端
# ---------------------------------------------------------------------------


class TestMineInputPaths:
    @pytest.fixture
    def engine(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(eng, "_run_sandbox", lambda spec: _FakeSandboxResult(0))
        monkeypatch.setattr(eng, "_sandbox_backend_name", lambda: "apptainer")
        captured: dict = {}
        orig = eng._build_sandbox_spec

        def _capture(*a, **k):
            spec = orig(*a, **k)
            captured["spec"] = spec
            return spec

        monkeypatch.setattr(eng, "_build_sandbox_spec", _capture)
        e = eng.DbosTaskEngine(tmp_path)
        e._captured = captured  # type: ignore[attr-defined]
        yield e
        eng.shutdown_dbos()

    def _wait(self, e, tid: str, timeout_s: float = 30.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = e.status(tid)
            if st.state != TaskState.RUNNING:
                return st
            time.sleep(0.2)
        return e.status(tid)

    def test_registers_and_mounts_input_paths(self, engine, tmp_path, data_dir, monkeypatch):
        monkeypatch.setattr(tools_services, "_GOM_DB", tmp_path / "gom.sqlite")
        tid = engine.submit(
            TaskType.MINE,
            {"script": "pass", "input_paths": [str(data_dir)]},
            "analyst",
        )
        self._wait(engine, tid)

        # 数据集已登记（零拷贝）
        with DatasetRegistry(tmp_path / "gom.sqlite") as reg:
            datasets = reg.list_all()
        assert len(datasets) == 1
        ds = datasets[0]
        assert ds.registered_by == "analyst"
        assert ds.resolved_path == str(data_dir.resolve())

        # 沙箱 spec 只读挂载了该数据（guest 路径 /input/<id>）且白名单放行
        spec = engine._captured["spec"]  # type: ignore[attr-defined]
        assert spec.readonly_mounts[ds.resolved_path] == ds.mount_guest
        assert ds.resolved_path in {str(p) for p in spec.allowed_readonly_roots}

        # 只读工具可见
        out = json.loads(tools_services.inspect_dataset({"dataset_id": ds.dataset_id}))
        assert out["dataset_id"] == ds.dataset_id

    def test_no_input_paths_no_dataset(self, engine, tmp_path):
        tid = engine.submit(TaskType.MINE, {"script": "pass"}, "analyst")
        self._wait(engine, tid)
        with DatasetRegistry(tmp_path / "gom.sqlite") as reg:
            assert reg.list_all() == []


