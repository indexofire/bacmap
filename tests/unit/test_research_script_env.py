"""P4：沙箱脚本算子、环境构建算子与配置解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacmap.research.config import (
    ApprovalConfig,
    load_research_config,
    parse_research_config,
)
from bacmap.research.operators import get_operator
from bacmap.research.operators.builtin import render_env_dockerfile
from bacmap.research.operators.spec import OperatorContext, SandboxRequest, SandboxResult


class FakeRunner:
    def __init__(self, *, rc: int = 0, stderr: str = "", image_id: str = "sha256:img") -> None:
        self.rc = rc
        self.stderr = stderr
        self.image_id = image_id
        self.requests: list[SandboxRequest] = []

    def __call__(self, request: SandboxRequest) -> SandboxResult:
        self.requests.append(request)
        return SandboxResult(
            returncode=self.rc,
            stdout="ok",
            stderr=self.stderr,
            backend="fake",
            image_id=self.image_id,
        )


def _ctx(tmp_path: Path, params: dict, runner: FakeRunner, inputs: dict | None = None) -> OperatorContext:
    return OperatorContext(
        home=tmp_path,
        task_id="t1",
        node_id="n1",
        params=params,
        inputs=inputs or {},
        input_artifacts={},
        workdir=tmp_path / "work",
        runner=runner,
    )


def _script_ok(workspace: Path) -> None:
    (workspace / "result.json").write_text('{"answer": 42}', encoding="utf-8")


# ---------------------------------------------------------------------------
# script.python
# ---------------------------------------------------------------------------


def test_script_python_runs_and_returns_result(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner_write = _script_ok

    def _run(request: SandboxRequest) -> SandboxResult:
        runner_write(request.workspace)
        return runner(request)

    ctx = _ctx(tmp_path, {"code": "print('hi')", "objective": "x", "image": "img"}, _run)  # type: ignore[arg-type]
    out = get_operator("script.python@1.0").fn(ctx)
    assert out["result"] == {"answer": 42}
    assert out["log"]["backend"] == "fake"
    assert (tmp_path / "work" / "sandbox" / "analysis.py").is_file()


def test_script_python_passes_input_data(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def _run(request: SandboxRequest) -> SandboxResult:
        seen["data"] = (request.workspace / "inputs" / "data.json").read_text(encoding="utf-8")
        _script_ok(request.workspace)
        return SandboxResult(returncode=0, backend="fake")

    ctx = _ctx(
        tmp_path,
        {"code": "x", "objective": "", "image": "img"},
        _run,  # type: ignore[arg-type]
        inputs={"data": {"rows": [1, 2]}},
    )
    get_operator("script.python@1.0").fn(ctx)
    assert '"rows"' in seen["data"]


def test_script_python_failure_is_reported(tmp_path: Path) -> None:
    runner = FakeRunner(rc=1, stderr="Traceback: boom")
    ctx = _ctx(tmp_path, {"code": "raise", "objective": "", "image": "img"}, runner)
    with pytest.raises(Exception) as excinfo:
        get_operator("script.python@1.0").fn(ctx)
    assert "boom" in str(excinfo.value)


def test_script_python_requires_result_json(tmp_path: Path) -> None:
    runner = FakeRunner()
    ctx = _ctx(tmp_path, {"code": "pass", "objective": "", "image": "img"}, runner)
    with pytest.raises(Exception) as excinfo:
        get_operator("script.python@1.0").fn(ctx)
    assert "result.json" in str(excinfo.value)


def test_script_python_requires_runner(tmp_path: Path) -> None:
    ctx = OperatorContext(
        home=tmp_path,
        task_id="t",
        node_id="n",
        params={"code": "pass", "objective": "", "image": "img"},
        inputs={},
        input_artifacts={},
        workdir=tmp_path,
        runner=None,
    )
    with pytest.raises(Exception) as excinfo:
        get_operator("script.python@1.0").fn(ctx)
    assert "sandbox" in str(excinfo.value)


# ---------------------------------------------------------------------------
# env.build
# ---------------------------------------------------------------------------


def _env_params(**overrides: object) -> dict:
    base = {"base": "python:3.12-slim", "apt": [], "pip": [], "script": "", "tag": ""}
    base.update(overrides)
    return base


def test_env_build_refuses_without_network(tmp_path: Path) -> None:
    runner = FakeRunner()
    ctx = _ctx(tmp_path, _env_params(pip=["lifelines"]), runner)
    with pytest.raises(Exception) as excinfo:
        get_operator("env.build@1.0").fn(ctx)
    assert "allow_network" in str(excinfo.value)


def test_env_build_refuses_without_mirrors(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[research.env]\nallow_network = true\n", encoding="utf-8")
    runner = FakeRunner()
    ctx = _ctx(tmp_path, _env_params(pip=["lifelines"]), runner)
    with pytest.raises(Exception) as excinfo:
        get_operator("env.build@1.0").fn(ctx)
    assert "mirrors" in str(excinfo.value)


def test_env_build_records_digest_and_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        "[research.env]\nallow_network = true\nmirrors = ['https://pypi.internal/simple']\n",
        encoding="utf-8",
    )
    runner = FakeRunner(image_id="sha256:deadbeef")
    ctx = _ctx(
        tmp_path,
        _env_params(pip=["lifelines==0.30.0"], apt=["libxml2-dev"]),
        runner,
    )
    out = get_operator("env.build@1.0").fn(ctx)
    env = out["env"]
    assert env["digest"] == "sha256:deadbeef"
    assert env["image"].startswith("bacmap-env:")
    assert "pip install" in env["dockerfile"]
    assert "libxml2-dev" in env["dockerfile"]
    assert runner.requests[0].kind == "build"
    assert runner.requests[0].network is True


def test_dockerfile_rendering_is_deterministic() -> None:
    params = {"base": "python:3.12-slim", "apt": ["curl"], "pip": ["numpy==2.0"], "script": "echo hi"}
    first = render_env_dockerfile(params, proxy="http://proxy:3128", pypi="https://pypi.internal/simple")
    second = render_env_dockerfile(params, proxy="http://proxy:3128", pypi="https://pypi.internal/simple")
    assert first == second
    assert "PIP_INDEX_URL=https://pypi.internal/simple" in first
    assert "COPY setup.sh" in first


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = parse_research_config({})
    assert cfg.env.allow_network is False
    assert cfg.env.mirrors == ()
    assert cfg.approval.code_review == "always"


def test_config_parses_sections() -> None:
    cfg = parse_research_config(
        {
            "research": {
                "env": {"allow_network": True, "mirrors": ["https://m"], "proxy": "http://p"},
                "approval": {"code_review": "plan"},
            }
        }
    )
    assert cfg.env.allow_network is True
    assert cfg.env.mirrors == ("https://m",)
    assert cfg.approval.code_review == "plan"


def test_config_rejects_unknown_review_level() -> None:
    with pytest.raises(ValueError):
        parse_research_config({"research": {"approval": {"code_review": "sometimes"}}})


def test_load_config_from_home(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        "[research.approval]\ncode_review = 'off'\n", encoding="utf-8"
    )
    cfg = load_research_config(tmp_path)
    assert cfg.approval == ApprovalConfig(code_review="off")
