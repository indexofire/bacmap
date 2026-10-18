"""重组检测适配器（Gubbins）：工具缺失不静默、GFF 解析、失败留痕。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "bacmap" / "workflow" / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_wf_run_recombination", _SCRIPTS / "run_recombination.py"
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


class TestRunRecombination:
    def test_skipped_when_tool_missing(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        out = tmp_path / "recombination.json"
        rc = mod.run(tmp_path / "a.fasta", out, tmp_path / "wd", threads=1, seed=1, timeout=10)
        assert rc == 0
        data = json.loads(out.read_text())
        assert data["status"] == "skipped"
        assert "gubbins" in data["reason"]

    def test_ran_parses_predictions(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/run_gubbins.py")

        def fake_run(cmd, capture_output=True, text=True, timeout=None):
            if "--version" in cmd:
                return _Proc(0, out="Version: 3.4.3")
            prefix = Path(cmd[cmd.index("--prefix") + 1])
            Path(f"{prefix}.recombination_predictions.gff").write_text(
                "##gff-version 3\nA\t1\t1\nB\t2\t2\n", encoding="utf-8"
            )
            Path(f"{prefix}.node_labelled.final_tree.tre").write_text("(A,B);", encoding="utf-8")
            return _Proc(0)

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        out = tmp_path / "recombination.json"
        assert (
            mod.run(tmp_path / "a.fasta", out, tmp_path / "wd", threads=4, seed=42, timeout=60)
            == 0
        )
        data = json.loads(out.read_text())
        assert data["status"] == "ran"
        assert data["n_recombinations"] == 2
        assert data["final_tree"].endswith(".final_tree.tre")

    def test_failure_is_recorded(self, tmp_path, monkeypatch):
        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/run_gubbins.py")
        monkeypatch.setattr(
            mod.subprocess, "run", lambda *a, **k: _Proc(1, err="boom: tree building failed")
        )
        out = tmp_path / "recombination.json"
        assert (
            mod.run(tmp_path / "a.fasta", out, tmp_path / "wd", threads=1, seed=1, timeout=60) == 0
        )
        data = json.loads(out.read_text())
        assert data["status"] == "failed"
        assert "boom" in data["error"]

    def test_timeout_is_recorded(self, tmp_path, monkeypatch):
        import subprocess as sp

        mod = _load()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/run_gubbins.py")

        def boom(*a, **k):
            raise sp.TimeoutExpired(cmd="gubbins", timeout=1)

        monkeypatch.setattr(mod.subprocess, "run", boom)
        out = tmp_path / "recombination.json"
        assert (
            mod.run(tmp_path / "a.fasta", out, tmp_path / "wd", threads=1, seed=1, timeout=1) == 0
        )
        assert json.loads(out.read_text())["status"] == "failed"
