"""I3：isolate 注册表与传代命名（v1.8.2）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.store.isolates import IsolateService, parse_isolate_identity


class TestParseIdentity:
    def test_plain_isolate(self):
        assert parse_isolate_identity("HZCPE-01") == (None, None, None)

    def test_passage_suffix_derives_lineage(self):
        assert parse_isolate_identity("EVO-001-P037") == ("EVO-001", 37, "EVO-001")
        assert parse_isolate_identity("EVO-001-P000") == ("EVO-001", 0, "EVO-001")


class TestService:
    def test_upsert_get_list(self, tmp_path: Path):
        db = tmp_path / "data" / "bacmap.sqlite"
        svc = IsolateService(db)
        svc.ensure("EVO-001-P037")
        row = svc.get("EVO-001-P037")
        assert row is not None
        assert row["lineage_id"] == "EVO-001" and row["passage"] == 37
        assert [r["isolate_id"] for r in svc.list()] == ["EVO-001-P037"]

    def test_ensure_is_idempotent_and_keeps_explicit_lineage(self, tmp_path: Path):
        svc = IsolateService(tmp_path / "data" / "bacmap.sqlite")
        svc.ensure("S1", lineage_id="LINE-9", passage=3)
        svc.ensure("S1")
        row = svc.get("S1")
        assert row["lineage_id"] == "LINE-9" and row["passage"] == 3

    def test_unknown_returns_none(self, tmp_path: Path):
        assert IsolateService(tmp_path / "data" / "bacmap.sqlite").get("nope") is None


class TestRegistrationIntegration:
    def test_registration_creates_isolate_rows(self, tmp_path: Path):
        from bacmap.workflow.samples_registry import register_fastas

        d = tmp_path / "data"
        d.mkdir()
        (d / "EVO-001-P037__ilm.fna").write_text(">c\nACGT\n")
        register_fastas(tmp_path / "home", d, "VPA")
        row = IsolateService(tmp_path / "home" / "data" / "bacmap.sqlite").get("EVO-001-P037")
        assert row is not None and row["lineage_id"] == "EVO-001" and row["passage"] == 37


class TestCli:
    def test_ls_and_show(self, tmp_path, capsys):
        import json

        import bacmap.interfaces.cli.main as cli

        IsolateService(tmp_path / "data" / "bacmap.sqlite").ensure("EVO-001-P037")
        cli.main(["isolate", "ls", "--home", str(tmp_path), "--json"])
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["isolate_id"] == "EVO-001-P037"
        cli.main(["isolate", "show", "EVO-001-P037", "--home", str(tmp_path), "--json"])
        assert json.loads(capsys.readouterr().out)["passage"] == 37
        with pytest.raises(SystemExit, match="不存在"):
            cli.main(["isolate", "show", "nope", "--home", str(tmp_path)])
