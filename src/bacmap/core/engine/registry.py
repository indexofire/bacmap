from __future__ import annotations

from collections.abc import Callable
from typing import Any


class Registry:
    """Name → callable registry with lowercase keys and lazy loading."""

    def __init__(self) -> None:
        self._store: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, func: Callable[..., Any]) -> None:
        key = (name or "").strip().lower()
        if not key:
            raise ValueError("Registry.register: name must be non-empty")
        self._store[key] = func

    def get(self, name: str) -> Callable[..., Any]:
        key = (name or "").strip().lower()
        if key not in self._store:
            raise KeyError(f"Registry: '{name}' is not registered")
        return self._store[key]

    def available(self) -> dict[str, Callable[..., Any]]:
        return dict(self._store)

    def has(self, name: str) -> bool:
        return (name or "").strip().lower() in self._store
