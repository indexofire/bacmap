"""Execution-environment helpers for engine backends.

Single implementation lives in bacmap.config; this module re-exports
it so backends can import from a local module (``from .._env import which``).
"""

from __future__ import annotations

from bacmap.config import pixi_path, which

__all__ = ["pixi_path", "which"]
