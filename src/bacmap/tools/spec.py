"""工具契约（冻结设计 §4.1/§4.7，ADR-04）。

ToolSpec 是 MCP server 与内置智能体共用的唯一事实来源。
迁移期：legacy handler（dict→JSON str）经适配器转为 ToolResult；
后续逐个改写为类型化输入（input_model + typed_handler）。
"""

from __future__ import annotations

from collections.abc import Callable
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Literal, NewType

from pydantic import BaseModel, ConfigDict

TaskId = NewType("TaskId", str)


class TrustLayer(StrEnum):
    L1 = "L1"  # 固定管线：只调用，不改写
    L2 = "L2"  # 受控探索：沙箱 + 人审
    L3 = "L3"  # 自由对话：受门约束


class Effect(StrEnum):
    READ = "read"  # 只读查询
    COMPUTE = "compute"  # 计算但不写持久状态
    WRITE = "write"  # 写 GOM / 数据库，只能经由任务（ADR-07）


class DataClass(IntEnum):
    D0 = 0  # 公开知识
    D1 = 1  # 去标识聚合统计
    D2 = 2  # 单株分型结果
    D3 = 3  # 序列与比对数据
    D4 = 4  # 个人与流调可识别信息（ADR-16）


class EvidenceRef(BaseModel):
    kind: Literal["gom_object", "file"]
    object_id: str | None = None
    version: int | None = None
    path: str | None = None
    sha256: str | None = None


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = {}
    error: str | None = None
    evidence: list[EvidenceRef] = []


class ToolContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: TaskId
    role: str
    run_id: str | None = None
    workspace: Path


LegacyHandler = Callable[..., str]


class ToolSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    version: str
    description: str
    trust_layer: TrustLayer
    effect: Effect
    output_data_class: DataClass
    long_running: bool = False
    legacy_schema: dict[str, Any] | None = None
    legacy_handler: LegacyHandler | None = None
    input_model: type[BaseModel] | None = None
    typed_handler: Callable[[BaseModel, ToolContext], ToolResult] | None = None

    def call_legacy(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        """迁移期适配：legacy handler 返回 JSON str → ToolResult 信封。"""
        if self.legacy_handler is None:
            return ToolResult(ok=False, error=f"{self.name}: no legacy handler")
        raw = self.legacy_handler(args, **kwargs)
        return parse_legacy_json(raw, self.name)


def parse_legacy_json(raw: str, name: str) -> ToolResult:
    import json

    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ToolResult(
            ok=False, error=f"{name}: non-JSON legacy output", data={"raw": str(raw)[:2000]}
        )
    if not isinstance(payload, dict):
        return ToolResult(
            ok=False, error=f"{name}: legacy output is not an object", data={"raw": str(raw)[:2000]}
        )
    if "error" in payload and payload.get("error"):
        return ToolResult(ok=False, error=str(payload["error"]), data=payload)
    return ToolResult(ok=True, data=payload)
