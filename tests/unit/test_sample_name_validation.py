"""Security tests for sample-name validation (snp.smk shell-injection guard)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "src" / "bacmap" / "tools" / "_scripts"))

from _common import validate_sample_name  # noqa: E402


class TestSampleNameValidation:
    def test_normal_identifier_passes(self):
        validate_sample_name("SAM-TYP-001")
        validate_sample_name("DEC.012")
        validate_sample_name("SHI_013")

    @pytest.mark.parametrize(
        "evil",
        [
            "evil; rm -rf /",
            "evil $(whoami)",
            "evil`id`",
            "evil | cat",
            "evil && echo hi",
            "evil\nnewline",
            "name with space",
            "a$b",
            "a>out",
            "",
        ],
    )
    def test_shell_metacharacter_names_rejected(self, evil):
        with pytest.raises(ValueError, match="unsafe sample name"):
            validate_sample_name(evil)
