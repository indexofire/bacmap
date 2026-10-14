"""运行记录（ADR-18 / §4.6）：证据链 `(strain_id, run_id)` 的 run_id 侧。

每次工作流执行生成一条不可修改的 AnalysisRun：完整解析后参数及哈希、
参考数据库清单、工具实测版本、输入文件 SHA256、随机种子、起止时间。
存两份：analysis_runs 表（SQLite，INSERT-ONLY）+ 运行目录 run_manifest.json
（带自身 SHA256，两者内容一致）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id          TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL DEFAULT '',
    strain_ids      TEXT NOT NULL DEFAULT '[]',
    workflow        TEXT NOT NULL,
    workflow_commit TEXT NOT NULL DEFAULT '',
    workflow_dirty  INTEGER NOT NULL DEFAULT 0,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    ingested_at     TEXT,
    resolved_config TEXT NOT NULL DEFAULT '{}',
    config_sha256   TEXT NOT NULL DEFAULT '',
    ref_databases   TEXT NOT NULL DEFAULT '[]',
    tool_versions   TEXT NOT NULL DEFAULT '{}',
    env_lock_sha256 TEXT NOT NULL DEFAULT '',
    input_files     TEXT NOT NULL DEFAULT '{}',
    seeds           TEXT NOT NULL DEFAULT '{}',
    nondeterministic_steps TEXT NOT NULL DEFAULT '[]',
    host            TEXT NOT NULL DEFAULT '{}',
    baseline_version TEXT,
    manifest_sha256 TEXT NOT NULL DEFAULT ''
)
"""


class RefDatabase(BaseModel):
    name: str
    version: str
    checksum: str


class AnalysisRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str = ""
    strain_ids: list[str] = []
    workflow: str
    workflow_commit: str = ""
    workflow_dirty: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    ingested_at: datetime | None = None
    resolved_config: dict[str, Any] = {}
    config_sha256: str = ""
    ref_databases: list[RefDatabase] = []
    tool_versions: dict[str, str] = {}
    env_lock_sha256: str = ""
    input_files: dict[str, str] = {}
    seeds: dict[str, int] = {}
    nondeterministic_steps: list[str] = []
    host: dict[str, Any] = {}
    baseline_version: str | None = None
    manifest_sha256: str = ""


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def probe_tool_versions(tools: list[str], timeout: int = 20) -> dict[str, str]:
    """运行时实测版本（ADR-18）：优先 JSON 内嵌版本是第 5 步工具适配器的事，
    这里是回退通道——逐工具调 --version 取首个非空行。"""
    versions: dict[str, str] = {}
    for tool in tools:
        try:
            proc = subprocess.run(
                [tool, "--version"], capture_output=True, text=True, timeout=timeout
            )
            out = (proc.stdout or proc.stderr).strip().splitlines()
            versions[tool] = out[0].strip() if out else f"exit={proc.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            versions[tool] = f"unavailable: {type(exc).__name__}"
    return versions


