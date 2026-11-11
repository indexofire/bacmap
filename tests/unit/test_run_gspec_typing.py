"""gspec 分型编排：多库状态（ran/no_scheme/skipped/failed）+ eco_dec 排除。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_run_gspec_typing", _SCRIPTS / "run_gspec_typing.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _Proc:
    def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _typing_json(phenotype: str = "IIa") -> str:
    return json.dumps(
        {
            "schema": "gspec.typing_result/1",
            "db": "lmo_sero",
            "files": [
                {
                    "file": "c.fasta",
                    "genes": ["lmo0737"],
                    "phenotypes": {
                        "doumith_serogroup": {"phenotype": phenotype, "confidence": "high"}
                    },
                }
            ],
        }
    )


def _fake_run(typing_out: dict[str, str], *, screen_fail: set[str] | None = None):
    def _run(cmd, capture_output=True, text=True, timeout=None):
        if "screen" in cmd:
            db = cmd[cmd.index("--db") + 1]
            if screen_fail and db in screen_fail:
                return _Proc(2, err=f"{db} screen failed")
            # v1.10.21：screen 产物为 gspec.report/1 JSON（typing 表由其派生）
            Path(cmd[cmd.index("-o") + 1]).write_text(
                json.dumps({"schema": "gspec.report/1", "tool": {"name": "gspec"}, "files": []}),
                encoding="utf-8",
            )
            return _Proc(0)
        # typing <派生临时表> -f json —— 库名从临时表前缀（<db>_screen_）推回
        import re

        m = re.match(r"(.+)_screen_", Path(cmd[2]).name)
        db = m.group(1) if m else Path(cmd[2]).stem
        default = json.dumps(
            {"schema": "gspec.error/1", "code": "TYPING_NO_SCHEME", "message": "no scheme"}
        )
        return _Proc(0, out=typing_out.get(db, default))

    return _run


class TestRunGspecTyping:
    def test_skipped_when_gspec_missing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        out = tmp_path / "typing.json"
        assert (
            mod.run(
                tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lmo_sero"], timeout=10
            )
            == 0
        )
        data = json.loads(out.read_text())
        assert data["status"] == "skipped"
        assert data["databases"]["lmo_sero"]["status"] == "skipped"

    def test_empty_when_no_databases(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        out = tmp_path / "typing.json"
        # eco_dec 被专用步骤排除 → 无库可跑
        assert (
            mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["eco_dec"], timeout=10)
            == 0
        )
        assert json.loads(out.read_text()) == {"status": "empty", "databases": {}}

    def test_error_json_on_stderr_is_no_scheme(self, tmp_path, monkeypatch):
        """gspec typing 把 error JSON 放 stderr 且退出码非 0（实测 0.5.4 + ecoh）。"""
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        err = json.dumps(
            {"schema": "gspec.error/1", "code": "TYPING_NO_SCHEME", "message": "no scheme"}
        )

        def _run(cmd, **kwargs):
            if "screen" in cmd:
                Path(cmd[cmd.index("-o") + 1]).write_text("#FILE\tGENE\n", encoding="utf-8")
                return _Proc(0)
            return _Proc(1, out="", err=err)

        monkeypatch.setattr(mod.subprocess, "run", _run)
        out = tmp_path / "typing.json"
        mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["ecoh"], timeout=30)
        data = json.loads(out.read_text())
        # 无 scheme 是能力未就绪，不是执行失败
        assert data["databases"]["ecoh"]["status"] == "no_scheme"

    def test_ran_and_no_scheme_mixed(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        monkeypatch.setattr(mod.subprocess, "run", _fake_run({"lmo_sero": _typing_json("IIa")}))
        out = tmp_path / "typing.json"
        mod.run(
            tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lmo_sero", "ecoh"], timeout=60
        )
        data = json.loads(out.read_text())
        assert data["status"] == "ran"
        assert data["databases"]["lmo_sero"]["status"] == "ran"
        assert data["databases"]["lmo_sero"]["schemes"] == {"doumith_serogroup": "IIa"}
        assert data["databases"]["ecoh"]["status"] == "no_scheme"

    def test_screen_failure_recorded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        monkeypatch.setattr(
            mod.subprocess, "run", _fake_run({}, screen_fail={"lmo_sero"})
        )
        out = tmp_path / "typing.json"
        mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lmo_sero"], timeout=60)
        data = json.loads(out.read_text())
        assert data["databases"]["lmo_sero"]["status"] == "failed"
        assert data["databases"]["lmo_sero"]["stage"] == "screen"

    def test_missing_database_is_unavailable(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        err = json.dumps(
            {
                "schema": "gspec.error/1",
                "code": "DATABASE_NOT_FOUND",
                "message": "Database ab_k is not in ~/.local/share/gspec/db",
            }
        )
        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(0, out=err))
        out = tmp_path / "typing.json"
        mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["ab_k"], timeout=30)
        data = json.loads(out.read_text())
        # 缺库 ≠ 执行失败：如实记 unavailable（声明了但未 fetch）
        assert data["databases"]["ab_k"]["status"] == "unavailable"


class TestSpeciesRouting:
    def _species(self, tmp_path: Path, verdict: str = "V_parahaemolyticus",
                 confidence: str = "high") -> Path:
        p = tmp_path / "species_id.json"
        p.write_text(
            json.dumps({"species": verdict, "confidence": confidence}), encoding="utf-8"
        )
        return p

    def _selection(self, tmp_path: Path, databases: list[str]) -> Path:
        p = tmp_path / "db_selection.yaml"
        p.write_text(
            "schema: bacmap.db_selection/1\n"
            "species:\n"
            "  VPA:\n"
            "    mode: replace\n"
            "    databases:\n"
            + "".join(f"    - {db}\n" for db in databases),
            encoding="utf-8",
        )
        return p

    def _catalog(self):
        from bacmap.core.tool_selection_validate import DbCatalogEntry

        return {
            "vpa_ok": DbCatalogEntry(
                name="vpa_ok", kind="cluster", typing=True, installed=True, source="bundled"
            ),
            "vpa_pai": DbCatalogEntry(
                name="vpa_pai", kind="cluster", typing=False, installed=True, source="bundled"
            ),
        }

    def test_species_and_selection_drive_cluster_screens(self, tmp_path, monkeypatch):
        mod = _load()
        calls: list[list[str]] = []

        cluster_doc = {
            "schema": "gspec.cluster/2",
            "files": [
                {
                    "file": "c.fasta",
                    "best": {"locus": "OL3", "type": "O3"},
                    "phenotypes": {
                        "o_group": {"phenotype": "O3", "confidence": "high"},
                        "k_group": {"phenotype": "K6", "confidence": "high"},
                        "serotype": {"phenotype": "O3:K6", "confidence": "high"},
                    },
                    "loci": [{"locus": "OL3"}],
                }
            ],
        }

        def _run(cmd, **kwargs):
            calls.append(list(cmd))
            assert "screen" in cmd
            assert "--format" in cmd and cmd[cmd.index("--format") + 1] == "json"
            Path(cmd[cmd.index("-o") + 1]).write_text(
                json.dumps(cluster_doc), encoding="utf-8"
            )
            return _Proc(0)

        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        monkeypatch.setattr(mod, "_catalog", lambda datadir: self._catalog())
        monkeypatch.setattr(mod.subprocess, "run", _run)

        out = tmp_path / "typing.json"
        mod.run(
            tmp_path / "c.fasta",
            out,
            tmp_path / "wd",
            databases=[],
            timeout=30,
            species_json=self._species(tmp_path),
            sample="S1",
            selection_path=self._selection(tmp_path, ["vpa_ok", "vpa_pai"]),
        )
        data = json.loads(out.read_text())
        assert data["species"]["code"] == "VPA"
        assert data["databases"]["vpa_ok"]["status"] == "ran"
        assert data["databases"]["vpa_ok"]["phenotype"] == "O3:K6"
        assert data["databases"]["vpa_pai"]["status"] == "ran"
        # cluster 库绝不走 gspec typing
        assert all("typing" not in call for call in calls)

    def test_low_confidence_routes_no_species_databases(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        monkeypatch.setattr(mod, "_catalog", lambda datadir: self._catalog())
        monkeypatch.setattr(
            mod.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
        )
        out = tmp_path / "typing.json"
        mod.run(
            tmp_path / "c.fasta",
            out,
            tmp_path / "wd",
            databases=["vpa_ok"],  # samples.tsv fallback must NOT be used
            timeout=30,
            species_json=self._species(tmp_path, confidence="low"),
            sample="S1",
            selection_path=self._selection(tmp_path, ["vpa_ok"]),
        )
        data = json.loads(out.read_text())
        assert data["status"] == "empty"
        assert data["databases"] == {}
        assert data["species"]["confidence"] == "low"

    def test_unk_fallback_selection_runs(self, tmp_path, monkeypatch):
        mod = _load()
        calls: list[list[str]] = []

        def _run(cmd, **kwargs):
            calls.append(list(cmd))
            Path(cmd[cmd.index("-o") + 1]).write_text(
                json.dumps({"schema": "gspec.cluster/2", "files": [{"best": {}, "loci": []}]}),
                encoding="utf-8",
            )
            return _Proc(0)

        selection = tmp_path / "db_selection.yaml"
        selection.write_text(
            "schema: bacmap.db_selection/1\n"
            "species:\n"
            "  UNK:\n"
            "    databases: [vpa_ok]\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gspec")
        monkeypatch.setattr(mod, "_catalog", lambda datadir: self._catalog())
        monkeypatch.setattr(mod.subprocess, "run", _run)
        out = tmp_path / "typing.json"
        mod.run(
            tmp_path / "c.fasta",
            out,
            tmp_path / "wd",
            databases=[],
            timeout=30,
            species_json=self._species(tmp_path, verdict="Unknown", confidence="low"),
            sample="S1",
            selection_path=selection,
        )
        data = json.loads(out.read_text())
        assert data["species"]["code"] == "UNK"
        assert data["databases"]["vpa_ok"]["status"] == "ran"
        assert calls
