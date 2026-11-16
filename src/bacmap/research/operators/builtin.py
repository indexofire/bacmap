"""内置算子（P1）：把现有确定性能力接入研究编排层。

只做适配与校验，不新写生信算法（ADR-20）；所有计算复用 ``bacmap.research``
既有实现，保证 CLI/Web/MCP 与 DAG 三条路径结果一致。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bacmap.research.models import (
    AnalysisSession,
    ResearchProfile,
    SessionStatus,
    StatResult,
)
from bacmap.research.operators.spec import (
    OperatorContext,
    OperatorError,
    PortType,
    ResourceSpec,
    operator,
)

# ---------------------------------------------------------------------------
# cohort.from_run
# ---------------------------------------------------------------------------


class CohortFromRunParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=64, description="既有分析 run 的 id")


@operator(
    name="cohort.from_run",
    version="1.0",
    doc="从既有分析 run 读取菌株集合（不重跑管线）",
    inputs={},
    outputs={"cohort": PortType.COHORT},
    params=CohortFromRunParams,
    data_class=2,
    resources=ResourceSpec(cpu=1, mem_gb=1, timeout_s=60),
)
def cohort_from_run(ctx: OperatorContext) -> dict[str, Any]:
    from bacmap.store import runs

    run = runs.read_run(str(ctx.params["run_id"]), ctx.home / "runs.sqlite")
    if run is None:
        raise OperatorError("not_found", f"no such run: {ctx.params['run_id']}")
    if not run.strain_ids:
        raise OperatorError("empty_cohort", f"run {run.run_id} has no strains")
    return {"cohort": {"run_id": run.run_id, "isolate_ids": list(run.strain_ids)}}


# ---------------------------------------------------------------------------
# stats.assoc
# ---------------------------------------------------------------------------


class AssocParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gene: str = Field(min_length=1, max_length=128, description="AMR 基因名，如 blaCTX-M-15")
    test_name: str = Field(min_length=1, max_length=128, description="药敏项目，如 meropenem")


@operator(
    name="stats.assoc",
    version="1.0",
    doc="2×2 列联表关联分析（基因存在 × 表型耐药，Woolf 95% CI）",
    inputs={"cohort": PortType.COHORT},
    outputs={"table": PortType.TABLE},
    params=AssocParams,
    data_class=2,
    resources=ResourceSpec(cpu=1, mem_gb=1, timeout_s=120),
)
def stats_assoc(ctx: OperatorContext) -> dict[str, Any]:
    from bacmap.research.stats import analyze_amr_association

    cohort = ctx.inputs["cohort"]
    run_id = str(cohort.get("run_id") or "")
    if not run_id:
        raise OperatorError("invalid_input", "cohort is missing run_id")
    stat = analyze_amr_association(ctx.home, run_id, ctx.params["gene"], ctx.params["test_name"])
    return {
        "table": {
            "run_id": run_id,
            "gene": str(ctx.params["gene"]),
            "test_name": str(ctx.params["test_name"]),
            "stat": stat.model_dump(mode="json"),
        }
    }


# ---------------------------------------------------------------------------
# figure.forest
# ---------------------------------------------------------------------------


class ForestParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(default="", max_length=200)


@operator(
    name="figure.forest",
    version="1.0",
    doc="关联结果森林图（SVG，沿用既有 figure contract）",
    inputs={"table": PortType.TABLE},
    outputs={"figure": PortType.FIGURE},
    params=ForestParams,
    data_class=2,
    resources=ResourceSpec(cpu=1, mem_gb=1, timeout_s=60),
)
def figure_forest(ctx: OperatorContext) -> dict[str, Any]:
    from bacmap.research.figures import build_association_spec
    from bacmap.research.render import render_association_svg

    table = ctx.inputs["table"]
    stat = StatResult.model_validate(table["stat"])
    now = datetime.now(UTC).isoformat()
    session = AnalysisSession(
        session_id=f"dag-{ctx.task_id}-{ctx.node_id}",
        run_id=str(table["run_id"]),
        gene=str(table["gene"]),
        test_name=str(table["test_name"]),
        profile=ResearchProfile.RESEARCH,
        status=SessionStatus.REVIEW_REQUIRED,
        data_class=2,
        created_by=f"dag:{ctx.task_id}",
        created_at=now,
        updated_at=now,
    )
    spec = build_association_spec(session, stat)
    if ctx.params.get("title"):
        spec = spec.model_copy(update={"title": str(ctx.params["title"])})
    svg = render_association_svg(spec)
    return {"figure": {"format": "svg", "data": svg, "figure_id": spec.figure_id}}


# ---------------------------------------------------------------------------
# text.report
# ---------------------------------------------------------------------------


class ReportParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str = Field(default="surveillance-zh", max_length=64)


@operator(
    name="text.report",
    version="1.0",
    doc="中文监测报告（数字槽位 + 证据绑定；不含 LLM 行文）",
    inputs={"table": PortType.TABLE, "figure": PortType.FIGURE},
    outputs={"text": PortType.TEXT},
    params=ReportParams,
    data_class=2,
    # 发表门在导出路径接入（P2）；当前仅声明意图，不作为执行期门。
    approval="none",
    resources=ResourceSpec(cpu=1, mem_gb=1, timeout_s=60),
)
def text_report(ctx: OperatorContext) -> dict[str, Any]:
    from bacmap.research.numeric_audit import audit_numbers
    from bacmap.research.report_dag import render_surveillance_report

    if ctx.params.get("template") != "surveillance-zh":
        raise OperatorError(
            "unsupported_template", f"unknown report template: {ctx.params.get('template')}"
        )
    table = ctx.inputs["table"]
    stat = StatResult.model_validate(table["stat"])
    rendered = render_surveillance_report(
        run_id=str(table["run_id"]),
        gene=str(table["gene"]),
        drug=str(table["test_name"]),
        stat=stat,
        table_artifact=ctx.input_artifacts.get("table", ""),
        figure_artifact=ctx.input_artifacts.get("figure", ""),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    violations = audit_numbers(rendered["markdown"], rendered["slots"])
    if violations:
        raise OperatorError(
            "numeric_audit_failed",
            f"numbers without provenance: {', '.join(violations[:10])}",
        )
    return {
        "text": {
            "format": "markdown",
            "template": str(ctx.params.get("template") or "surveillance-zh"),
            "markdown": rendered["markdown"],
            "slots": rendered["slots"],
            "claims": rendered["claims"],
            "audit": {"ok": True, "violations": []},
        }
    }


# ---------------------------------------------------------------------------
# script.python（P4：沙箱内任意代码）
# ---------------------------------------------------------------------------


class ScriptParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=20_000, description="Python 脚本全文")
    objective: str = Field(default="", max_length=500)
    image: str = Field(default="docker://python:3.12-slim", max_length=200)


@operator(
    name="script.python",
    version="1.0",
    doc=(
        "在无网络沙箱内执行 Python 脚本；脚本读取 /workspace/inputs/data.json，"
        "必须把 JSON 结果写入 /workspace/result.json"
    ),
    inputs={"data": PortType.ARTIFACT},
    optional_inputs=("data",),
    outputs={"result": PortType.ARTIFACT, "log": PortType.TEXT},
    params=ScriptParams,
    data_class=3,
    approval="code",
    determinism="stochastic",
    resources=ResourceSpec(cpu=1, mem_gb=4, timeout_s=3600),
)
def script_python(ctx: OperatorContext) -> dict[str, Any]:
    import json

    from bacmap.research.operators.spec import SandboxRequest

    if ctx.runner is None:
        raise OperatorError("sandbox_unavailable", "no sandbox runner in this context")
    sandbox = ctx.workdir / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "analysis.py").write_text(str(ctx.params["code"]), encoding="utf-8")
    data = ctx.inputs.get("data")
    if data is not None:
        inputs_dir = sandbox / "inputs"
        inputs_dir.mkdir(exist_ok=True)
        (inputs_dir / "data.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    result = ctx.runner(
        SandboxRequest(
            kind="run",
            image=str(ctx.params["image"]),
            command=("python", "/workspace/analysis.py"),
            workspace=sandbox,
            timeout_s=3600,
        )
    )
    log = {
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
        "backend": result.backend,
        "returncode": result.returncode,
    }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise OperatorError("sandbox_failed", f"script exited {result.returncode}: {detail}")
    result_path = sandbox / "result.json"
    if not result_path.is_file():
        raise OperatorError(
            "missing_result", "script must write /workspace/result.json"
        )
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OperatorError("invalid_result", f"result.json is not valid JSON: {exc}") from exc
    return {"result": payload, "log": log}


# ---------------------------------------------------------------------------
# env.build（P4：镜像构建；唯一允许联网的执行路径）
# ---------------------------------------------------------------------------


class EnvBuildParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: str = Field(default="python:3.12-slim", max_length=200)
    apt: list[str] = Field(default_factory=list)
    pip: list[str] = Field(default_factory=list)
    script: str = Field(default="", max_length=20_000)
    tag: str = Field(default="", max_length=120)


def render_env_dockerfile(params: dict[str, Any], *, proxy: str = "", pypi: str = "") -> str:
    """确定性渲染 Dockerfile（相同输入 → 相同文本 → 相同 tag）。"""
    base = str(params.get("base") or "python:3.12-slim")
    if base.startswith("docker://"):
        base = base[len("docker://") :]
    lines = [f"FROM {base}"]
    env_pairs: list[str] = []
    if pypi:
        env_pairs.append(f"PIP_INDEX_URL={pypi}")
    if proxy:
        env_pairs.extend([f"HTTP_PROXY={proxy}", f"HTTPS_PROXY={proxy}"])
    if env_pairs:
        lines.append("ENV " + " ".join(env_pairs))
    apt = [str(p) for p in params.get("apt") or []]
    if apt:
        lines.append(
            "RUN apt-get update && apt-get install -y --no-install-recommends "
            + " ".join(apt)
            + " && rm -rf /var/lib/apt/lists/*"
        )
    pip = [str(p) for p in params.get("pip") or []]
    if pip:
        lines.append("RUN pip install --no-cache-dir " + " ".join(pip))
    if str(params.get("script") or ""):
        lines.append("COPY setup.sh /tmp/setup.sh")
        lines.append("RUN bash /tmp/setup.sh")
    return "\n".join(lines) + "\n"


@operator(
    name="env.build",
    version="1.0",
    doc=(
        "按白名单镜像源构建不可变分析镜像（Podman）；产物为镜像 tag + digest，"
        "供 script.* 节点引用"
    ),
    inputs={},
    outputs={"env": PortType.ENV},
    params=EnvBuildParams,
    data_class=0,
    approval="code",
    resources=ResourceSpec(cpu=2, mem_gb=8, timeout_s=3600),
)
def env_build(ctx: OperatorContext) -> dict[str, Any]:
    import hashlib

    from bacmap.research.config import load_research_config
    from bacmap.research.operators.spec import SandboxRequest

    config = load_research_config(ctx.home)
    if not config.env.allow_network:
        raise OperatorError(
            "network_disabled",
            "image build needs network; set [research.env] allow_network = true",
        )
    if not config.env.mirrors:
        raise OperatorError(
            "no_mirrors",
            "image build needs a mirror allowlist; set [research.env] mirrors = [...]",
        )
    if ctx.runner is None:
        raise OperatorError("sandbox_unavailable", "no sandbox runner in this context")

    pypi = next((m for m in config.env.mirrors if "pypi" in m.lower()), "")
    dockerfile = render_env_dockerfile(
        ctx.params, proxy=config.env.proxy, pypi=pypi
    )
    digest = hashlib.sha256(dockerfile.encode()).hexdigest()[:12]
    tag = str(ctx.params.get("tag") or f"bacmap-env:{digest}")
    workdir = ctx.workdir / "build"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    script = str(ctx.params.get("script") or "")
    if script:
        (workdir / "setup.sh").write_text(script, encoding="utf-8")

    result = ctx.runner(
        SandboxRequest(
            kind="build",
            workspace=workdir,
            dockerfile=dockerfile,
            tag=tag,
            network=True,
            timeout_s=3600,
        )
    )
    if result.returncode != 0 or not result.image_id:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise OperatorError(
            "build_failed",
            f"podman build exited {result.returncode}: {detail or 'no image id'}",
        )
    return {
        "env": {
            "image": tag,
            "digest": result.image_id,
            "dockerfile": dockerfile,
            "mirrors": list(config.env.mirrors),
            "built_by": f"dag:{ctx.task_id}",
        }
    }


# ---------------------------------------------------------------------------
# text.manuscript（P5：英文 IMRAD 稿）
# ---------------------------------------------------------------------------


class ManuscriptParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str = Field(default="imrad-en", max_length=64)
    title: str = Field(default="", max_length=300)


@operator(
    name="text.manuscript",
    version="1.0",
    doc="英文 IMRAD 稿（数据成文；不含文献引用；数字经审计门）",
    inputs={"table": PortType.TABLE, "figure": PortType.FIGURE},
    optional_inputs=("figure",),
    outputs={"text": PortType.TEXT},
    params=ManuscriptParams,
    data_class=2,
    resources=ResourceSpec(cpu=1, mem_gb=1, timeout_s=60),
)
def text_manuscript(ctx: OperatorContext) -> dict[str, Any]:
    from bacmap.research.numeric_audit import audit_numbers
    from bacmap.research.report_dag import render_imrad_manuscript

    if ctx.params.get("template") != "imrad-en":
        raise OperatorError(
            "unsupported_template",
            f"unknown manuscript template: {ctx.params.get('template')}",
        )
    table = ctx.inputs["table"]
    stat = StatResult.model_validate(table["stat"])
    rendered = render_imrad_manuscript(
        run_id=str(table["run_id"]),
        gene=str(table["gene"]),
        drug=str(table["test_name"]),
        stat=stat,
        table_artifact=ctx.input_artifacts.get("table", ""),
        figure_artifact=ctx.input_artifacts.get("figure", ""),
        title=str(ctx.params.get("title") or ""),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    violations = audit_numbers(rendered["markdown"], rendered["slots"])
    if violations:
        raise OperatorError(
            "numeric_audit_failed",
            f"numbers without provenance: {', '.join(violations[:10])}",
        )
    return {
        "text": {
            "format": "markdown",
            "template": "imrad-en",
            "markdown": rendered["markdown"],
            "slots": rendered["slots"],
            "claims": rendered["claims"],
            "audit": {"ok": True, "violations": []},
        }
    }