def resolve_config(workflow_dir: Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """合并 config.yaml 与覆盖项后的完整参数（深合并一层，与 Snakemake --config 语义一致）。"""
    cfg_path = workflow_dir / "config" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def load_ref_databases(refs_dir: Path) -> list[RefDatabase]:
    """读取部署期登记的外部工具数据库（ADR-20 → AnalysisRun.ref_databases）。

    manifest 形如 ``$BACMAP_HOME/refs/manifest.json``::

        {"databases": [{"name": "gapit:card", "version": "3.2.6", "checksum": "..."}]}

    接受裸列表或带 ``databases`` 键的对象；文件缺失/条目非法时返回 ``[]``
    （不猜测、不做昂贵的目录全量哈希——校验值由部署方在登记时写入）。
    """
    manifest = refs_dir / "manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("databases") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    out: list[RefDatabase] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        version = entry.get("version")
        if not name or version is None:
            continue
        out.append(
            RefDatabase(
                name=str(name),
                version=str(version),
                checksum=str(entry.get("checksum", "")),
            )
        )
    return out


def create_run(
    workflow: str,
    workflow_dir: Path,
    strain_ids: list[str],
    overrides: dict[str, Any] | None = None,
    input_files: list[Path] | None = None,
    db_path: Path | None = None,
    task_id: str = "",
    refs_dir: Path | None = None,
) -> AnalysisRun:
    from bacmap.config import BACMAP_HOME, REFS_DIR, env_lock_path

    resolved = resolve_config(workflow_dir, overrides)
    run = AnalysisRun(
        task_id=task_id,
        strain_ids=strain_ids,
        workflow=workflow,
        resolved_config=resolved,
        config_sha256=hashlib.sha256(
            json.dumps(resolved, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        tool_versions=probe_tool_versions(
            ["snakemake", "fastp", "spades.py", "blastn", "gmlst", "abricate", "iqtree"]
        ),
        input_files={str(p): file_sha256(p) for p in (input_files or []) if Path(p).is_file()},
        seeds={"iqtree": int(resolved.get("iqtree_seed", 42))},
        ref_databases=load_ref_databases(refs_dir or REFS_DIR),
        host={"hostname": _hostname()},
    )
    lock = env_lock_path()
    if lock is not None:
        run.env_lock_sha256 = file_sha256(lock)
    run.manifest_sha256 = hashlib.sha256(
        _manifest_body(run).encode()
    ).hexdigest()

    conn = sqlite3.connect(db_path or (BACMAP_HOME / "runs.sqlite"))
    with conn:
        conn.execute(_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO analysis_runs (run_id, task_id, strain_ids, workflow, workflow_commit,"
            " workflow_dirty, started_at, resolved_config, config_sha256, ref_databases,"
            " tool_versions, env_lock_sha256, input_files, seeds, nondeterministic_steps, host,"
            " manifest_sha256)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id, run.task_id, json.dumps(run.strain_ids), run.workflow,
                run.workflow_commit, int(run.workflow_dirty),
                run.started_at.isoformat(), json.dumps(run.resolved_config, ensure_ascii=False),
                run.config_sha256, json.dumps([r.model_dump() for r in run.ref_databases]),
                json.dumps(run.tool_versions), run.env_lock_sha256,
                json.dumps(run.input_files), json.dumps(run.seeds),
                json.dumps(run.nondeterministic_steps), json.dumps(run.host),
                run.manifest_sha256,
            ),
        )
    conn.close()
    return run


def finish_run(run: AnalysisRun, db_path: Path | None = None) -> None:
    from bacmap.config import BACMAP_HOME

    run.finished_at = datetime.now(UTC)
    conn = sqlite3.connect(db_path or (BACMAP_HOME / "runs.sqlite"))
    with conn:
        conn.execute(
            "UPDATE analysis_runs SET finished_at = ? WHERE run_id = ? AND finished_at IS NULL",
            (run.finished_at.isoformat(), run.run_id),
        )
    conn.close()


def read_run(run_id: str, db_path: Path) -> AnalysisRun | None:
    """从 analysis_runs 表读回一条运行记录（用于封存 manifest，ADR-18）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA_SQL)
    row = conn.execute("SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return AnalysisRun(
        run_id=row["run_id"],
        task_id=row["task_id"],
        strain_ids=json.loads(row["strain_ids"]),
        workflow=row["workflow"],
        workflow_commit=row["workflow_commit"],
        workflow_dirty=bool(row["workflow_dirty"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        ingested_at=datetime.fromisoformat(row["ingested_at"]) if row["ingested_at"] else None,
        resolved_config=json.loads(row["resolved_config"]),
        config_sha256=row["config_sha256"],
        ref_databases=[RefDatabase(**d) for d in json.loads(row["ref_databases"])],
        tool_versions=json.loads(row["tool_versions"]),
        env_lock_sha256=row["env_lock_sha256"],
        input_files=json.loads(row["input_files"]),
        seeds=json.loads(row["seeds"]),
        nondeterministic_steps=json.loads(row["nondeterministic_steps"]),
        host=json.loads(row["host"]),
        baseline_version=row["baseline_version"],
        manifest_sha256=row["manifest_sha256"],
    )


def finalize_run(run_id: str, db_path: Path, runs_root: Path) -> AnalysisRun | None:
    """封存运行记录：补 finished_at、重算 manifest_sha256、落盘 run_manifest.json。

    表与文件内容一致（ADR-18 §4.6）：先写文件再用其哈希回写表，两者同源。
    """
    run = read_run(run_id, db_path)
    if run is None:
        return None
    if run.finished_at is None:
        run.finished_at = datetime.now(UTC)
    run.manifest_sha256 = hashlib.sha256(_manifest_body(run).encode()).hexdigest()
    write_manifest(run, runs_root)
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "UPDATE analysis_runs SET finished_at = ?, manifest_sha256 = ? WHERE run_id = ?",
            (run.finished_at.isoformat(), run.manifest_sha256, run.run_id),
        )
    conn.close()
    return run


def write_manifest(run: AnalysisRun, runs_root: Path) -> Path:
    """运行目录内的 run_manifest.json（与表内容一致，自校验）。"""
    d = runs_root / run.run_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "run_manifest.json"
    payload = json.loads(_manifest_body(run))
    payload["manifest_sha256"] = run.manifest_sha256
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def _manifest_body(run: AnalysisRun) -> str:
    return run.model_dump_json(exclude={"finished_at", "ingested_at", "manifest_sha256"})


def _hostname() -> str:
    import socket

    return socket.gethostname()


# ---------------------------------------------------------------------------
# 运行比较（ADR-18：差异归因 + 不可复现告警）
# ---------------------------------------------------------------------------

_PROVENANCE_DIMS: dict[str, tuple[str, ...]] = {
    "parameters": ("resolved_config", "config_sha256", "seeds"),
    "databases": ("ref_databases",),
    "tools": ("tool_versions", "env_lock_sha256"),
    "inputs": ("input_files",),
    "workflow": ("workflow_commit", "workflow_dirty"),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def compare_runs(a: AnalysisRun, b: AnalysisRun) -> dict[str, Any]:
    """逐字段比较两次运行的来源（参数/数据库/工具/输入/工作流）。

    返回 ``diffs``（每项含 category/field/a/b）与 ``changed_categories``。
    结果层面的比较由调用方（bio_compare_runs）叠加，用于"来源相同但结果不同
    → 标记不可复现"的判定（ADR-18）。
    """
    diffs: list[dict[str, Any]] = []
    changed: set[str] = set()
    for category, fields in _PROVENANCE_DIMS.items():
        for field in fields:
            va, vb = getattr(a, field), getattr(b, field)
            if va != vb:
                diffs.append(
                    {
                        "category": category,
                        "field": field,
                        "a": _jsonable(va),
                        "b": _jsonable(vb),
                    }
                )
                changed.add(category)
    return {
        "run_a": a.run_id,
        "run_b": b.run_id,
        "same_provenance": not diffs,
        "changed_categories": sorted(changed),
        "diffs": diffs,
    }
