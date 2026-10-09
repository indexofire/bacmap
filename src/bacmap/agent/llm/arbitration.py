"""资源仲裁（ADR-17：本地模型与管线同机的内存协调，V7）。

heavy_step() 上下文管理器：进入前检查可用内存，低于阈值时 POST /unload
释放 Strata（常驻 ~45G），步骤结束后 POST /load 恢复（1–3 分钟）。
co_located=false 时直通（模型在独立主机）。
确定性功能优先于 LLM（C3）：卸载只影响 LLM 可用性，不影响管线正确性。
"""

from __future__ import annotations

import contextlib
import json
import logging
import urllib.request
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)


def available_memory_gb() -> float:
    """Linux MemAvailable（/proc/meminfo），失败时返回 inf（不触发仲裁）。"""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError, IndexError):
        pass
    return float("inf")


class StrataArbiter:
    """Strata 加载态仲裁器（管理端点：/unload、/load）。"""

    def __init__(
        self,
        admin_url: str = "http://127.0.0.1:8080",
        enabled: bool = True,
        min_free_gb: float = 24.0,
        load_timeout_s: int = 300,
    ) -> None:
        self._admin_url = admin_url.rstrip("/")
        self._enabled = enabled
        self._min_free_gb = min_free_gb
        self._load_timeout_s = load_timeout_s

    def _post(self, path: str, timeout: int = 60) -> dict:
        req = urllib.request.Request(  # noqa: S310 —— 本机管理端点
            f"{self._admin_url}{path}", method="POST", data=b""
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    @contextlib.contextmanager
    def heavy_step(self) -> Iterator[None]:
        """内存密集步骤包裹器：不足则卸载模型，完成后恢复。"""
        if not self._enabled or available_memory_gb() >= self._min_free_gb:
            yield
            return
        logger.info(
            "arbitration: free %.1fG < %.1fG — unloading Strata",
            available_memory_gb(),
            self._min_free_gb,
        )
        try:
            self._post("/unload")
        except (OSError, ValueError) as exc:
            logger.warning("arbitration: unload failed (%s) — proceeding", exc)
            yield
            return
        try:
            yield
        finally:
            try:
                self._post("/load", timeout=self._load_timeout_s)
                logger.info("arbitration: Strata reloaded")
            except (OSError, ValueError) as exc:
                logger.warning("arbitration: reload failed (%s) — LLM 降级直至手动恢复", exc)
