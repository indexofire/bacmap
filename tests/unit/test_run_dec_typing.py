"""DEC 致病型适配器（gapit ecoli_dec）：守卫 + 两段调用 + 失败留痕。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_run_dec_typing", _SCRIPTS / "run_dec_typing.py"
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


_TYPING = json.dumps(
    {
        "schema": "gapit.typing_result/1",
        "db": "ecoli_dec",
        "files": [
            {
                "file": "c.fasta",
                "genes": ["escV"],
                "phenotypes": {"gb4789_6": {"phenotype": "EPEC_atypical"}},
            }
        ],
    }
)


class TestRunDecTyping:
    def test_skipped_when_gapit_missing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        out = tmp_path / "pathotype.json"
        assert mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", db="ecoli_dec", timeout=10) == 0
        assert json.loads(out.read_text())["status"] == "skipped"

    def test_ran_screen_then_typing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        calls: list[list[str]] = []

        def fake_run(cmd, capture_output=True, text=True, timeout=None):
            calls.append(cmd)
            if "screen" in cmd:
                Path(cmd[cmd.index("-o") + 1]).write_text("#FILE\tGENE\n", encoding="utf-8")
                return _Proc(0)
            return _Proc(0, out=_TYPING)

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        out = tmp_path / "pathotype.json"
        assert mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", db="ecoli_dec", timeout=60) == 0
        data = json.loads(out.read_text())
        assert data["status"] == "ran"
        assert data["db"] == "ecoli_dec"
        assert [c[1] for c in calls] == ["screen", "typing"]

    def test_screen_failure_recorded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")
        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc(2, err="no hits"))
        out = tmp_path / "pathotype.json"
        assert mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", db="ecoli_dec", timeout=60) == 0
        data = json.loads(out.read_text())
        assert data["status"] == "failed" and data["stage"] == "screen"

    def test_typing_non_json_recorded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/gapit")

        def fake_run(cmd, capture_output=True, text=True, timeout=None):
            if "screen" in cmd:
                Path(cmd[cmd.index("-o") + 1]).write_text("#x\n", encoding="utf-8")
                return _Proc(0)
            return _Proc(0, out="not json")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        out = tmp_path / "pathotype.json"
        assert mod.run(tmp_path / "c.fasta", out, tmp_path / "wd", db="ecoli_dec", timeout=60) == 0
        assert json.loads(out.read_text())["stage"] == "typing"
