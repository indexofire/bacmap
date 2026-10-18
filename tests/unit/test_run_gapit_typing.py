"""gapit 分型编排：多库状态（ran/no_scheme/skipped/failed）+ ecoli_dec 排除。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_run_gapit_typing", _SCRIPTS / "run_gapit_typing.py"
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
            "schema": "gapit.typing_result/1",
            "db": "lm_doumith",
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
            Path(cmd[cmd.index("-o") + 1]).write_text("#FILE\tGENE\n", encoding="utf-8")
            return _Proc(0)
        # typing <screen.tsv> -f json —— 库名从 screen 文件名推回
        db = Path(cmd[2]).name.replace("_screen.tsv", "")
        default = json.dumps(
            {"schema": "gapit.error/1", "code": "TYPING_NO_SCHEME", "message": "no scheme"}
        )
        return _Proc(0, out=typing_out.get(db, default))

    return _run


class TestRunGapitTyping:
    def test_skipped_when_gapit_missing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        out = tmp_path / "typing.json"
        assert (
            mod.run(
                tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lm_doumith"], timeout=10
            )
            == 0
        )
        data = json.loads(out.read_text())
        assert data["status"] == "skipped"
        assert data["databases"]["lm_doumith"]["status"] == "skipped"

    def test_empty_when_no_databases(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        out = tmp_path / "typing.json"
        # ecoli_dec 被专用步骤排除 → 无库可跑
        assert (
            mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["ecoli_dec"], timeout=10)
            == 0
        )
        assert json.loads(out.read_text()) == {"status": "empty", "databases": {}}

    def test_error_json_on_stderr_is_no_scheme(self, tmp_path, monkeypatch):
        """gapit typing 把 error JSON 放 stderr 且退出码非 0（实测 0.5.4 + ecoh）。"""
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        err = json.dumps(
            {"schema": "gapit.error/1", "code": "TYPING_NO_SCHEME", "message": "no scheme"}
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
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        monkeypatch.setattr(mod.subprocess, "run", _fake_run({"lm_doumith": _typing_json("IIa")}))
        out = tmp_path / "typing.json"
        mod.run(
            tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lm_doumith", "ecoh"], timeout=60
        )
        data = json.loads(out.read_text())
        assert data["status"] == "ran"
        assert data["databases"]["lm_doumith"]["status"] == "ran"
        assert data["databases"]["lm_doumith"]["schemes"] == {"doumith_serogroup": "IIa"}
        assert data["databases"]["ecoh"]["status"] == "no_scheme"

    def test_screen_failure_recorded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        monkeypatch.setattr(
            mod.subprocess, "run", _fake_run({}, screen_fail={"lm_doumith"})
        )
        out = tmp_path / "typing.json"
        mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["lm_doumith"], timeout=60)
        data = json.loads(out.read_text())
        assert data["databases"]["lm_doumith"]["status"] == "failed"
        assert data["databases"]["lm_doumith"]["stage"] == "screen"

    def test_missing_database_is_unavailable(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        err = json.dumps(
            {
                "schema": "gapit.error/1",
                "code": "DATABASE_NOT_FOUND",
                "message": "Database ab_k is not in ~/.local/share/gapit/db",
            }
        )
        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(0, out=err))
        out = tmp_path / "typing.json"
        mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", databases=["ab_k"], timeout=30)
        data = json.loads(out.read_text())
        # 缺库 ≠ 执行失败：如实记 unavailable（声明了但未 fetch）
        assert data["databases"]["ab_k"]["status"] == "unavailable"
