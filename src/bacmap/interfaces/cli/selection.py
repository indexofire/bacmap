"""``bacmap selection`` — inspect and edit the per-tool reference overlay.

``tool_selection.yaml`` selects gspec databases and gmlst typing modes/schemes
per species/sample.  ``bacmap db`` remains a gspec-only alias (the parser
defaults ``--tool`` to ``gspec``).  The packaged ``pathogens.yaml`` is never
edited; this CLI writes ``$BACMAP_HOME/config/tool_selection.yaml`` atomically.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bacmap.core.pathogen_registry import load_registry
from bacmap.core.species_codes import UNK
from bacmap.core.tool_selection import (
    DEFAULT_SELECTION_REL,
    LEGACY_SELECTION_REL,
    GmlstMode,
    GmlstPlan,
    GmlstSelection,
    GspecSelection,
    SelectionError,
    SpeciesSelection,
    ToolSelection,
    is_legacy_path,
    load_selection,
    load_selection_data,
    resolve_selection_path,
    selection_to_yaml,
    write_selection,
)
from bacmap.core.tool_selection_validate import (
    GmlstScheme,
    ValidationReport,
    build_options,
    catalog_hash,
    diff_against_defaults,
    gmlst_catalog_hash,
    validate_selection,
)
from bacmap.tools.tool_catalog import (
    fetch_gmlst_schemes,
    fetch_gspec_catalog,
    options_payload,
)

_TOOL_CHOICES = ("gspec", "gmlst", "all")


def _emit_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _console() -> Any:
    from rich.console import Console

    return Console()


def _safe(value: Any) -> str:
    from rich.markup import escape

    return escape(str(value))


def _warn_legacy(legacy: bool) -> None:
    if legacy:
        _console().print(
            "[#d29922]正在使用旧 db_selection.yaml（gspec-only）；"
            "建议迁移到 tool_selection.yaml[/]"
        )


def _target_path(args: Any) -> Path:
    explicit = str(getattr(args, "selection", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    for env_name in ("BACMAP_TOOL_SELECTION", "BACMAP_DB_SELECTION"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            return Path(env_value).expanduser()
    return Path(args.home).expanduser() / DEFAULT_SELECTION_REL


def _load(args: Any) -> ToolSelection:
    return load_selection(
        str(getattr(args, "selection", "") or "") or None,
        home=Path(args.home).expanduser(),
    )


def _gspec_catalog(args: Any) -> dict[str, Any]:
    return fetch_gspec_catalog(datadir=str(getattr(args, "datadir", "") or "") or None)


def _gmlst_catalog(args: Any) -> dict[str, GmlstScheme]:
    return fetch_gmlst_schemes(
        downloaded_only=bool(getattr(args, "downloaded_only", False))
    )


def _sample_species(home: Path) -> dict[str, str]:
    """Read the deployed samples.tsv (if any) for sample-aware validation."""
    path = home / "workflows" / "bacmap" / "config" / "samples.tsv"
    if not path.is_file():
        return {}
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("sample") or "").strip(): str(row.get("species") or "").strip()
            for row in csv.DictReader(handle, delimiter="\t")
            if str(row.get("sample") or "").strip()
        }


def _species_code(value: str) -> str:
    registry = load_registry()
    if value.strip().upper() == UNK:
        return UNK
    code = registry.resolve(value)
    if code is None:
        raise SystemExit(f"未知物种：{value!r}（用 `bacmap selection options` 查看可用码）")
    return code


def _print_gspec_option(row: Any) -> None:
    from rich.table import Table

    console = _console()
    console.print(
        f"[bold]{_safe(row.code)}[/bold]  {_safe(row.display_name)}  "
        f"默认={_safe(', '.join(row.defaults) or '-')}  "
        f"生效={_safe(', '.join(row.effective) or '-')}"
    )
    table = Table(box=None, show_header=True, header_style="bold")
    for column in ("#", "选", "默认", "库", "kind", "typing", "installed", "license", "说明"):
        table.add_column(column)
    for index, db in enumerate(row.databases, start=1):
        table.add_row(
            str(index),
            "x" if db.selected else "",
            "x" if db.default else "",
            _safe(db.name),
            _safe(db.kind or "-"),
            "yes" if db.typing else "-",
            "yes" if db.installed else "no",
            _safe(db.license or "-"),
            _safe(db.description),
        )
    console.print(table)


def _print_gmlst_option(row: Any) -> None:
    from rich.table import Table

    console = _console()
    gmlst = row.gmlst
    console.print(
        f"[bold]{_safe(row.code)}[/bold]  {_safe(row.display_name)}  "
        f"gmlst 默认={_safe(','.join(gmlst.defaults.modes) or '-')}  "
        f"生效={_safe(','.join(gmlst.effective.modes) or '-')}"
    )
    table = Table(box=None, show_header=True, header_style="bold")
    for column in ("模式", "默认 scheme", "生效 scheme", "选", "scheme 类型", "下载"):
        table.add_column(column)
    for mode in ("mlst", "cgmlst", "wgmlst", "tgmlst"):
        selected = mode in gmlst.effective.modes
        scheme = gmlst.effective.schemes.get(mode, "")
        default = gmlst.defaults.schemes.get(mode, "")
        entry = next((s for s in gmlst.schemes if s.name == scheme), None)
        table.add_row(
            mode,
            _safe(default or "-"),
            _safe(scheme or "-"),
            "x" if selected else "",
            _safe(entry.scheme_type if entry else "-"),
            "yes" if entry and entry.downloaded else "no" if entry else "-",
        )
    console.print(table)
    if gmlst.schemes and len(gmlst.schemes) > 4:
        names = ", ".join(s.name for s in gmlst.schemes[:12])
        console.print(f"  可选 scheme（前 12 个）：{_safe(names)}")


def run_selection_path(args: Any) -> None:
    resolved = resolve_selection_path(
        str(getattr(args, "selection", "") or "") or None,
        home=Path(args.home).expanduser(),
    )
    target = _target_path(args)
    legacy = Path(args.home).expanduser() / LEGACY_SELECTION_REL
    payload = {
        "schema": "bacmap.tool_selection_path/1",
        "path": str(resolved or target),
        "exists": bool(resolved and resolved.is_file()),
        "legacy": bool(resolved and is_legacy_path(resolved)),
        "default": str(Path(args.home).expanduser() / DEFAULT_SELECTION_REL),
        "legacy_path": str(legacy),
        "legacy_exists": legacy.is_file(),
    }
    if args.json:
        _emit_json(payload)
        return
    status = (
        "（存在" + ("，legacy" if payload["legacy"] else "") + "）"
        if payload["exists"]
        else "（不存在，使用 registry 默认）"
    )
    _console().print(f"tool_selection: {_safe(payload['path'])}{status}")
    if payload["legacy_exists"]:
        _console().print(f"  旧文件仍存在：{_safe(payload['legacy_path'])}（新文件优先）")


def run_selection_options(args: Any) -> None:
    payload = options_payload(
        tool=str(getattr(args, "tool", "all") or "all"),
        species=str(args.species or ""),
        datadir=str(args.datadir or ""),
        selection_path=str(getattr(args, "selection", "") or ""),
        home=str(args.home),
        include_remote_schemes=not bool(getattr(args, "downloaded_only", False)),
    )
    if args.json:
        _emit_json(payload)
        return
    console = _console()
    _warn_legacy(bool(payload.get("legacy_selection")))
    selected_tool = str(getattr(args, "tool", "all") or "all")
    if not payload["catalog_available"] and selected_tool in ("gspec", "all"):
        console.print("[#d29922]gspec catalog 不可用：无法校验库名/kind/typing[/]")
    if not payload["gmlst_catalog_available"] and selected_tool in ("gmlst", "all"):
        console.print("[#d29922]gmlst catalog 不可用：无法校验 scheme 名/类型[/]")
    if not args.species:
        from rich.table import Table

        table = Table(title="物种 → 工具选择（--species CODE 看详情）", box=None)
        for column in ("code", "物种", "gspec 默认", "gspec 生效", "gmlst 生效"):
            table.add_column(column)
        for row in payload["species"]:
            table.add_row(
                str(row["code"]),
                _safe(row["display_name"]),
                _safe(", ".join(row["defaults"]) or "-"),
                _safe(", ".join(row["effective"]) or "-"),
                _safe(",".join(row["gmlst"]["effective"]["modes"]) or "-"),
            )
        console.print(table)
        return
    from bacmap.core.tool_selection_validate import SpeciesOption

    for raw_row in payload["species"]:
        row = SpeciesOption.model_validate(raw_row)
        if str(getattr(args, "tool", "all")) in ("gspec", "all"):
            _print_gspec_option(row)
        if str(getattr(args, "tool", "all")) in ("gmlst", "all"):
            _print_gmlst_option(row)


def run_selection_show(args: Any) -> None:
    selection = _load(args)
    registry = load_registry()
    species_filter = str(getattr(args, "species", "") or "")
    code_filter = _species_code(species_filter) if species_filter else None
    rows: list[dict[str, Any]] = []
    for code, spec in sorted(registry.pathogens.items()):
        if code_filter is not None and code != code_filter:
            continue
        defaults = list(spec.gspec_screens)
        effective = selection.effective_gspec_databases(code, registry=registry)
        gmlst_defaults = selection.effective_gmlst(code, registry=registry)
        # The effective gmlst plan is already merged with the registry defaults.
        gmlst_registry = _registry_gmlst(registry, code)
        rows.append(
            {
                "code": code,
                "display_name": spec.display_name,
                "defaults": defaults,
                "effective": effective,
                "gmlst_defaults": {
                    "modes": list(gmlst_registry.modes),
                    "schemes": dict(gmlst_registry.schemes),
                },
                "gmlst_effective": {
                    "modes": list(gmlst_defaults.modes),
                    "schemes": dict(gmlst_defaults.schemes),
                },
            }
        )
    if code_filter == UNK:
        effective = selection.effective_gspec_databases(UNK, registry=registry)
        gmlst_effective = selection.effective_gmlst(UNK, registry=registry)
        rows.append(
            {
                "code": UNK,
                "display_name": "未识别",
                "defaults": [],
                "effective": effective,
                "gmlst_defaults": {"modes": [], "schemes": {}},
                "gmlst_effective": {
                    "modes": list(gmlst_effective.modes),
                    "schemes": dict(gmlst_effective.schemes),
                },
            }
        )
    payload: dict[str, Any] = {
        "schema": "bacmap.tool_selection_show/1",
        "selection_path": str(resolve_selection_path(home=Path(args.home)) or ""),
        "legacy_selection": is_legacy_path(resolve_selection_path(home=Path(args.home))),
        "species": rows,
        "diff": diff_against_defaults(selection, registry=registry).model_dump(
            by_alias=True, mode="json"
        ),
    }
    if args.json:
        _emit_json(payload)
        return
    console = _console()
    _warn_legacy(bool(payload.get("legacy_selection")))
    from rich.table import Table

    table = Table(title="物种 → 工具选择", box=None)
    for column in ("code", "物种", "gspec 默认", "gspec 生效", "gmlst 生效"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row["code"],
            _safe(row["display_name"]),
            _safe(", ".join(row["defaults"]) or "-"),
            _safe(", ".join(row["effective"]) or "-"),
            _safe(",".join(row["gmlst_effective"]["modes"]) or "-"),
        )
    console.print(table)
    if args.diff:
        diff = payload["diff"]
        for row in diff["species"]:
            parts: list[str] = []
            if row["removed"]:
                parts.append(f"-{_safe(', '.join(row['removed']))}")
            if row["added"]:
                parts.append(f"+{_safe(', '.join(row['added']))}")
            if row.get("gmlst"):
                parts.append(
                    "gmlst="
                    + _safe(",".join(row["gmlst"]["effective"]["modes"]) or "-")
                )
            console.print(f"  {row['code']}: {' '.join(parts) or '(unchanged)'}")
        if diff["samples"]:
            samples = _safe(json.dumps(diff["samples"], ensure_ascii=False))
            console.print(f"  samples(gspec): {samples}")
        if diff["gmlst_samples"]:
            console.print(
                f"  samples(gmlst): {_safe(json.dumps(diff['gmlst_samples'], ensure_ascii=False))}"
            )


def _registry_gmlst(registry: Any, code: str) -> GmlstPlan:
    from bacmap.core.tool_selection import default_gmlst_plan

    return default_gmlst_plan(code, registry=registry)


def _print_report(report: ValidationReport) -> None:
    console = _console()
    for issue in report.errors:
        console.print(f"[red]ERROR[/red] {_safe(issue.code)}: {_safe(issue.message)}")
    for issue in report.warnings:
        console.print(f"[#d29922]WARN[/#d29922]  {_safe(issue.code)}: {_safe(issue.message)}")


def run_selection_validate(args: Any) -> None:
    explicit = str(getattr(args, "path", "") or "").strip()
    if explicit:
        path = explicit
        if not Path(path).is_file():
            raise SystemExit(f"tool selection not found: {path}")
    else:
        resolved = resolve_selection_path(home=Path(args.home).expanduser())
        path = str(resolved or _target_path(args))
    selection = load_selection(path)
    catalog = _gspec_catalog(args)
    gmlst_catalog = _gmlst_catalog(args)
    report = validate_selection(
        selection,
        catalog=catalog,
        gmlst_catalog=gmlst_catalog,
        sample_species=_sample_species(Path(args.home).expanduser()),
    )
    payload = {
        "schema": "bacmap.tool_selection_validation/1",
        "path": path,
        "exists": Path(path).is_file(),
        "legacy_selection": is_legacy_path(path),
        "ok": report.ok,
        "errors": [issue.model_dump() for issue in report.errors],
        "warnings": [issue.model_dump() for issue in report.warnings],
    }
    if args.json:
        _emit_json(payload)
    else:
        _warn_legacy(bool(payload.get("legacy_selection")))
        _print_report(report)
        _console().print("OK" if report.ok else "FAILED")
    if not report.ok:
        raise SystemExit(1)


def _parse_schemes(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit("--schemes 格式：mlst=name,cgmlst=name")
        key, scheme = item.split("=", 1)
        key = key.strip()
        if key not in {"mlst", "cgmlst", "wgmlst"}:
            raise SystemExit(f"无效的 gmlst scheme key：{key!r}")
        out[key] = scheme.strip()
    return out


def _parse_modes(value: str) -> list[GmlstMode]:
    modes = [item.strip() for item in value.split(",") if item.strip()]
    allowed = {"mlst", "cgmlst", "wgmlst", "tgmlst"}
    bad = [mode for mode in modes if mode not in allowed]
    if bad:
        raise SystemExit(f"无效的 gmlst mode：{bad!r}（可选 {sorted(allowed)}）")
    # Runtime-validated against ``allowed``; the cast only narrows str → Literal.
    from typing import cast

    return cast("list[GmlstMode]", list(dict.fromkeys(modes)))


def _entry_for(selection: ToolSelection, code: str) -> SpeciesSelection:
    return selection.species.get(code) or SpeciesSelection()


def _update_entry(
    selection: ToolSelection,
    code: str,
    *,
    gspec: GspecSelection | None = None,
    gmlst: GmlstSelection | None = None,
) -> ToolSelection:
    current = _entry_for(selection, code)
    updated = current.model_copy(
        update={
            "gspec": gspec if gspec is not None else current.gspec,
            "gmlst": gmlst if gmlst is not None else current.gmlst,
        }
    )
    species = dict(selection.species)
    species[code] = updated
    return selection.model_copy(update={"species": species})


def _interactive_gspec(args: Any, selection: ToolSelection, code: str) -> ToolSelection:
    from rich.prompt import Prompt

    console = _console()
    catalog = _gspec_catalog(args)
    doc = build_options(selection, catalog=catalog, species=code)
    row = doc.species[0]
    _print_gspec_option(row)
    answer = Prompt.ask(
        "输入要启用的 gspec 编号（逗号分隔；all=全选，none=全不选，回车=保持当前）",
        default="",
        console=console,
    ).strip()
    if not answer:
        return selection
    if answer.lower() == "all":
        chosen = [db.name for db in row.databases]
    elif answer.lower() == "none":
        chosen = []
    else:
        chosen = []
        for token in answer.split(","):
            token = token.strip()
            if not token.isdigit() or not (1 <= int(token) <= len(row.databases)):
                raise SystemExit(f"无效编号：{token!r}")
            chosen.append(row.databases[int(token) - 1].name)
    return _update_entry(
        selection,
        code,
        gspec=GspecSelection(mode=args.mode, databases=chosen),
    )


def _interactive_gmlst(args: Any, selection: ToolSelection, code: str) -> ToolSelection:
    from rich.prompt import Prompt

    console = _console()
    doc = build_options(selection, gmlst_catalog=_gmlst_catalog(args), species=code)
    row = doc.species[0]
    _print_gmlst_option(row)
    answer = Prompt.ask(
        "输入要启用的 gmlst 模式（逗号分隔：mlst,cgmlst,wgmlst,tgmlst；回车=保持当前）",
        default="",
        console=console,
    ).strip()
    if not answer:
        return selection
    modes = _parse_modes(answer)
    schemes: dict[str, str] = {}
    for mode in modes:
        if mode == "tgmlst":
            continue
        default = row.gmlst.effective.schemes.get(mode, "")
        schemes[mode] = Prompt.ask(
            f"{mode} scheme", default=default, console=console
        ).strip()
    return _update_entry(
        selection,
        code,
        gmlst=GmlstSelection(mode=args.mode, modes=modes, schemes=schemes),
    )


def _selection_from_file(args: Any) -> ToolSelection:
    source = str(getattr(args, "from_json", "") or "").strip()
    if source:
        try:
            raw = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SelectionError(f"cannot read proposal {source}: {exc}") from exc
        return load_selection_data(raw, source=source)
    source = str(getattr(args, "from_yaml", "") or "").strip()
    if source:
        import yaml

        try:
            raw = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise SelectionError(f"cannot read proposal {source}: {exc}") from exc
        return load_selection_data(raw, source=source)
    raise SelectionError("internal: no proposal file")


def _apply_noninteractive(
    args: Any, selection: ToolSelection, tool: str
) -> ToolSelection:
    if tool == "gmlst" and str(getattr(args, "databases", "") or "").strip():
        raise SystemExit("--databases 只用于 --tool gspec")
    if tool == "gspec" and str(getattr(args, "modes", "") or "").strip():
        raise SystemExit("--modes/--schemes 只用于 --tool gmlst")
    species_value = str(getattr(args, "species", "") or "").strip()
    if not species_value:
        raise SystemExit("--json 模式需要 --species 或 --from-json/--from-yaml")
    code = _species_code(species_value)
    if tool in ("gspec", "all") and str(getattr(args, "databases", "") or "").strip():
        chosen = [
            item.strip()
            for item in str(args.databases).split(",")
            if item.strip()
        ]
        selection = _update_entry(
            selection,
            code,
            gspec=GspecSelection(mode=args.mode, databases=chosen),
        )
    if tool in ("gmlst", "all") and str(getattr(args, "modes", "") or "").strip():
        modes = _parse_modes(str(args.modes))
        schemes = _parse_schemes(str(getattr(args, "schemes", "") or ""))
        selection = _update_entry(
            selection,
            code,
            gmlst=GmlstSelection(mode=args.mode, modes=modes, schemes=schemes),
        )
    return selection


def _interactive_select(
    args: Any, selection: ToolSelection, tool: str
) -> ToolSelection:
    from rich.prompt import Prompt

    species_value = str(getattr(args, "species", "") or "").strip()
    if not species_value:
        species_value = Prompt.ask("物种码", console=_console())
    code = _species_code(species_value)
    if tool in ("gspec", "all"):
        selection = _interactive_gspec(args, selection, code)
    if tool in ("gmlst", "all"):
        selection = _interactive_gmlst(args, selection, code)
    return selection


def _with_meta(
    selection: ToolSelection,
    catalog: dict[str, Any],
    gmlst_catalog: dict[str, GmlstScheme],
    registry: Any,
) -> ToolSelection:
    return selection.model_copy(
        update={
            "meta": selection.meta.model_copy(
                update={
                    "generated_by": "cli",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "approved_by": os.environ.get("USER", ""),
                    "registry_signature": registry.signature(),
                    "gspec_catalog_hash": catalog_hash(catalog) if catalog else "",
                    "gmlst_catalog_hash": gmlst_catalog_hash(gmlst_catalog)
                    if gmlst_catalog
                    else "",
                }
            )
        }
    )


def _preview_or_write(
    args: Any, selection: ToolSelection, report: ValidationReport
) -> None:
    target = _target_path(args)
    if args.dry_run:
        if args.json:
            _emit_json(
                {
                    "schema": "bacmap.tool_selection_proposal/1",
                    "path": str(target),
                    "ok": True,
                    "warnings": [issue.model_dump() for issue in report.warnings],
                    "document": selection.model_dump(by_alias=True, mode="json"),
                    "yaml": selection_to_yaml(selection),
                }
            )
        else:
            _print_report(report)
            print(selection_to_yaml(selection))
        return

    if not args.yes:
        from rich.prompt import Confirm

        _print_report(report)
        _console().print(selection_to_yaml(selection))
        if not Confirm.ask(f"写入 {target}？", default=False, console=_console()):
            _console().print("已取消。")
            return

    written = write_selection(selection, target, backup=True)
    payload = {
        "schema": "bacmap.tool_selection_write/1",
        "path": str(written),
        "ok": True,
        "warnings": [issue.model_dump() for issue in report.warnings],
    }
    if args.json:
        _emit_json(payload)
    else:
        _print_report(report)
        _console().print(f"已写入 {_safe(written)}（旧文件保留为 .bak）")


def run_selection_select(args: Any) -> None:
    selection = _load(args)
    tool = str(getattr(args, "tool", "all") or "all")
    if tool not in _TOOL_CHOICES:
        raise SystemExit(f"未知 tool：{tool!r}")
    if getattr(args, "from_json", "") or getattr(args, "from_yaml", ""):
        selection = _selection_from_file(args)
    elif (
        str(getattr(args, "databases", "") or "").strip()
        or str(getattr(args, "modes", "") or "").strip()
    ):
        selection = _apply_noninteractive(args, selection, tool)
    else:
        if args.json:
            raise SystemExit("--json 模式需要 --databases 或 --modes")
        selection = _interactive_select(args, selection, tool)

    catalog = _gspec_catalog(args)
    gmlst_catalog = _gmlst_catalog(args)
    selection = _with_meta(selection, catalog, gmlst_catalog, load_registry())
    report = validate_selection(
        selection,
        catalog=catalog,
        gmlst_catalog=gmlst_catalog,
        sample_species=_sample_species(Path(args.home).expanduser()),
    )
    if not report.ok:
        _print_report(report)
        raise SystemExit(1)
    _preview_or_write(args, selection, report)
