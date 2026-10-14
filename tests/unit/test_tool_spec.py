"""ToolSpec / ToolResult 契约测试（ADR-04 §4.1）。

覆盖迁移期适配器 call_legacy/parse_legacy_json——此前为未测死代码，
现作为注册表与 MCP/智能体共用的返回信封转换点锁定行为。
"""

from __future__ import annotations

from bacmap.tools.spec import ToolResult, parse_legacy_json


class TestParseLegacyJson:
    def test_ok_object(self):
        r = parse_legacy_json('{"a": 1}', "t")
        assert r.ok is True and r.data == {"a": 1}

    def test_error_payload_maps_to_failed_envelope(self):
        r = parse_legacy_json('{"error": "boom"}', "t")
        assert r.ok is False and r.error == "boom"

    def test_non_json_returns_error(self):
        r = parse_legacy_json("not json", "t")
        assert r.ok is False and "non-JSON" in (r.error or "")
        assert r.data["raw"] == "not json"

    def test_non_object_returns_error(self):
        r = parse_legacy_json("[1, 2]", "t")
        assert r.ok is False and "not an object" in (r.error or "")

    def test_trailing_raw_truncated(self):
        r = parse_legacy_json("x" * 5000, "t")
        assert len(r.data["raw"]) == 2000


class TestToolResultDefaults:
    def test_defaults(self):
        r = ToolResult(ok=True)
        assert r.data == {} and r.error is None and r.evidence == []


class TestRegistryAccessors:
    """注册表访问器（get/by_effect/by_trust_layer）与元数据完整性。"""

    def test_all_tools_registered_and_have_meta(self):
        from bacmap.tools import registry

        specs = registry.list_specs()
        assert len(specs) == 24  # 元数据缺项会被静默丢弃——此处锁死数量

    def test_get_returns_spec(self):
        from bacmap.tools import registry
        from bacmap.tools.spec import Effect

        assert registry.get("bio_seq_stats").effect == Effect.COMPUTE

    def test_by_effect_write_matches_three_write_tools(self):
        from bacmap.tools import registry
        from bacmap.tools.spec import Effect

        names = {s.name for s in registry.by_effect(Effect.WRITE)}
        assert names == {"bio_analyze_pathogen", "bio_add_metadata", "bio_add_lab_result"}

    def test_by_trust_layer_l1_non_empty(self):
        from bacmap.tools import registry
        from bacmap.tools.spec import TrustLayer

        assert registry.by_trust_layer(TrustLayer.L1)
