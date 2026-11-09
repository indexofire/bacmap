"""i18n 双语言变量测试（PLAN #1）：cli_language 独立于全局 language。"""

from __future__ import annotations

from pathlib import Path

from bacmap.config import system_language, ui_language


class TestLanguageResolution:
    def test_default_is_english(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("BACMAP_LANG", raising=False)
        monkeypatch.delenv("BACMAP_CLI_LANG", raising=False)
        monkeypatch.setenv("BACMAP_HOME", str(tmp_path))
        monkeypatch.setenv("BACMAP_CONFIG", str(tmp_path / "none.toml"))
        assert ui_language() == "en"
        assert system_language() == "en"

    def test_global_language_applies_to_both(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text('[ui]\nlanguage = "zh"\n', encoding="utf-8")
        monkeypatch.delenv("BACMAP_LANG", raising=False)
        monkeypatch.delenv("BACMAP_CLI_LANG", raising=False)
        monkeypatch.setenv("BACMAP_CONFIG", str(config))
        assert ui_language() == "zh"
        assert system_language() == "zh"

    def test_cli_language_overrides_only_cli(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text(
            '[ui]\nlanguage = "en"\ncli_language = "zh"\n', encoding="utf-8"
        )
        monkeypatch.delenv("BACMAP_LANG", raising=False)
        monkeypatch.delenv("BACMAP_CLI_LANG", raising=False)
        monkeypatch.setenv("BACMAP_CONFIG", str(config))
        assert ui_language() == "zh"  # CLI 用覆盖值
        assert system_language() == "en"  # 系统仍用全局值

    def test_env_cli_lang_overrides_all(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text('[ui]\nlanguage = "en"\n', encoding="utf-8")
        monkeypatch.delenv("BACMAP_LANG", raising=False)
        monkeypatch.setenv("BACMAP_CLI_LANG", "zh")
        monkeypatch.setenv("BACMAP_CONFIG", str(config))
        assert ui_language() == "zh"
        assert system_language() == "en"  # CLI 专用 env 不影响系统级

    def test_env_lang_applies_to_both(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("BACMAP_CLI_LANG", raising=False)
        monkeypatch.setenv("BACMAP_LANG", "zh")
        assert ui_language() == "zh"
        assert system_language() == "zh"

    def test_invalid_falls_back(self, tmp_path: Path, monkeypatch):
        config = tmp_path / "config.toml"
        config.write_text(
            '[ui]\nlanguage = "fr"\ncli_language = "de"\n', encoding="utf-8"
        )
        monkeypatch.delenv("BACMAP_LANG", raising=False)
        monkeypatch.delenv("BACMAP_CLI_LANG", raising=False)
        monkeypatch.setenv("BACMAP_CONFIG", str(config))
        assert ui_language() == "en"
        assert system_language() == "en"
