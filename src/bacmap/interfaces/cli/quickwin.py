"""``bacmap`` 0.1.4 新增命令：stats / detect / species / reference / completion。

对应 dev/PLAN.md #4（FASTQ 平台探测）、#13（物种命名查询）、#18（全库统计）、
#19（参考基因组）、#12（shell 补全）。

shell 补全脚本 inherently 含长行，模块级豁免 E501。
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
from typing import Any

from bacmap.interfaces.i18n import T


def run_stats(args: argparse.Namespace) -> None:
    from bacmap.interfaces.stats_summary import gather_stats, stats_markdown

    stats = gather_stats(args.home)
    if args.json:
        import json

        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    print(stats_markdown(stats))


def run_detect(args: argparse.Namespace) -> None:
    from bacmap.core.fastq_probe import detect_directory

    try:
        result = detect_directory(args.directory, sample_reads=args.sample_reads)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"{result['directory']}: platform={result['platform']} ({result['n_files']} files)")
    for f in result["files"]:
        print(
            f"  {f['file']:<40} median={f['median_len']:>6} p10={f['p10_len']:>6} "
            f"p90={f['p90_len']:>6} max={f['max_len']:>7} -> {f['vote']}"
        )
    print(f"  note: {result['note']}")


def run_species_ls(args: argparse.Namespace) -> None:
    from bacmap.core.pathogen_registry import load_registry

    registry = load_registry()
    rows = []
    for code, entry in sorted(registry.pathogens.items()):
        if not entry.enabled:
            continue
        if args.query and args.query.lower() not in (
            code.lower(),
            entry.display_name.lower(),
            " ".join(entry.gside_labels).lower(),
        ):
            continue
        rows.append(
            {
                "code": code,
                "display_name": entry.display_name,
                "gside_labels": list(entry.gside_labels),
                "mlst_scheme": entry.mlst_scheme or "",
                "snp_group": entry.snp_group or "",
            }
        )
    if args.json:
        import json

        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    from rich import box
    from rich.table import Table

    table = Table(
        title=T(f"Species registry ({len(rows)})", f"物种注册表（{len(rows)}）"),
        box=box.SQUARE,
    )
    for col in ("code", "display_name", "gside_labels", "mlst", "snp_group"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["code"]), str(r["display_name"]), str(",".join(r["gside_labels"])),
            str(r["mlst_scheme"]), str(r["snp_group"]),
        )
    from bacmap.interfaces.cli.main import _console

    _console().print(table)


def run_species_resolve(args: argparse.Namespace) -> None:
    from bacmap.core.pathogen_registry import resolve_species

    code = resolve_species(args.name)
    if code is None:
        raise SystemExit(T(f"unknown species: {args.name}", f"未知物种：{args.name}"))
    import json

    print(json.dumps({"input": args.name, "code": code}, ensure_ascii=False))


def run_database_status(args: argparse.Namespace) -> None:
    """数据库/参考基因组预检（只读；缺库时退出码 1，便于 agent/CI 判断）。"""
    import csv
    import json
    from pathlib import Path

    from bacmap.core.pipeline.resources import preflight_resources

    home = Path(args.home).expanduser()
    if args.samples:
        samples = [item.strip() for item in args.samples.split(",") if item.strip()]
    else:
        samples = []
        tsv = home / "workflows" / "bacmap" / "config" / "samples.tsv"
        if tsv.is_file():
            try:
                with tsv.open("r", encoding="utf-8", newline="") as handle:
                    samples = [
                        row.get("sample", "")
                        for row in csv.DictReader(handle, delimiter="\t")
                        if row.get("sample")
                    ]
            except OSError:
                samples = []
    report = preflight_resources(home, samples, annotation=args.annotation)
    payload = report.as_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        state = "ok" if report.ok else "missing"
        print(T(f"database preflight: {state}", f"数据库预检：{state}"))
        for item in report.checked:
            mark = "OK" if item.present else "MISSING"
            print(f"  [{mark:<7}] {item.name:<28} {item.path}")
        for item in report.skipped:
            print(T(f"  [SKIP   ] {item.name}: {item.detail}", f"  [跳过   ] {item.name}：{item.detail}"))
        if report.decisions:
            print(T("  typing schemes available but not enabled:", "  有可用但未启用的分型方案："))
            for item in report.decisions:
                mark = "cached" if item.present else "remote"
                print(f"  [{mark:<7}] {item.name:<28} {item.install}")
                if item.detail:
                    print(f"            {item.detail}")
        if report.warning:
            print(report.warning)
        if not report.ok:
            print(T("install:", "安装："))
            for item in report.missing:
                print(f"  {item.install}")
    if not report.ok:
        raise SystemExit(1)


def run_reference_ls(args: argparse.Namespace) -> None:
    """列出参考基因组清单（薄适配 tools/services 的 JSON 字符串返回）。"""
    import json as _json

    from bacmap.tools.services import list_reference_genomes

    raw = list_reference_genomes({})
    try:
        payload = _json.loads(raw)
    except ValueError:
        print(raw)
        return
    if args.json:
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for g in payload.get("groups", []):
        status = "present" if g.get("present") else "missing"
        print(f"  {g.get('group', '')!s:<16} {g.get('version', '-') or '-'!s:<10} {status}")
    print(str(payload.get("hint", "")))


_BASH_COMPLETION = """\
_bacmap_completions() {
    local cur prev commands
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="start overview task plan record run gom config doctor backup restore results events isolate sample search selection db research agent stats detect species reference database completion ops"  # noqa: E501
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return
    fi
    case "${COMP_WORDS[1]}" in
        task) COMPREPLY=( $(compgen -W "list ls show submit approve cancel" -- "$cur") ) ;;
        plan) COMPREPLY=( $(compgen -W "list ls show confirm reject" -- "$cur") ) ;;
        sample|isolate) COMPREPLY=( $(compgen -W "list ls show" -- "$cur") ) ;;
        start) COMPREPLY=( $(compgen -W "mcp web tui console" -- "$cur") ) ;;
        research) COMPREPLY=( $(compgen -W "list ls show create figure stats advstats package request analysis evidence study cohort plan claim experiment" -- "$cur") ) ;;  # noqa: E501
        ops) COMPREPLY=( $(compgen -W "doctor backup restore results events" -- "$cur") ) ;;
        species) COMPREPLY=( $(compgen -W "list resolve" -- "$cur") ) ;;
        reference) COMPREPLY=( $(compgen -W "list" -- "$cur") ) ;;
        *) COMPREPLY=() ;;
    esac
}
complete -F _bacmap_completions bacmap
"""

_ZSH_COMPLETION = """\
#compdef bacmap
_bacmap() {
    local -a commands
    commands=(
        'start:long-running interfaces' 'overview:system overview' 'task:task queries'
        'plan:plan management' 'record:record tasks' 'run:run queries' 'gom:genome objects'
        'config:configuration' 'doctor:health check' 'backup:backup' 'restore:restore'
        'results:results' 'events:events' 'isolate:isolate queries' 'sample:sample queries'
        'search:sample search' 'selection:tool selection' 'db:gspec alias' 'research:research workbench'
        'agent:agent adapters' 'stats:database statistics' 'detect:fastq platform detection'
        'species:species registry' 'reference:reference genomes' 'completion:shell completion'
        'ops:operations (doctor/backup/restore)'
    )
    _describe 'command' commands
}
compdef _bacmap bacmap
"""


def run_completion(args: argparse.Namespace) -> None:
    if args.shell == "bash":
        print(_BASH_COMPLETION)
    elif args.shell == "zsh":
        print(_ZSH_COMPLETION)
    else:
        raise SystemExit(f"unsupported shell: {args.shell}")


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p_stats = sub.add_parser(
        "stats",
        help=T("database statistics summary", "全库统计汇总"),
    )
    add_home(p_stats)
    add_json(p_stats)
    p_stats.set_defaults(func=run_stats)

    p_detect = sub.add_parser(
        "detect",
        help=T(
            "detect FASTQ sequencing platform (read length heuristic)",
            "探测 FASTQ 测序平台（读长启发式）",
        ),
    )
    p_detect.add_argument("directory", help=T("FASTQ directory", "FASTQ 目录"))
    p_detect.add_argument(
        "--sample-reads", type=int, default=2000,
        help=T("reads per file to sample", "每文件采样 read 数"),
    )
    add_json(p_detect)
    p_detect.set_defaults(func=run_detect)

    p_species = sub.add_parser(
        "species",
        help=T("species code registry (list/resolve)", "物种码注册表（list/resolve）"),
    )
    species_sub = p_species.add_subparsers(dest="species_command", required=True)
    sp_ls = species_sub.add_parser(
        "list", aliases=["ls"], help=T("list all species codes", "列出全部物种码"),
    )
    sp_ls.add_argument("--query", default="", help=T("filter by code/name/label", "按码/名称过滤"))
    add_json(sp_ls)
    sp_ls.set_defaults(func=run_species_ls)
    sp_resolve = species_sub.add_parser("resolve", help=T("resolve name -> code", "名称 → 码"))
    sp_resolve.add_argument("name")
    sp_resolve.set_defaults(func=run_species_resolve)

    p_ref = sub.add_parser(
        "reference",
        help=T("reference genome management", "参考基因组管理"),
    )
    ref_sub = p_ref.add_subparsers(dest="reference_command", required=True)
    ref_ls = ref_sub.add_parser("list", aliases=["ls"], help=T("list reference genomes", "列出参考基因组"))
    add_home(ref_ls)
    add_json(ref_ls)
    ref_ls.set_defaults(func=run_reference_ls)

    p_database = sub.add_parser(
        "database",
        help=T("database/reference preflight (no download)", "数据库/参考基因组预检（不下载）"),
    )
    database_sub = p_database.add_subparsers(dest="database_command", required=True)
    db_status = database_sub.add_parser(
        "status", help=T("check required resources for an analyze run", "检查 analyze 所需资源")
    )
    db_status.add_argument("--samples", default="", help=T("comma-separated sample IDs (default: all registered)", "样本 ID，逗号分隔（默认全部已登记）"))
    db_status.add_argument("--annotation", action=argparse.BooleanOptionalAction, default=True, help=T("include Bakta/eggNOG databases", "包含 Bakta/eggNOG 数据库"))
    add_home(db_status)
    add_json(db_status)
    db_status.set_defaults(func=run_database_status)

    p_completion = sub.add_parser(
        "completion",
        help=T(
            "print shell completion script (bash|zsh)",
            "输出 shell 补全脚本（bash|zsh）",
        ),
    )
    p_completion.add_argument("shell", choices=["bash", "zsh"])
    p_completion.set_defaults(func=run_completion)
