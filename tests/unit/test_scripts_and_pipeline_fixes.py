"""工具/脚本层审计修复的回归测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(_SRC / "bacmap" / "tools" / "_scripts"))


def _summary(sample: str, steps: dict) -> dict:
    return {"sample": sample, "steps": steps}


def _write(results: Path, sample: str, steps: dict) -> None:
    d = results / sample / "report"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sample}_summary.json").write_text(json.dumps(_summary(sample, steps)))


@pytest.fixture
def results(tmp_path, monkeypatch):
    from bacmap.tools import pipeline as tools_pipeline

    r = tmp_path / "results"
    r.mkdir()
    monkeypatch.setattr(tools_pipeline, "_RESULTS_DIR", r)
    monkeypatch.setattr(tools_pipeline, "_run_project_script", lambda *a, **k: "ok")
    return r


class TestGetResultSpeciesKeys:
    def test_real_summary_species_key(self, results):
        from bacmap.tools.pipeline import get_result

        # 真实 summary 用 steps.species.species（非 verdict）
        _write(results, "S1", {"species": {"species": "Salmonella"}})
        out = json.loads(get_result({"sample_id": "S1"}))
        assert out["species_verdict"] == "Salmonella"
        assert out["species_type"] == "Salmonella"

    def test_common_pathogen_species_type(self, results):
        from bacmap.tools.pipeline import get_result

        _write(results, "K1", {"species": {"species": "Klebsiella_pneumoniae"}})
        out = json.loads(get_result({"sample_id": "K1"}))
        assert out["species_type"] == "Klebsiella pneumoniae"

    def test_non_dict_plasmid_tolerated(self, results):
        from bacmap.tools.pipeline import get_result

        _write(results, "P1", {"species": {"species": "Salmonella"}, "plasmid": "N/A"})
        out = json.loads(get_result({"sample_id": "P1"}))
        assert out["plasmid_count"] == 0


class TestReportValidationAndErrors:
    def test_generate_report_rejects_traversal(self, results):
        from bacmap.tools.pipeline import generate_report

        out = json.loads(generate_report({"sample_id": "../../etc/passwd"}))
        assert "invalid sample_id" in out["error"]

    def test_pipeline_surfaces_script_error(self, results, monkeypatch):
        from bacmap.tools import pipeline as p

        monkeypatch.setattr(
            p, "_run_project_script", lambda *a, **k: json.dumps({"error": "boom", "stderr": "x"})
        )
        out = json.loads(p.analyze_pathogen({"sample_id": "S1"}))
        assert out["error"] == "Pipeline failed" and "boom" in out["detail"]


class TestWorkflowDirBase:
    def test_scripts_common_uses_config_dir(self):
        import _common as scripts_common  # noqa: N812

        from bacmap import config

        assert scripts_common.WORKFLOW_DIR == config.DEPLOYED_WORKFLOWS_DIR


class TestRunAnalysisCli:
    def _load(self):
        path = _SRC / "bacmap" / "tools" / "_scripts" / "run_analysis.py"
        spec = importlib.util.spec_from_file_location("run_analysis", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod

    def test_status_with_sample_parses(self, tmp_path, monkeypatch, capsys):
        mod = self._load()
        wf = tmp_path / "wf"
        (wf / "config").mkdir(parents=True)
        (wf / "config" / "samples.tsv").write_text("sample\tspecies\nS1\tSalmonella\n")
        monkeypatch.setattr(mod, "WORKFLOW_DIR", wf)
        monkeypatch.setattr(mod, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(sys, "argv", ["run_analysis.py", "--status", "--sample", "S1"])
        assert mod.main() == 0
        assert "分析状态" in capsys.readouterr().out

    def test_no_action_errors(self, tmp_path, monkeypatch):
        mod = self._load()
        monkeypatch.setattr(sys, "argv", ["run_analysis.py"])
        with pytest.raises(SystemExit):
            mod.main()
