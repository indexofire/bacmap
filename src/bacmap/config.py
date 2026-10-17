"""运行时配置与路径解析（ADR-03）。

原则：任何路径都不由源码位置推导。
- 数据根目录 ``BACMAP_HOME``（默认 ``~/.local/share/bacmap``），可被环境变量覆盖；
- 配置文件 ``$BACMAP_HOME/config.toml``（可选，不存在时全部取默认值）；
- 生信工具从当前 pixi 环境的 PATH 解析（``which``），不做路径注入；
- 测试与多实例部署通过环境变量覆盖（BACMAP_HOME / BACMAP_DATA_DIR /
  BACMAP_DB_PATH / BACMAP_RESULTS_DIR）。

历史：hermes-bacmap 的 config.py 把 PROJECT_ROOT/PIXI_BIN 写死在开发仓库目录、
插件靠软链接加载（dev/research-framework-evidence.md §2.2）——本模块是其替代。
"""

from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path
from typing import Any, overload


@overload
def _env_path(var: str, default: Path) -> Path: ...


@overload
def _env_path(var: str, default: None) -> Path | None: ...


def _env_path(var: str, default: Path | None) -> Path | None:
    val = os.environ.get(var)
    if val:
        return Path(val).resolve()
    return default


def _load_config_toml(home: Path) -> dict[str, Any]:
    cfg = home / "config.toml"
    if cfg.is_file():
        with cfg.open("rb") as fh:
            return tomllib.load(fh)
    return {}


def _resolve_data_dir(home: Path, paths_cfg: dict[str, Any], env_value: str | None) -> Path:
    """DATA_DIR 解析：环境变量优先（多实例/测试），其次 config.toml 的 paths.data_dir，
    最后 ``$BACMAP_HOME/data``。后两者展开 ``~`` 并 resolve（env 由 _env_path 处理）。"""
    if env_value:
        return Path(env_value).expanduser().resolve()
    configured = paths_cfg.get("data_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return home / "data"


BACMAP_HOME: Path = _env_path("BACMAP_HOME", Path.home() / ".local" / "share" / "bacmap")

_toml = _load_config_toml(BACMAP_HOME)
_paths_cfg: dict[str, Any] = _toml.get("paths", {})

DATA_DIR: Path = _resolve_data_dir(BACMAP_HOME, _paths_cfg, os.environ.get("BACMAP_DATA_DIR"))

REF_DIR: Path = DATA_DIR / "reference"

# 外部工具数据库登记目录（ADR-20）：refs/<tool>/…，版本与校验值经 refs/manifest.json
# 在部署时登记，运行记录（ADR-18 ref_databases）读取它。
REFS_DIR: Path = _env_path("BACMAP_REFS_DIR", BACMAP_HOME / "refs")

SPECIES_DB_DIR: Path = DATA_DIR / "db"

DB_PATH: Path = _env_path("BACMAP_DB_PATH", DATA_DIR / "bacmap.sqlite")

# 运行记录库（ADR-18 analysis_runs）与 GOM 库（分析对象 + 门事件）。
RUNS_DB: Path = _env_path("BACMAP_RUNS_DB", BACMAP_HOME / "runs.sqlite")
GOM_DB: Path = _env_path("BACMAP_GOM_DB", BACMAP_HOME / "gom.sqlite")

RESULTS_DIR: Path = _env_path("BACMAP_RESULTS_DIR", BACMAP_HOME / "results")

# 工作流文件目录（第 4 步迁入工作流后使用；脚本过渡期同样指向此处）。
WORKFLOWS_DIR: Path = _env_path("BACMAP_WORKFLOWS_DIR", BACMAP_HOME / "workflows")

# WorkflowRunner.deploy() 的落点：包内工作流模板复制到这里后运行（ADR-03/05）。
# samples.tsv、config.yaml、.snakemake/ 断点状态都在此目录下——所有数据类路径
# 一律经它解析，绝不由源码位置推导（ADR-03）。
DEPLOYED_WORKFLOWS_DIR: Path = WORKFLOWS_DIR / "bacmap"

# Snakemake 运行状态（.snakemake/ 日志等），迁移第 4 步起使用。
WORKFLOW_STATE_DIR: Path = _env_path("BACMAP_WORKFLOW_STATE_DIR", BACMAP_HOME / "workflow_state")
WORKFLOW_LOG_DIR: Path = WORKFLOW_STATE_DIR / "log"

# 大型鉴定数据库（GTDB-Tk / CheckM2 等）由部署者通过环境变量指向。
# 注：CheckM2 官方变量为 CHECKM2_DB（与文档一致）；CHECKM2DB 作为旧别名兼容。
CHECKM2_DB: Path | None = _env_path("CHECKM2_DB", None) or _env_path("CHECKM2DB", None)
GTDB_DB: Path | None = _env_path("GTDBTK_DATA_PATH", None) or _env_path("GTDBDB", None)


def pixi_path() -> str:
    """当前进程 PATH（pixi 环境激活时即含生信工具 bin）。保留旧名以兼容 engine/_env。"""
    return os.environ.get("PATH", "")


def which(tool: str) -> str | None:
    """在当前 PATH 中解析生信工具（ADR-03：不做路径注入）。"""
    return shutil.which(tool, path=pixi_path() or None)


def env_lock_path() -> Path | None:
    """定位当前运行环境的 ``pixi.lock``（ADR-18 的 ``env_lock_sha256`` 来源）。

    绝不从源码目录推导（ADR-03）。解析顺序：
    1. ``BACMAP_ENV_LOCK`` 显式指定的路径；
    2. ``$BACMAP_HOME/pixi.lock``（部署方随环境落盘）；
    3. ``$PIXI_PROJECT_ROOT/pixi.lock``（开发期由 pixi 任务注入）。
    都不可得时返回 ``None``（运行记录该项留空，而非猜测）。
    """
    explicit = os.environ.get("BACMAP_ENV_LOCK")
    if explicit:
        return Path(explicit).resolve()
    candidates = [BACMAP_HOME / "pixi.lock"]
    project_root = os.environ.get("PIXI_PROJECT_ROOT")
    if project_root:
        candidates.append(Path(project_root) / "pixi.lock")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None

