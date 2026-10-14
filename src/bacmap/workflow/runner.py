"""WorkflowRunner（ADR-05：Snakemake 9 只经 CLI 子进程调用）。

部署模型：包内工作流模板（src/bacmap/workflow/）→ 首次运行时复制到
``$BACMAP_HOME/workflows/bacmap/`` 并把 config 的 project_root 重写为
BACMAP_HOME（ADR-03：数据库/结果均落在 BACMAP_HOME 下）；重部署不覆盖
用户的 samples.tsv。运行时 cwd=部署目录，保留 ``.snakemake/`` 断点续跑。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from bacmap.config import BACMAP_HOME, WORKFLOWS_DIR
from bacmap.core._pkg import pkg_dir

WORKFLOW_PKG_DIR = pkg_dir().parent / "workflow"
DEPLOYED_DIR = WORKFLOWS_DIR / "bacmap"


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(f.relative_to(root)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def deployed_stamp() -> Path:
    return DEPLOYED_DIR / ".bacmap_workflow_sha"


def deploy(force: bool = False) -> Path:
    """包内工作流 → BACMAP_HOME；内容变化时自动更新（保留 samples.tsv 与 .snakemake 续跑状态）。"""
    pkg_hash = _tree_hash(WORKFLOW_PKG_DIR)
    stamp = deployed_stamp()
    if not force and stamp.is_file() and stamp.read_text().strip() == pkg_hash:
        return DEPLOYED_DIR

    keeps: list[tuple[Path, Path]] = []
    for rel in ("config/samples.tsv", ".snakemake"):
        src = DEPLOYED_DIR / rel
        if src.exists():
            bak = DEPLOYED_DIR.parent / (src.name + ".keep")
            if bak.exists():
                shutil.rmtree(bak, ignore_errors=True)
            shutil.copytree(src, bak) if src.is_dir() else shutil.copy2(src, bak)
            keeps.append((bak, DEPLOYED_DIR / rel))

    if DEPLOYED_DIR.exists():
        shutil.rmtree(DEPLOYED_DIR)
    shutil.copytree(WORKFLOW_PKG_DIR, DEPLOYED_DIR, ignore=shutil.ignore_patterns("__pycache__"))

    for bak, dst in keeps:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.move(str(bak), str(dst))

    cfg = DEPLOYED_DIR / "config" / "config.yaml"
    text = cfg.read_text()
    marker = 'project_root: "../.."'
    already = f'project_root: "{BACMAP_HOME}"'
    if marker in text:
        rewritten = text.replace(marker, already)
    elif already in text:
        rewritten = text  # 重部署：已指向 BACMAP_HOME
    else:
        # 模板缺少可重写的 project_root 标记 → 部署路径会错，快速失败而非静默。
        raise RuntimeError(
            f'deploy: config.yaml 缺少 {marker!r} 标记，无法重写为 BACMAP_HOME'
        )
    cfg.write_text(rewritten)

    stamp.write_text(pkg_hash)
    return DEPLOYED_DIR


def _env_with_src() -> dict[str, str]:
    """snakemake 及其 shell 子进程必须能 import bacmap（未 pip install 的部署形态）。"""
    import os
    import sys

    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src_root + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    bin_dir = str(Path(sys.executable).resolve().parent)
    env["PATH"] = bin_dir + ":" + env.get("PATH", "")
    return env


class WorkflowRunner:
    """Snakemake CLI 的唯一调用口（ADR-02：仅本模块可调 Snakemake）。"""

    def __init__(self, deployed_dir: Path | None = None, timeout: int = 7200) -> None:
        self.dir = Path(deployed_dir) if deployed_dir else deploy()
        self.timeout = timeout

    def run(
        self,
        targets: list[str],
        cores: int = 8,
        config_overrides: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [
            "snakemake",
            "-s",
            str(self.dir / "Snakefile"),
            "--cores",
            str(cores),
            "--rerun-incomplete",
            "--printshellcmds",
        ]
        if config_overrides:
            cmd += ["--config"] + [f"{k}={v}" for k, v in config_overrides.items()]
        cmd += targets
        return subprocess.run(
            cmd,
            cwd=str(self.dir),
            timeout=timeout or self.timeout,
            text=True,
            capture_output=True,
            env=_env_with_src(),
        )

    def dry_run(self, targets: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        cmd = ["snakemake", "-s", str(self.dir / "Snakefile"), "-n", "-p"]
        if targets:
            cmd += targets
        return subprocess.run(
            cmd, cwd=str(self.dir), text=True, capture_output=True, timeout=300, env=_env_with_src()
        )
