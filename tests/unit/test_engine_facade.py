"""Unit tests for the engine facade layer.

Covers:
- engine/_env.py (re-export smoke test)
- engine/registry.py (Registry class)
- engine/backends/__init__.py (lazy loading, available(), get_backend())

SequenceMatcher removed in engine/ 收缩 (v1.4.8)；ReadMapper 由
test_engine_read_mapper.py 单独覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from bacmap.core.engine import _env as env_module  # noqa: E402
from bacmap.core.engine.backends import (  # noqa: E402
    _BUILTINS,
    _REG,
    _ensure,
    available,
    get_backend,
    register,
)
from bacmap.core.engine.registry import Registry  # noqa: E402

# ===========================================================================
# _env re-exports
# ===========================================================================


class TestEnvReexports:
    def test_which_is_callable_and_returns_none_for_unknown(self):
        assert callable(env_module.which)
        assert env_module.which("nonexistent_binary_xyz_12345") is None

    def test_pixi_path_is_callable_and_returns_pathlike_string(self):
        assert callable(env_module.pixi_path)
        result = env_module.pixi_path()
        assert isinstance(result, str)
        assert ":" in result

    def test_all_exports_complete(self):
        assert set(env_module.__all__) == {"which", "pixi_path"}


# ===========================================================================
# Registry
# ===========================================================================


class TestRegistry:
    def test_register_and_get_lowercases_and_strips(self):
        r = Registry()

        def sentinel() -> int:
            return 1

        r.register("  Foo  ", sentinel)
        assert r.get("foo") is sentinel
        assert r.get("FOO") is sentinel
        assert r.get("  Foo  ") is sentinel

    def test_has_lowercases_and_strips(self):
        r = Registry()
        r.register("MyTool", lambda: 1)
        assert r.has("mytool")
        assert r.has("MYTOOL")
        assert r.has("  MyTool  ")
        assert not r.has("other")

    def test_register_empty_name_raises_valueerror(self):
        r = Registry()
        with pytest.raises(ValueError, match="name must be non-empty"):
            r.register("", lambda: 1)
        with pytest.raises(ValueError, match="name must be non-empty"):
            r.register("    ", lambda: 1)

    def test_get_missing_raises_keyerror(self):
        r = Registry()
        with pytest.raises(KeyError, match="not registered"):
            r.get("nope")

    def test_available_returns_independent_copy(self):
        r = Registry()
        r.register("foo", lambda: 1)
        avail = r.available()
        assert "foo" in avail
        avail["bar"] = lambda: 2
        assert not r.has("bar")


# ===========================================================================
# backends/__init__ lazy loading
# ===========================================================================


class TestBackendsModule:
    def test_available_includes_all_builtins_sorted(self):
        names = available()
        for builtin in _BUILTINS:
            assert builtin in names
        assert names == sorted(names)

    def test_get_backend_lazy_loads_blastn(self):
        """End-to-end smoke: get_backend('blastn') triggers BlastBackend init.
        Skips if blastn binary isn't on PATH."""
        try:
            b = get_backend("blastn")
        except RuntimeError:
            pytest.skip("blastn not on test PATH")
        assert b.__class__.__name__ == "BlastBackend"

    def test_get_backend_blastp_injects_tool_kwarg(self):
        with (
            patch.object(_REG, "has", return_value=True),
            patch.object(_REG, "get", return_value=MagicMock()) as mock_get,
        ):
            get_backend("blastp")
        mock_get.return_value.assert_called_once_with(tool="blastp")

    def test_get_backend_blastx_injects_tool_kwarg(self):
        with (
            patch.object(_REG, "has", return_value=True),
            patch.object(_REG, "get", return_value=MagicMock()) as mock_get,
        ):
            get_backend("blastx")
        mock_get.return_value.assert_called_once_with(tool="blastx")

    def test_get_backend_tblastn_injects_tool_kwarg(self):
        with (
            patch.object(_REG, "has", return_value=True),
            patch.object(_REG, "get", return_value=MagicMock()) as mock_get,
        ):
            get_backend("tblastn")
        mock_get.return_value.assert_called_once_with(tool="tblastn")

    def test_get_backend_blastn_does_not_inject_tool(self):
        with (
            patch.object(_REG, "has", return_value=True),
            patch.object(_REG, "get", return_value=MagicMock()) as mock_get,
        ):
            get_backend("blastn")
        mock_get.return_value.assert_called_once_with()

    def test_get_backend_respects_explicit_tool_kwarg(self):
        with (
            patch.object(_REG, "has", return_value=True),
            patch.object(_REG, "get", return_value=MagicMock()) as mock_get,
        ):
            get_backend("blastp", tool="diamond")
        mock_get.return_value.assert_called_once_with(tool="diamond")

    def test_get_backend_unknown_name_raises_keyerror(self):
        with pytest.raises(KeyError):
            get_backend("totally_unknown_backend_xyz")

    def test_register_then_get(self):
        class FakeBackend:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        register("custom_test_backend_xyz", FakeBackend)
        try:
            instance = get_backend("custom_test_backend_xyz")
            assert isinstance(instance, FakeBackend)
        finally:
            del _REG._store["custom_test_backend_xyz"]

    def test_get_backend_uppercase_injects_tool(self):
        """回归：大写 BLASTP 曾因未归一化而落到默认 blastn。"""
        seen: dict = {}

        class FakeBackend:
            def __init__(self, **kwargs):
                seen.update(kwargs)

        for key in ("blastn", "blastp"):
            _REG._store[key] = FakeBackend  # 覆盖懒加载，免依赖真实二进制
        try:
            get_backend("BLASTP")
            assert seen.get("tool") == "blastp"
        finally:
            for key in ("blastn", "blastp"):
                _REG._store.pop(key, None)

    def test_get_backend_case_insensitive_registered(self):
        class FakeBackend:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        register("casetest", FakeBackend)
        try:
            assert isinstance(get_backend("CaseTest"), FakeBackend)
        finally:
            del _REG._store["casetest"]

    def test_ensure_idempotent(self):
        """Calling _ensure twice keeps the same registered class."""
        _ensure("blastn")
        first = id(_REG.get("blastn"))
        _ensure("blastn")
        second = id(_REG.get("blastn"))
        assert first == second

    def test_ensure_empty_name_is_noop(self):
        before = dict(_REG._store)
        _ensure("")
        _ensure("   ")
        assert _REG._store == before
