"""沙箱访问面构建（A+D）：只读挂载 + 与真实后端一致的 context。

- 容器后端（apptainer/podman）：数据只读挂载到**稳定 guest 路径**
  （results → ``/data/results``、GOM → ``/data/gom.sqlite``、数据集 → ``/input/<id>``），
  ``context.json`` 给 guest 路径。
- 直通后端（无沙箱且 ``BACMAP_ALLOW_UNSANDBOXED=1``，仅开发）：不挂载，
  ``context.json`` 给宿主路径。
- fs_scope 由 ``SandboxSpec.allowed_readonly_roots`` 强制：只读挂载的宿主路径
  必须落在允许根内（results / GOM / 已登记数据集）。
"""

from __future__ import annotations

from pathlib import Path

from bacmap.store.datasets import Dataset

_CONTAINER_BACKENDS = {"apptainer", "podman"}


def build_access(
    backend: str,
    *,
    results_dir: Path,
    gom_db: Path,
    datasets: list[Dataset],
) -> tuple[dict[str, str], dict]:
    """返回 ``(readonly_mounts, context)``；context 内路径与后端一致。"""
    mounts: dict[str, str] = {}
    ctx: dict = {"backend": backend, "datasets": {}}

    if backend in _CONTAINER_BACKENDS:
        if results_dir.is_dir():
            mounts[str(results_dir)] = "/data/results"
            ctx["results_dir"] = "/data/results"
        if gom_db.is_file():
            mounts[str(gom_db)] = "/data/gom.sqlite"
            ctx["gom_db"] = "/data/gom.sqlite"
        for ds in datasets:
            mounts[ds.resolved_path] = ds.mount_guest
            ctx["datasets"][ds.dataset_id] = ds.mount_guest
    else:
        ctx["results_dir"] = str(results_dir)
        if gom_db.is_file():
            ctx["gom_db"] = str(gom_db)
        for ds in datasets:
            ctx["datasets"][ds.dataset_id] = ds.resolved_path
    return mounts, ctx


def allowed_roots(
    *, results_dir: Path, gom_db: Path, datasets: list[Dataset]
) -> tuple[Path, ...]:
    """只读挂载的允许根（fs_scope 白名单，供 SandboxSpec 校验）。"""
    roots = [results_dir, gom_db, *(Path(ds.resolved_path) for ds in datasets)]
    return tuple(roots)
