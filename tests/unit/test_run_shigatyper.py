"""run_shigatyper.py：ShigaTyper 适配（状态如实：ran / not_shigella / unavailable / failed）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_run_shigatyper", _SCRIPTS / "run_shigatyper.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestSummarizeRow:
    def test_shigella_prediction(self):
        mod = _load()
        out = mod.summarize_row(
            {"sample": "S1", "prediction": "Shigella sonnei", "ipaB": "+", "notes": "ok"}
        )
        assert out["status"] == "ran"
        assert out["species"] == "Shigella sonnei"
        assert out["serotype"] == "Shigella sonnei"
        assert out["ipaB"] == "+"

    def test_not_shigella_is_not_a_failure(self):
        mod = _load()
        out = mod.summarize_row(
            {"prediction": "Not Shigella or EIEC", "ipaB": "-", "notes": "ipaH-"}
        )
        assert out["status"] == "not_shigella"
        assert out["serotype"] == "N/A"

    def test_empty_prediction_is_failed(self):
        mod = _load()
        assert mod.summarize_row({})["status"] == "failed"

    def test_unexpected_text_is_failed_not_guessed(self):
        mod = _load()
        out = mod.summarize_row({"prediction": "Escherichia coli"})
        assert out["status"] == "failed"
        assert "未识别" in out["notes"]


class TestRun:
    def test_unavailable_without_tool(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        out = tmp_path / "o.json"
        assert mod.run(tmp_path / "r1", tmp_path / "r2", "S1", out, tmp_path / "wd") == 0
        data = json.loads(out.read_text())
        assert data["status"] == "unavailable"
        assert data["engine"] == "shigatyper"

    def test_ran_parses_tsv(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/shigatyper")
        monkeypatch.setattr(mod, "_tool_version", lambda tool: "2.0.5")

        def fake_run(cmd, **kwargs):
            outdir = Path(cmd[cmd.index("-o") + 1])
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "S1.tsv").write_text(
                "sample\tprediction\tipaB\tnotes\nS1\tShigella flexneri 2a\t+\tok\n",
                encoding="utf-8",
            )
            return mod.subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        out = tmp_path / "o.json"
        mod.run(tmp_path / "r1", tmp_path / "r2", "S1", out, tmp_path / "wd")
        data = json.loads(out.read_text())
        assert data["status"] == "ran"
        assert data["serotype"] == "Shigella flexneri 2a"
        assert data["version"] == "2.0.5"

    def test_failure_records_stderr(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/shigatyper")
        monkeypatch.setattr(mod, "_tool_version", lambda tool: "2.0.5")

        def fake_run(cmd, **kwargs):
            return mod.subprocess.CompletedProcess(cmd, 1, "", "boom")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        out = tmp_path / "o.json"
        mod.run(tmp_path / "r1", tmp_path / "r2", "S1", out, tmp_path / "wd")
        data = json.loads(out.read_text())
        assert data["status"] == "failed"
        assert "boom" in data["notes"]
