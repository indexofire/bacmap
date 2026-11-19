"""标准分析所需的本地数据库预检（v1.10.38）。

只回答一个问题：**按本次样本与阶段，哪些外部资源缺失**。这里不做下载——
下载属于受控 fetch 阶段（网络/磁盘/许可证都需要人确认），预检只给出可执行的
安装命令，让任务在进入 Snakemake 前秒级失败，而不是跑到一半才报缺库。

资源口径：
- 注释（Bakta/eggNOG）只在 ``annotation=True`` 且部署配置/环境未关闭时要求；
- gmlst scheme 按 registry + ``tool_selection.yaml`` 的生效方案检查缓存；
- gspec 库按生效库清单检查 ``GSPEC_DATADIR``（缺省 ``~/.local/share/gspec/db``）；
- AMRFinderPlus 数据库对每个样本都是硬依赖（专属规则会直接调用）；
- SNP 参考基因组只在本次包含 >=2 个 reads 样本的分组时要求。
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from bacmap.core.pathogen_registry import PathogenRegistry, load_registry
from bacmap.core.tool_selection import ToolSelection, load_selection
from bacmap.core.tool_selection_validate import GmlstScheme, scheme_matches_species

_TRUTHY_OFF = {"0", "false", "no", "off"}

# 分型类 scheme 的 scheme_type；wgmlst 也走同一条 gmlst 缓存。
_TYPING_SCHEME_TYPES = ("mlst", "cgmlst", "wgmlst")

# 上游 catalog 把"非本种"方案也挂在同一属名 organism 下
# （Campylobacter 的 9 个 non-jejuni/coli 方案 organism 全是
# "Campylobacter non-jejuni/coli"），仅靠标签 token 会误命中，需要显式排除。
_NEGATED_SPECIES = re.compile(r"\bnon\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResourceStatus:
    """一个外部资源的检查结果（CLI/JSON 与 Snakemake preflight 共用）。"""

    name: str
    kind: str
    path: str
    required_by: tuple[str, ...]
    install: str
    present: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "required_by": list(self.required_by),
            "install": self.install,
            "present": self.present,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PreflightReport:
    """预检报告：``ok=False`` 时任务必须 fail-fast。

    ``decisions`` 是"可以装、但没启用"的可选项（v1.10.46）：它们不会让任务失败
    （本物种不跑 MLST 可能是刻意选择），但必须让人看见——否则该步骤会写成
    ``NO_SCHEME`` 并静默出 N/A，看上去和"本物种没有 MLST"完全一样。
    """

    ok: bool
    checked: tuple[ResourceStatus, ...] = field(default_factory=tuple)
    skipped: tuple[ResourceStatus, ...] = field(default_factory=tuple)
    decisions: tuple[ResourceStatus, ...] = field(default_factory=tuple)
    warning: str = ""

    @property
    def missing(self) -> tuple[ResourceStatus, ...]:
        return tuple(item for item in self.checked if not item.present)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "missing": [item.as_dict() for item in self.missing],
            "checked": [item.as_dict() for item in self.checked],
            "skipped": [item.as_dict() for item in self.skipped],
            "decisions": [item.as_dict() for item in self.decisions],
            "warning": self.warning,
        }

    def failure_message(self) -> str:
        if self.ok:
            return ""
        lines = ["missing databases:"]
        for item in self.missing:
            lines.append(f"- {item.name} ({item.kind}) → {item.install}")
        if self.warning:
            lines.append(self.warning)
        return "\n".join(lines)

    def decision_message(self) -> str:
        """人可读的"可装未启用"清单；空字符串表示没有待决项。"""
        if not self.decisions:
            return ""
        lines = ["typing schemes available but not enabled:"]
        for item in self.decisions:
            lines.append(f"- {item.name} ({item.kind}) → {item.install}")
            if item.detail:
                lines.append(f"  {item.detail}")
        return "\n".join(lines)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """与 Snakefile 双 configfile 语义一致的深合并（本地覆盖优先）。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def workflow_config(home: Path) -> dict[str, Any]:
    """读取部署目录 config.yaml + config.local.yaml（core 不依赖上层模块）。"""
    cfg_dir = Path(home) / "workflows" / "bacmap" / "config"
    config: dict[str, Any] = {}
    for name in ("config.yaml", "config.local.yaml"):
        path = cfg_dir / name
        if not path.is_file():
            continue
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(loaded, dict):
            config = deep_merge(config, loaded)
    return config


