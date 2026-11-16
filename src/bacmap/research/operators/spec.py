"""研究编排层：算子契约与注册表（P1）。

算子（operator）= 有类型输入/输出、可校验参数、声明数据级别与资源的计算单元。
注册表以代码为唯一事实来源；``catalog()`` 导出 JSON（含参数 JSON Schema），
供计划器与 Web 计划预览消费。

不变量：
- 算子名 ``<area>.<verb>``，版本 semver；``ref = name@version`` 唯一。
- 端口类型必须属于 :class:`PortType`；执行器据此做计划期类型校验。
- ``data_class`` 是输入的最高数据级别（ADR-16）；执行器不得把更高级别数据
  喂给声明更低的算子。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class PortType(StrEnum):
    """算子端口类型（计划 DAG 的边类型）。"""

    COHORT = "Cohort"
    RUNSET = "RunSet"
    TABLE = "Table"
    FIGURE = "Figure"
    TREE = "Tree"
    ARTIFACT = "Artifact"
    ENV = "Env"
    TEXT = "Text"


class OperatorError(RuntimeError):
    """算子执行失败（可读 code + message；由执行器写入节点错误）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResourceSpec:
    cpu: int = 1
    mem_gb: int = 2
    timeout_s: int = 3600

    def as_dict(self) -> dict[str, int]:
        return {"cpu": self.cpu, "mem_gb": self.mem_gb, "timeout_s": self.timeout_s}


@dataclass(frozen=True)
class SandboxRequest:
    """沙箱请求（算子只描述，不直接接触容器后端）。"""

    kind: str = "run"  # run | build
    image: str = ""
    command: tuple[str, ...] = ()
    workspace: Path = Path(".")
    dockerfile: str = ""
    tag: str = ""
    network: bool = False
    timeout_s: int = 3600
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    backend: str = ""
    image_id: str = ""


SandboxRunner = Callable[[SandboxRequest], SandboxResult]


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    version: str
    doc: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params_model: type[BaseModel]
    data_class: int = 2
    determinism: str = "deterministic"
    resources: ResourceSpec = field(default_factory=ResourceSpec)
    approval: str = "none"
    optional_inputs: frozenset[str] = frozenset()

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "name": self.name,
            "version": self.version,
            "doc": self.doc,
            "inputs": {k: v.value for k, v in self.inputs.items()},
            "outputs": {k: v.value for k, v in self.outputs.items()},
            "params": self.params_model.model_json_schema(),
            "data_class": self.data_class,
            "determinism": self.determinism,
            "approval": self.approval,
            "optional_inputs": sorted(self.optional_inputs),
            "resources": self.resources.as_dict(),
        }


@dataclass(frozen=True)
class OperatorContext:
    """算子执行上下文：纯数据 + 路径，不含引擎对象。"""

    home: Path
    task_id: str
    node_id: str
    params: dict[str, Any]
    inputs: dict[str, Any]
    input_artifacts: dict[str, str]
    workdir: Path
    runner: SandboxRunner | None = None


OperatorFn = Callable[[OperatorContext], dict[str, Any]]


@dataclass(frozen=True)
class Operator:
    spec: OperatorSpec
    fn: OperatorFn


_REGISTRY: dict[str, Operator] = {}


def register(spec: OperatorSpec, fn: OperatorFn) -> Operator:
    if spec.ref in _REGISTRY:
        raise ValueError(f"operator already registered: {spec.ref}")
    op = Operator(spec=spec, fn=fn)
    _REGISTRY[spec.ref] = op
    return op


def operator(
    *,
    name: str,
    version: str,
    doc: str,
    inputs: dict[str, PortType],
    outputs: dict[str, PortType],
    params: type[BaseModel],
    data_class: int = 2,
    determinism: str = "deterministic",
    resources: ResourceSpec | None = None,
    approval: str = "none",
    optional_inputs: Iterable[str] = (),
) -> Callable[[OperatorFn], OperatorFn]:
    """声明一个算子。被装饰函数必须接受 :class:`OperatorContext` 并返回端口映射。"""

    def decorate(fn: OperatorFn) -> OperatorFn:
        spec = OperatorSpec(
            name=name,
            version=version,
            doc=doc,
            inputs=dict(inputs),
            outputs=dict(outputs),
            params_model=params,
            data_class=data_class,
            determinism=determinism,
            resources=resources or ResourceSpec(),
            approval=approval,
            optional_inputs=frozenset(optional_inputs),
        )
        register(spec, fn)
        return fn

    return decorate


def get_operator(ref: str) -> Operator:
    """按 ``name@version``（或 ``name`` 取最新版本）解析算子。"""
    if "@" in ref:
        try:
            return _REGISTRY[ref]
        except KeyError as exc:
            raise OperatorError("unknown_operator", f"no such operator: {ref}") from exc
    matches = [op for key, op in _REGISTRY.items() if op.spec.name == ref]
    if not matches:
        raise OperatorError("unknown_operator", f"no such operator: {ref}")
    return max(matches, key=lambda op: _version_key(op.spec.version))


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def list_operators() -> list[OperatorSpec]:
    return sorted((op.spec for op in _REGISTRY.values()), key=lambda s: (s.name, s.version))


def unregister(ref: str) -> None:
    """移除算子（测试隔离用；生产代码不应调用）。"""
    _REGISTRY.pop(ref, None)


def catalog() -> list[dict[str, Any]]:
    return [spec.catalog_entry() for spec in list_operators()]
