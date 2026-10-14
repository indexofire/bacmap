"""Tests for analysis modules — species_identifier, failure_diagnostics, genome_annotator."""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.failure_diagnostics import diagnose  # noqa: E402


class TestFailureDiagnosticsLoopLeak:
    def test_diagnose_returns_result_on_unknown_error(self):
        result = diagnose(
            stderr="some completely unknown error pattern zzz",
        )
        assert result is not None
        assert result.error_type is not None

    def test_diagnose_missing_input_adds_file_detail(self):
        result = diagnose(
            stderr="Error: Missing input files: /path/to/missing.fasta",
        )
        assert result.error_type == "missing_input"
        assert "/path/to/missing.fasta" in result.details



class TestFailureDiagnosticsAbsolutePath:
    def test_log_dir_comes_from_config(self):
        import inspect

        from bacmap.core.analysis import failure_diagnostics

        # ADR-03：日志目录来自 config（BACMAP_HOME），不由源码位置推导。
        src = inspect.getsource(failure_diagnostics.diagnose_from_log)
        assert "WORKFLOW_LOG_DIR" in src
        assert "parents[" not in src
        assert "_PROJECT_ROOT" not in src
