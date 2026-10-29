"""Web 鉴权基础件（v1.9.2 巡检）：签名会话、CSRF 前置判断、站内跳转白名单。"""

from __future__ import annotations

from bacmap.interfaces.web.auth import (
    WebAuthConfig,
    issue_session,
    safe_next,
    verify_session,
)


class TestSafeNext:
    def test_internal_paths_allowed(self):
        assert safe_next("/plans/abc?version=1") == "/plans/abc?version=1"
        assert safe_next("/samples/S1") == "/samples/S1"

    def test_absolute_and_protocol_relative_rejected(self):
        assert safe_next("https://evil.example/x") == "/"
        assert safe_next("//evil.example/x") == "/"
        assert safe_next("///evil.example") == "/"

    def test_backslash_bypass_rejected(self):
        # 浏览器把 /\evil.example 当 //evil.example 处理
        assert safe_next("/\\evil.example") == "/"
        assert safe_next("/path\\to") == "/"

    def test_control_characters_rejected(self):
        assert safe_next("/ok\r\nLocation: https://evil") == "/"
        assert safe_next("/ok\0") == "/"

    def test_custom_default(self):
        assert safe_next("//evil", default="/login") == "/login"


class TestSession:
    def test_roundtrip(self):
        value = issue_session("secret", ttl=60)
        assert verify_session("secret", value)

    def test_tampered_signature_rejected(self):
        value = issue_session("secret", ttl=60)
        sid, exp, sig = value.split(".")
        assert not verify_session("secret", f"{sid}.{exp}.{sig[:-1]}0")

    def test_expired_rejected(self):
        value = issue_session("secret", ttl=-1)
        assert not verify_session("secret", value)

    def test_wrong_secret_rejected(self):
        assert not verify_session("other", issue_session("secret", ttl=60))

    def test_malformed_rejected(self):
        assert not verify_session("secret", "")
        assert not verify_session("secret", "a.b")
        assert not verify_session("secret", "a.not-int.c")


class TestAuthConfig:
    def test_derived_secret_only_when_enabled(self):
        cfg = WebAuthConfig.from_env(None, env={})
        assert cfg.enabled is False
        assert cfg.secret == ""

    def test_explicit_secret_used(self):
        cfg = WebAuthConfig.from_env("tok", env={"BACMAP_WEB_SECRET": "s3cr3t"})
        assert cfg.enabled is True and cfg.secret == "s3cr3t"
        assert cfg.cookie_ok(issue_session("s3cr3t", ttl=60))

    def test_unknown_mode_falls_back_to_bearer(self):
        cfg = WebAuthConfig.from_env("tok", env={"BACMAP_WEB_AUTH": "cokie"})
        assert cfg.mode == "bearer"