def _resolve_path(raw: str | Path, home: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path(home) / path


def _annotation_enabled(annotation: bool, config: dict[str, Any], env: Mapping[str, str]) -> bool:
    configured = bool((config.get("tools", {}).get("annotation", {}) or {}).get("enabled", True))
    environment = str(env.get("BACMAP_ANNOTATION_ENABLED", "1")).strip().lower()
    return annotation and configured and environment not in _TRUTHY_OFF


def _gmlst_cache_roots(env: Mapping[str, str]) -> list[Path]:
    if env.get("GMLST_CACHE_DIR"):
        # gmlst 的解析顺序：显式环境变量优先于 env.sh / CONDA_PREFIX。
        return [Path(env["GMLST_CACHE_DIR"]).expanduser()]
    roots: list[Path] = []

    def add(path: Path) -> None:
        if path not in roots:
            roots.append(path)

    # gmlst 的 entrypoint 会读取 ~/.config/gmlst/env.sh；这里解析同一个事实来源，
    # 避免预检与实际运行看到两个不同的缓存位置。
    candidates = (
        Path.home() / ".config" / "gmlst" / "env.sh",
        Path.home() / ".gmlst" / "env.sh",
    )
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        pattern = r'^export\s+GMLST_CACHE_DIR=(?:"([^"]+)"|\'([^\']+)\'|(\S+))'
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            add(Path(next(value for value in match.groups() if value)).expanduser())
    add(Path.home() / ".cache" / "gmlst")
    add(Path.home() / ".local" / "share" / "gmlst")
    if env.get("CONDA_PREFIX"):
        add(Path(env["CONDA_PREFIX"]) / "share" / "gmlst")
    return roots


def _gmlst_scheme_path(scheme: str, roots: list[Path]) -> Path | None:
    for root in roots:
        for provider_dir in sorted(root.iterdir()) if root.is_dir() else []:
            candidate = provider_dir / scheme / ".meta.json"
            if candidate.is_file():
                return candidate.parent
    return None


def _amrfinder_db(base: Path) -> Path | None:
    if (base / "AMR_CDS.fa").is_file():
        return base
    if not base.is_dir():
        return None
    versions = sorted(
        path for path in base.iterdir()
        if path.is_dir() and (path / "AMR_CDS.fa").is_file()
    )
    return versions[-1] if versions else None


def _sample_rows(home: Path, samples: list[str]) -> dict[str, dict[str, str]]:
    tsv = Path(home) / "workflows" / "bacmap" / "config" / "samples.tsv"
    if not tsv.is_file():
        return {}
    try:
        with tsv.open("r", encoding="utf-8", newline="") as handle:
            rows = {row.get("sample", ""): row for row in csv.DictReader(handle, delimiter="\t")}
    except OSError:
        return {}
    wanted = set(samples)
    return {sample: row for sample, row in rows.items() if sample in wanted}


def _status(
    *,
    name: str,
    kind: str,
    path: Path,
    required_by: tuple[str, ...],
    install: str,
    present: bool,
    detail: str = "",
) -> ResourceStatus:
    return ResourceStatus(
        name=name,
        kind=kind,
        path=str(path),
        required_by=required_by,
        install=install,
        present=present,
        detail=detail,
    )


def _gmlst_catalog_snapshot() -> dict[str, GmlstScheme]:
    """实时 gmlst 目录（name → scheme）；gmlst 不可用时返回 ``{}``。

    延迟导入：``bacmap.tools.tool_catalog`` 依赖 core，模块级导入会成环。
    只读本地 catalog 文件（``gmlst scheme list``），无网络、无下载。
    """
    try:
        from bacmap.tools.tool_catalog import fetch_gmlst_schemes
    except Exception:  # pragma: no cover - 依赖缺失时静默降级
        return {}
    try:
        return fetch_gmlst_schemes()
    except Exception:  # pragma: no cover - subprocess/解析失败不应打断预检
        return {}


def _species_labels(registry: PathogenRegistry, code: str | None) -> list[str]:
    """物种码 → gside 标签（用于和 catalog 的 organism 字段做启发式匹配）。"""
    if not code:
        return []
    spec = registry.pathogens.get(code)
    return list(spec.gside_labels) if spec is not None else []


def _typing_scheme_candidates(
    catalog: Mapping[str, GmlstScheme],
    labels: list[str],
    *,
    modes: tuple[str, ...] = _TYPING_SCHEME_TYPES,
) -> list[GmlstScheme]:
    """catalog 中"看起来属于该物种"的分型方案（启发式，仅供参考）。

    候选只用于"告诉你上游有这些方案"，绝不自动选中——真正的启用仍要人经
    ``bacmap selection select`` 写入 overlay。
    """
    wanted = {mode.lower() for mode in modes}
    found: list[GmlstScheme] = []
    for entry in catalog.values():
        if entry.scheme_type.lower() not in wanted:
            continue
        if not scheme_matches_species(entry, labels):
            continue
        if _NEGATED_SPECIES.search(f"{entry.organism} {entry.display_name}"):
            continue
        found.append(entry)
    return sorted(found, key=lambda item: (item.scheme_type, item.name))


def preflight_resources(  # noqa: C901
    home: Path,
    samples: list[str],
    *,
    annotation: bool = True,
    config: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    registry: PathogenRegistry | None = None,
    selection: ToolSelection | None = None,
    stages: set[str] | None = None,
    gmlst_catalog: Mapping[str, GmlstScheme] | None = None,
) -> PreflightReport:
    """检查本次 analyze 所需的本地资源；只读、无网络、无副作用。

    ``gmlst_catalog``（v1.10.46）用于反向检查"catalog 里有方案、但本物种没声明"：
    这种缺口既不算缺失（没声明 = 没要求）也不失败，但会让 MLST 静默写成
    ``NO_SCHEME``，所以以 ``decisions`` 单独列出。省略时按需读取 gmlst 目录。
    """
    home = Path(home)
    env = dict(os.environ) if env is None else dict(env)
    config = workflow_config(home) if config is None else dict(config or {})
    registry = registry or load_registry()
    selection = selection or load_selection(home=home)
    rows = _sample_rows(home, samples)
    if not rows:
        # 测试/空 home 没有 samples.tsv：预检无法推断物种需求，交给后续登记/管线。
        return PreflightReport(
            ok=True, warning="samples.tsv unavailable; resource preflight skipped"
        )

    checked: list[ResourceStatus] = []
    skipped: list[ResourceStatus] = []
    # scheme → 聚合后的待决项；多株、多种共用同一 scheme 时也只报一次
    # （C. jejuni / C. coli 共用 campylobacter_10，按物种重复会刷屏）。
    pending: dict[str, dict[str, Any]] = {}
    catalog: Mapping[str, GmlstScheme] | None = gmlst_catalog

    def wants(stage: str) -> bool:
        return stages is None or stage in stages

    # ---- 注释（可选阶段） ------------------------------------------------
    if wants("annotation") and _annotation_enabled(annotation, config, env):
        tools = config.get("tools", {}).get("annotation", {}) or {}
        bakta = _resolve_path(
            env.get("BACMAP_BAKTA_DB")
            or tools.get("bakta", {}).get("db")
            or home / "refs" / "bakta" / "db-light",
            home,
        )
        checked.append(_status(
            name="bakta_db", kind="annotation_db", path=bakta,
            required_by=tuple(sorted(rows)),
            install="pixi run python scripts/setup_annotation_dbs.py --bakta-only",
            present=(bakta / "bakta.db").is_file(),
            detail="expects <dir>/bakta.db",
        ))
        eggnog = _resolve_path(
            env.get("BACMAP_EGGNOG_DATA_DIR")
            or tools.get("eggnog", {}).get("data_dir")
            or home / "refs" / "eggnog",
            home,
        )
        checked.append(_status(
            name="eggnog_data", kind="annotation_db", path=eggnog,
            required_by=tuple(sorted(rows)),
            install="pixi run python scripts/setup_annotation_dbs.py --eggnog-only",
            present=(eggnog / "eggnog.db").is_file()
                and (eggnog / "eggnog_proteins.dmnd").is_file(),
            detail="expects eggnog.db + eggnog_proteins.dmnd",
        ))
    else:
        skipped.append(_status(
            name="annotation_databases", kind="annotation_db", path=Path("-"),
            required_by=(), install="-", present=True,
            detail="annotation disabled for this run",
        ))

    # ---- gmlst 方案 / gspec 库 / AMR ------------------------------------
    roots = _gmlst_cache_roots(env)
    gspec_default = Path.home() / ".local" / "share" / "gspec" / "db"
    gspec_dir = Path(env.get("GSPEC_DATADIR", gspec_default)).expanduser()
    amr_raw = env.get("BACMAP_AMRFINDER_DB") or home / "data" / "db" / "amrfinderplus"
    amr_base = _resolve_path(amr_raw, home)
    amr_db = _amrfinder_db(amr_base)
    if wants("amr"):
        checked.append(_status(
            name="amrfinderplus_db", kind="amr_db", path=amr_db or amr_base,
            required_by=tuple(sorted(rows)),
            install="amrfinder_update --database <dir> or set BACMAP_AMRFINDER_DB",
            present=amr_db is not None,
            detail="expects AMR_CDS.fa (directly or in a version subdirectory)",
        ))

    # summary 的固定输入包含 vfdb/card/plasmidfinder（与物种无关的通用筛查），
    # 因此它们对所有样本都是硬依赖，而不是仅 registry 声明的种以下库。
    all_samples = tuple(sorted(rows))

    def require_gspec(database: str, required_by: tuple[str, ...]) -> None:
        db_dir = gspec_dir / database
        present = db_dir.is_dir() and (
            (db_dir / "gspec-manifest.json").is_file()
            or (db_dir / "features.json").is_file()
            or (db_dir / "records.jsonl").is_file()
        )
        checked.append(_status(
            name=f"gspec:{database}", kind="gspec_db", path=db_dir,
            required_by=required_by, install=f"gspec db fetch -d {database}",
            present=present,
        ))

    if wants("gspec"):
        for database in ("vfdb", "card", "plasmidfinder"):
            require_gspec(database, all_samples)

    typing_wanted = wants("mlst") or wants("cgmlst")

    def note_undeclared(sample: str, code: str | None, labels: list[str]) -> None:
        """记录"catalog 有、但本物种没声明"的分型方案（每 scheme 只记一次）。"""
        nonlocal catalog
        if catalog is None:
            catalog = _gmlst_catalog_snapshot()
        for entry in _typing_scheme_candidates(catalog, labels):
            item = pending.get(entry.name)
            if item is None:
                pending[entry.name] = {
                    "entry": entry,
                    "cached": _gmlst_scheme_path(entry.name, roots) is not None,
                    "samples": {sample},
                    "codes": {code or ""},
                }
            else:
                item["samples"].add(sample)
                item["codes"].add(code or "")

    for sample, row in sorted(rows.items()):
        code = registry.resolve(row.get("species", ""))

        plan = selection.effective_gmlst(code, sample=sample, registry=registry)
        if typing_wanted:
            modes = [mode for mode in plan.modes if mode in {"mlst", "cgmlst", "wgmlst"}]
        else:
            modes = []
        for mode in modes:
            scheme = plan.schemes.get(mode, "")
            if not scheme:
                continue
            scheme_path = _gmlst_scheme_path(scheme, roots)
            checked.append(_status(
                name=f"gmlst:{scheme}", kind="typing_scheme",
                path=scheme_path or Path("-"), required_by=(sample,),
                install=f"gmlst scheme download {scheme}",
                present=scheme_path is not None,
                detail="expects <cache>/<provider>/<scheme>/.meta.json",
            ))

        # 反向检查（v1.10.46）：本物种一个分型方案都没声明，但上游 catalog 里
        # 明明有 → 不失败，但必须让人看见，否则该步会静默写成 NO_SCHEME。
        if typing_wanted and not modes:
            labels = _species_labels(registry, code)
            if labels:
                note_undeclared(sample, code, labels)

        if wants("gspec"):
            databases = selection.effective_gspec_databases(
                code, sample=sample, registry=registry
            )
            for database in databases:
                require_gspec(database, (sample,))

    # ---- SNP cohort 参考基因组（reads 且 >=2 样本才参与联合分析） ---------
    reads_by_group: dict[str, list[str]] = {}
    for sample, row in sorted(rows.items()) if wants("snp") else []:
        code = registry.resolve(row.get("species", ""))
        if not code or not (row.get("R1") or "").strip():
            continue
        group = registry.pathogens[code].snp_group
        if group:
            reads_by_group.setdefault(group, []).append(sample)
    for group, members in sorted(reads_by_group.items()):
        if len(members) < 2:
            continue
        info = registry.snp_groups().get(group)
        if not info:
            continue
        reference = _resolve_path(info["ref"], home)
        checked.append(_status(
            name=f"snp_reference:{group}", kind="reference_genome", path=reference,
            required_by=tuple(members),
            install="python workflows/bacmap/scripts/fetch_reference_genomes.py "
                    "--manifest workflows/bacmap/config/reference_accessions.yaml "
                    f"--out-dir {home / 'data' / 'reference' / 'genomes'} "
                    f"--refs-dir {home / 'refs'}",
            present=reference.is_file(),
        ))

    decisions: list[ResourceStatus] = []
    for scheme, item in sorted(pending.items()):
        entry = item["entry"]
        cached = bool(item["cached"])
        owners = "、".join(sorted(code for code in item["codes"] if code)) or "本物种"
        if cached:
            detail = (
                f"catalog 有 {entry.scheme_type} scheme 且已缓存，但 {owners} 未声明 → "
                "该步骤会写 N/A；用 bacmap selection select 启用"
            )
        else:
            detail = (
                f"catalog 有 {entry.scheme_type} scheme，但 {owners} 未声明也未缓存 → "
                "该步骤会写 N/A；下载后仍需用 bacmap selection select 启用"
            )
        decisions.append(_status(
            name=f"gmlst:{scheme}", kind="typing_scheme",
            path=_gmlst_scheme_path(scheme, roots) or Path("-"),
            required_by=tuple(sorted(item["samples"])),
            install=f"gmlst scheme download {scheme}",
            present=cached,
            detail=detail,
        ))

    return PreflightReport(
        ok=all(item.present for item in checked),
        checked=tuple(checked),
        skipped=tuple(skipped),
        decisions=tuple(decisions),
    )
