"""运行时配置与路径解析（ADR-03）。

原则：数据路径不由源码位置推导。
- 数据根目录 ``BACMAP_HOME``（默认 ``~/.local/share/bacmap``），可被环境变量覆盖；
- 配置文件为 TOML（不是 YAML）。解析顺序：
  1. ``BACMAP_CONFIG`` 显式指定；
  2. ``$BACMAP_HOME/config.toml``（兼容默认/单机数据目录形态）；
  3. ``$XDG_CONFIG_HOME/bacmap/config.toml``（默认 ``~/.config/bacmap/config.toml``），
    适合 pip/conda 安装后把配置与数据分开；
  4. 都不存在时使用内置默认值。
- 生信工具从当前 pixi/conda 环境的 PATH 解析（``which``），不做路径注入；
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


def _xdg_config_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "bacmap" / "config.toml"


def config_path(home: Path | str | None = None) -> Path:
    """当前生效的配置文件路径（即使尚未创建也返回目标路径）。

    ``BACMAP_CONFIG`` 显式优先。未显式指定时，使用传入的 ``home``（例如命令行
    ``--home``）或模块级 ``BACMAP_HOME``；已有的 ``config.toml`` 继续兼容，
    否则落到 XDG 用户配置目录。项目内临时配置可用：

    ``BACMAP_CONFIG=$PWD/config.toml bacmap ...``
    """
    explicit = os.environ.get("BACMAP_CONFIG")
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = Path(home).expanduser() if home is not None else BACMAP_HOME
    home_file = root / "config.toml"
    if home_file.is_file():
        return home_file
    xdg_file = _xdg_config_file()
    if xdg_file.is_file():
        return xdg_file
    return home_file


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """加载 TOML 配置；缺失或解析失败时返回空字典（内置默认值）。"""
    target = Path(path).expanduser() if path is not None else config_path()
    if not target.is_file():
        return {}
    try:
        with target.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _load_config_toml(home: Path) -> dict[str, Any]:
    # 兼容旧内部签名；实际路径由 config_path(home) 统一解析。
    return load_config(config_path(home))


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


def _debug_from_env() -> bool | None:
    raw = (os.environ.get("BACMAP_DEBUG") or "").strip().lower()
    if not raw:
        return None
    return raw in {"1", "true", "yes", "on"}


def _debug_from_config() -> bool:
    """Read ``[debug] enabled`` from the active ``config.toml``.

    The file is read on demand so operators can turn debug mode off without
    restarting every long-lived interface; malformed or missing files mean off.
    """
    path = config_path()
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    section = data.get("debug")
    return isinstance(section, dict) and section.get("enabled") is True


def debug_mode() -> bool:
    """开发调试模式：环境变量或 ``[debug] enabled = true`` 时放宽运行控制。

    优先级：``BACMAP_DEBUG`` 显式设置 > ``config.toml``。因此 ``BACMAP_DEBUG=0``
    可以临时关闭配置文件开启的 debug 模式。仅用于受控开发机；数据红线
    （D3/D4 永不发往 cloud 端点）与 MCP 数据级别/HTTP 鉴权**不**在此开关
    范围内：debug 不是安全边界（ADR-16）。
    """
    enabled = _debug_from_env()
    if enabled is not None:
        return enabled
    return _debug_from_config()


def debug_warning(component: str) -> str:
    """统一警告文本（调用方打印到 stderr/日志）。"""
    return (
        f"[bacmap] DEBUG MODE ({component}): BACMAP_DEBUG=1 或 "
        "[debug] enabled=true——Web 鉴权/CSRF、审批、门与沙箱限制已放宽；"
        "MCP 数据级别与 HTTP 鉴权不放宽。仅限本机开发；不要用于生产。"
    )


_UI_LANGUAGES = ("en", "zh")


def _ui_language_from_env() -> str | None:
    raw = (os.environ.get("BACMAP_LANG") or "").strip().lower()
    return raw if raw in _UI_LANGUAGES else None


def ui_language() -> str:
    """CLI 文案显示语言：``BACMAP_LANG`` > ``[ui] language`` > 内置默认 ``"en"``。

    取值仅 ``"en"`` | ``"zh"``（大小写不敏感）。环境变量或配置非法/缺失时
    确定性回落默认值（与 ``debug_mode`` 的容错口径一致），不逐次告警。
    """
    from_env = _ui_language_from_env()
    if from_env is not None:
        return from_env
    path = config_path()
    if path.is_file():
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            return "en"
        section = data.get("ui")
        if isinstance(section, dict):
            raw = section.get("language")
            if isinstance(raw, str):
                normalized = raw.strip().lower()
                if normalized in _UI_LANGUAGES:
                    return normalized
    return "en"


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

