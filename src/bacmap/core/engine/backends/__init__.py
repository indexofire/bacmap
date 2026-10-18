from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from ..registry import Registry

_REG = Registry()

_BUILTINS = {
    "blastn": ("bacmap.core.engine.backends.blast", "BlastBackend"),
    "blastp": ("bacmap.core.engine.backends.blast", "BlastBackend"),
    "blastx": ("bacmap.core.engine.backends.blast", "BlastBackend"),
    "tblastn": ("bacmap.core.engine.backends.blast", "BlastBackend"),
    "minimap2": ("bacmap.core.engine.backends.minimap2", "MinimapBackend"),
    "mash": ("bacmap.core.engine.backends.kmer", "MashBackend"),
    "sourmash": ("bacmap.core.engine.backends.kmer", "SourmashBackend"),
    "kma": ("bacmap.core.engine.backends.kma", "KmaBackend"),
    "skani": ("bacmap.core.engine.backends.skani", "SkaniBackend"),
}


def register(name: str, backend_class: Callable[..., Any]) -> None:
    _REG.register(name, backend_class)


def _ensure(name: str) -> None:
    key = (name or "").strip().lower()
    if not key or _REG.has(key):
        return
    if key in _BUILTINS:
        mod_path, attr = _BUILTINS[key]
        mod = import_module(mod_path)
        cls = getattr(mod, attr)
        register(key, cls)


def get_backend(name: str, **kwargs: Any) -> Any:
    key = (name or "").strip().lower()
    _ensure(key)
    cls = _REG.get(key)
    # blast 家族统一用 BlastBackend，但 tool 必须随请求的子命令走；否则大写/别名
    # 请求会落到默认 blastn（如 BLASTP 被当成 blastn）。
    if key in ("blastp", "blastx", "tblastn") and "tool" not in kwargs:
        kwargs["tool"] = key
    return cls(**kwargs)


def available() -> list[str]:
    names = set(_BUILTINS.keys())
    names.update(_REG.available().keys())
    return sorted(names)
