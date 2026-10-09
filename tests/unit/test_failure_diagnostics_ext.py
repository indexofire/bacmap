"""Extends failure_diagnostics coverage: every classify pattern, rule/exit/
file extraction, severity escalation, and diagnose_from_log over a tmp
snakemake log dir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.analysis.failure_diagnostics import (  # noqa: E402
    _PATTERNS,
    Diagnosis,
    diagnose,
    diagnose_from_log,
)


class TestDiagnosis:
    def test_summary_format_with_rule(self):
        d = Diagnosis(
            error_type="oom",
            rule_name="shovill",
            details="x" * 50,
        )
        s = d.summary
        assert s.startswith("[oom]")
        assert "rule=shovill" in s

    def test_summary_truncates_long_details(self):
        d = Diagnosis(error_type="oom", details="X" * 500)
        assert len(d.summary.split(" | ")[-1]) <= 120

    def test_summary_omits_empty_rule(self):
        d = Diagnosis(error_type="oom", details="boom")
        assert "rule=" not in d.summary

    def test_to_dict_contains_all_fields(self):
        d = Diagnosis(
            error_type="oom",
            rule_name="asm",
            details="d",
            suggested_fix="fix",
            severity="critical",
            recovery_commands=["cmd1", "cmd2"],
        )
        out = d.to_dict()
        for key in (
            "error_type",
            "rule_name",
            "details",
            "suggested_fix",
            "severity",
            "recovery_commands",
            "summary",
        ):
            assert key in out
        assert out["recovery_commands"] == ["cmd1", "cmd2"]


class TestDiagnoseEmptyAndUnknown:
    def test_empty_string_returns_empty_error_type(self):
        out = diagnose("")
        assert out.error_type == "empty"
        assert out.severity == "low"
        assert "Check .snakemake/log/" in out.suggested_fix

    def test_whitespace_only_returns_empty_error_type(self):
        out = diagnose("   \n\t  \n")
        assert out.error_type == "empty"

    def test_unknown_error_keeps_last_three_lines_as_details(self):
        stderr = "line one\nline two\nline three\nline four"
        out = diagnose(stderr)
        assert out.error_type == "unknown"
        assert "line two" in out.details
        assert "line four" in out.details
        assert len(out.details) <= 300

    def test_unknown_severity_is_medium_by_default(self):
        out = diagnose("totally unknown message")
        assert out.severity == "medium"


@pytest.mark.parametrize(
    "stderr, expected_type",
    [
        ("Error locking directory /path", "lock"),
        ("lock file exist already", "lock"),
        ("Directory cannot be locked.", "lock"),
        ("MissingInputException in rule foo", "missing_input"),
        ("Missing input files: /x.fasta", "missing_input"),
        ("ChildIOException: Child process terminated by signal 9", "oom"),
        ("RuntimeError: out of memory", "oom"),
        ("Cannot allocate memory", "oom"),
        ("MemoryError", "oom"),
        ("SIGKILL received", "oom"),
        ("bash: fastp: command not found", "missing_tool"),
        ("error: tool not installed", "missing_tool"),
        ("executable not found in PATH", "missing_tool"),
        ("Database file error: missing", "missing_db"),
        ("No volumes were created by checkm2", "missing_db"),
        ("database 'card' not found", "missing_db"),
        ("TimeoutExpired: timed out after 600 seconds", "timeout"),
        ("operation timed out", "timeout"),
        ("Error writing file: No space left on device", "disk_full"),
        ("disk full", "disk_full"),
        ("write failed: ENOSPC", "disk_full"),
        ("Permission denied: /root/x", "permission"),
        ("Operation not permitted", "permission"),
        ("TypeError in snakefile line 5", "snakemake_v8"),
        ("AttributeError in dag pipeline", "snakemake_v8"),
        ("Snakemake version 8 incompatible", "snakemake_v8"),
    ],
)
def test_all_patterns_classified(stderr, expected_type):
    out = diagnose(stderr)
    assert out.error_type == expected_type, (
        f"Expected {expected_type} for {stderr!r}, got {out.error_type}"
    )


class TestRegexBackslashBug:
    """Documents a real bug: the missing_tool / missing_db regex patterns use
    `\\.pixi`, `\\.nhr`, `\\.phr` in raw strings, which in regex means a
    literal backslash followed by any char — not the intended literal dot.
    Plain strings like "file.nhr not found" never trigger missing_db.
    """

    def test_nhr_extension_triggers_missing_db(self):
        assert diagnose("BLAST error: file.nhr not found").error_type == "missing_db"

    def test_phr_extension_triggers_missing_db(self):
        assert diagnose("file.phr not found in /data").error_type == "missing_db"

    def test_pixi_path_triggers_missing_tool(self):
        out = diagnose("No such file or directory .pixi/envs/default/bin/foo")
        assert out.error_type == "missing_tool"


class TestPatternSetSuggestedFixAndCommands:
    @pytest.mark.parametrize("err_type", [p[0] for p in _PATTERNS])
    def test_every_pattern_has_fix_and_commands(self, err_type):
        matching = [p for p in _PATTERNS if p[0] == err_type]
        assert len(matching) == 1
        _, _, details, fix, commands = matching[0]
        assert details
        assert fix
        assert isinstance(commands, list)
        assert len(commands) >= 1

    def test_lock_pattern_carries_unlock_command(self):
        out = diagnose("Error locking directory")
        assert out.error_type == "lock"
        assert "snakemake --unlock" in out.recovery_commands[0]

    def test_missing_db_carries_makeblastdb_command(self):
        out = diagnose("database 'card' not found")
        assert out.error_type == "missing_db"
        assert any("makeblastdb" in c for c in out.recovery_commands)


class TestSeverityEscalation:
    def test_oom_is_critical(self):
        assert diagnose("out of memory").severity == "critical"

    def test_disk_full_is_critical(self):
        assert diagnose("No space left on device").severity == "critical"

    def test_lock_is_high(self):
        assert diagnose("Error locking directory").severity == "high"

    def test_missing_tool_is_high(self):
        assert diagnose("fastp: command not found").severity == "high"

    def test_missing_db_is_high(self):
        assert diagnose("database 'card' not found").severity == "high"

    def test_missing_input_is_medium(self):
        assert diagnose("MissingInputException").severity == "medium"

    def test_timeout_is_medium(self):
        assert diagnose("TimeoutExpired").severity == "medium"

    def test_permission_is_medium(self):
        assert diagnose("Permission denied").severity == "medium"


class TestRuleNameExtraction:
    def test_rule_extracted_from_error_in_rule(self):
        out = diagnose("Error in rule shovill:\n  anything")
        assert out.rule_name == "shovill"

    def test_rule_extracted_from_bare_rule_token(self):
        out = diagnose("rule fastp failed:\n  command not found")
        assert out.rule_name == "fastp"

    def test_no_rule_in_stderr_leaves_empty(self):
        out = diagnose("out of memory")
        assert out.rule_name == ""


class TestExitCodeExtraction:
    def test_exit_code_appended_to_known_pattern(self):
        stderr = "Error in rule shovill:\nout of memory\nnon-zero exit status 137"
        out = diagnose(stderr)
        assert out.error_type == "oom"
        assert "exit code 137" in out.details

    def test_exit_code_survives_for_unknown_errors(self):
        out = diagnose("Error: command returned non-zero exit status 5")
        assert "exit code 5" in out.details


class TestMissingInputFileExtraction:
    def test_missing_file_appended_to_details(self):
        stderr = "MissingInputException: Missing input files for rule x: /abs/path/to/file.fasta"
        out = diagnose(stderr)
        assert out.error_type == "missing_input"
        assert "/abs/path/to/file.fasta" in out.details

    def test_missing_file_extracts_when_missing_input_pattern_triggers(self):
        stderr = (
            "Missing input files for rule assemble:\n"
            "  No such file or directory: /data/reference/card.fasta"
        )
        out = diagnose(stderr)
        assert out.error_type == "missing_input"
        assert "/data/reference/card.fasta" in out.details

    def test_file_extraction_not_added_for_other_types(self):
        stderr = "Error locking directory /some/path"
        out = diagnose(stderr)
        assert "/some/path" not in out.details


class TestDiagnoseFromLog:
    def test_missing_log_returns_no_log_diagnosis(self, tmp_path, monkeypatch):
        # Patch _PROJECT_ROOT so the fallback log dir lookup does not find
        # real Snakemake logs from the working tree.
        import bacmap.core.analysis.failure_diagnostics as fd

        monkeypatch.setattr(fd, "WORKFLOW_LOG_DIR", tmp_path / "no_such_log_dir")
        out = diagnose_from_log(str(tmp_path / "does_not_exist.log"))
        assert out.error_type == "no_log"
        assert out.severity == "low"

    def test_log_without_errors_returns_no_error(self, tmp_path):
        log = tmp_path / "trace.snakemake.log"
        log.write_text("Running rule x\nFinished successfully\n")
        out = diagnose_from_log(str(log))
        assert out.error_type == "no_error"
        assert out.severity == "low"

    def test_log_with_errors_routes_through_diagnose(self, tmp_path):
        log = tmp_path / "trace.snakemake.log"
        log.write_text(
            "Running rule x\n"
            "Error: fastp: command not found\n"
            "Exception in rule foo\n"
            "Detailed traceback follows\n"
        )
        out = diagnose_from_log(str(log))
        assert out.error_type == "missing_tool"
        assert out.rule_name == "foo"

    def test_diagnose_from_log_uses_default_snakemake_dir_when_path_missing(
        self, tmp_path, monkeypatch
    ):
        fake_root = tmp_path / "fake_project"
        log_dir = fake_root / "workflow_state" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "2024-01-01T000000Z.snakemake.log").write_text("completed normally")
        import bacmap.core.analysis.failure_diagnostics as fd

        monkeypatch.setattr(fd, "WORKFLOW_LOG_DIR", log_dir)

        out = diagnose_from_log("/nonexistent/path")
        assert out.error_type == "no_error"

    def test_diagnose_from_log_picks_latest_snakemake_log(self, tmp_path, monkeypatch):
        fake_root = tmp_path / "fake_project"
        log_dir = fake_root / "workflow_state" / "log"
        log_dir.mkdir(parents=True)
        (log_dir / "2024-01-01T000000Z.snakemake.log").write_text("nothing interesting")
        (log_dir / "2024-12-31T235959Z.snakemake.log").write_text("Error: command not found\n")
        import bacmap.core.analysis.failure_diagnostics as fd

        monkeypatch.setattr(fd, "WORKFLOW_LOG_DIR", log_dir)
        out = diagnose_from_log("/nonexistent/path")
        assert out.error_type == "missing_tool"

    def test_diagnose_from_log_handles_non_utf8_bytes(self, tmp_path):
        log = tmp_path / "weird.log"
        log.write_bytes(b"\xff\xfe Error: out of memory\n")
        out = diagnose_from_log(str(log))
        assert out.error_type == "oom"


class TestSummaryIntegration:
    def test_summary_for_classified_oom_with_rule(self):
        stderr = "Error in rule shovill:\nChildIOException signal 9"
        out = diagnose(stderr)
        assert out.error_type == "oom"
        assert out.rule_name == "shovill"
        s = out.summary
        assert s.startswith("[oom]")
        assert "rule=shovill" in s
