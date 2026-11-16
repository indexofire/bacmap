"""研究计划器（P3）：把自然语言问题编译成可执行 DAG 草案。

边界（ADR-16/ADR-21）：

- 计划器**只提案**：不创建计划、不确认、不执行；确认仍在 bacmap CLI/Web。
- 计划器只看到算子目录与 run 摘要（D2 元数据），**不接触**样本明细/序列/表型表。
- 输出必须过 ``ResearchDag`` 的类型校验；校验失败把结构化问题回传模型修复，
  最多 ``max_attempts`` 轮。
- 缺关键参数（基因、药物、run_id、时间范围）时**不许猜**：返回澄清问题。

LLM 不可用时抛 ``LlmUnavailableError``，由接口层给出可操作的配置提示。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from bacmap.agent.llm.gateway import LlmGateway
from bacmap.research.dag import DagValidationError, ResearchDag
from bacmap.research.operators import catalog
from bacmap.tools.spec import DataClass

DEFAULT_PURPOSE = "planner"


class PlannerConstraints(BaseModel):
    """计划器可见的约束（全部为 D0/D1 元数据）。"""

    max_data_class: int = Field(default=2, ge=0, le=4)
    species: str = ""
    allow_checkpoints: bool = True


class PlannerOutput(BaseModel):
    """LLM 的结构化输出；dag 为 None 表示需要澄清。"""

    dag: dict[str, Any] | None = Field(
        default=None, description="符合 bacmap.research.dag/1 的 DAG；需要澄清时为 null"
    )
    questions: list[str] = Field(default_factory=list, description="需要用户回答的关键参数")
    rationale: str = Field(default="", description="一句话说明计划思路")


class PlanProposal(BaseModel):
    dag: dict[str, Any] | None = None
    questions: list[str] = Field(default_factory=list)
    rationale: str = ""
    problems: list[str] = Field(default_factory=list)
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.dag is not None and not self.problems


def _catalog_prompt(entries: list[dict[str, Any]] | None = None) -> str:
    items = entries if entries is not None else catalog()
    compact = [
        {
            "ref": item["ref"],
            "doc": item["doc"],
            "inputs": item["inputs"],
            "outputs": item["outputs"],
            "data_class": item["data_class"],
            "params": item["params"].get("properties", {}),
            "required": item["params"].get("required", []),
        }
        for item in items
    ]
    return json.dumps(compact, ensure_ascii=False, indent=1)


def _runs_prompt(runs: list[dict[str, Any]] | None) -> str:
    if not runs:
        return "（未提供 run 列表；如需 run_id 请向用户询问）"
    lines = []
    for run in runs[:10]:
        strains = run.get("strain_ids") or []
        lines.append(
            f"- run_id={run.get('run_id')}  菌株数={len(strains)}  "
            f"开始={run.get('started_at', '')}"
        )
    return "\n".join(lines)


def build_prompt(
    question: str,
    *,
    constraints: PlannerConstraints,
    runs: list[dict[str, Any]] | None,
    entries: list[dict[str, Any]] | None = None,
    repair: list[str] | None = None,
) -> str:
    checkpoint_rule = (
        "允许在关键决策节点设置 checkpoints（例如关联结果出来之后、成文之前）。"
        if constraints.allow_checkpoints
        else "不要设置 checkpoints。"
    )
    repair_section = ""
    if repair:
        repair_section = (
            "\n上一版 DAG 未通过校验，请只修复下列问题后重新输出完整 DAG：\n"
            + "\n".join(f"- {item}" for item in repair)
            + "\n"
        )
    return f"""你是 bacmap 的研究计划器。把用户的研究问题编译成**可执行分析 DAG**。

用户问题：
{question}

可用的既有 run（只能使用这里列出的 run_id，或向用户询问）：
{_runs_prompt(runs)}

约束：
- 数据级别上限：D{constraints.max_data_class}（不得越界）。
- 执行模式：线性（execution.mode="linear"）；不允许嵌套 DAG。
- {checkpoint_rule}
- 节点 op 必须精确等于下面目录中的 ref，禁止发明算子。
- inputs 用 "<节点id>.<端口名>"；每个输入端口都必须连线。
- 缺关键参数（基因名、药物名、run_id、时间范围）时**不要猜测**：
  在 questions 中列出问题并令 dag=null。
- 若问题已足够明确，dag 必须能通过以下校验：端口类型匹配、无环、检查点节点有产物。

算子目录（唯一可用集合）：
{_catalog_prompt(entries)}
{repair_section}
输出要求：dag 为 bacmap.research.dag/1 JSON（含 schema 字段）；rationale 用一句中文说明思路。"""


def propose_dag(
    question: str,
    gateway: LlmGateway,
    *,
    constraints: PlannerConstraints | None = None,
    runs: list[dict[str, Any]] | None = None,
    entries: list[dict[str, Any]] | None = None,
    purpose: str = DEFAULT_PURPOSE,
    max_attempts: int = 3,
) -> PlanProposal:
    """生成 DAG 草案；校验失败自动修复，仍失败则返回带 problems 的提案。"""
    limits = constraints or PlannerConstraints()
    prompt = build_prompt(question, constraints=limits, runs=runs, entries=entries)
    attempts = 0
    problems: list[str] = []
    while attempts < max(1, max_attempts):
        attempts += 1
        output = gateway.structured(
            purpose=purpose,
            prompt=prompt,
            output_type=PlannerOutput,
            data_class=DataClass(limits.max_data_class),
        )
        if not isinstance(output, PlannerOutput):  # pragma: no cover - 防御
            output = PlannerOutput.model_validate(output)
        if output.dag is None:
            return PlanProposal(
                questions=list(output.questions),
                rationale=output.rationale,
                attempts=attempts,
            )
        try:
            dag = ResearchDag.model_validate(output.dag)
            dag.validate_dag()
        except (DagValidationError, ValueError) as exc:
            problems = (
                list(exc.problems)
                if isinstance(exc, DagValidationError)
                else [f"invalid dag: {exc}"]
            )
            prompt = build_prompt(
                question,
                constraints=limits,
                runs=runs,
                entries=entries,
                repair=problems,
            )
            continue
        return PlanProposal(
            dag=dag.model_dump(mode="json", by_alias=True),
            questions=list(output.questions),
            rationale=output.rationale,
            attempts=attempts,
        )
    return PlanProposal(
        problems=problems or ["planner failed to produce a valid dag"],
        attempts=attempts,
    )


def recent_run_summaries(home: Any, limit: int = 10) -> list[dict[str, Any]]:
    """最近 run 摘要（只含 run_id/菌株数/时间，D2 元数据）。"""
    from pathlib import Path

    from bacmap.store import runs as runs_store

    db = Path(home) / "runs.sqlite"
    if not db.is_file():
        return []
    return runs_store.list_runs(db, limit=limit)
