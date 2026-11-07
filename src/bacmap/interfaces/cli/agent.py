"""``bacmap agent`` — install/inspect agent-harness adapters.

L1 content (server instructions, role prompts/resources) stays in bacmap.  These
commands only generate the thin L2 files a user-selected harness needs.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from bacmap.agent import harnesses
from bacmap.interfaces.i18n import T


def _emit(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def run_list(args: argparse.Namespace) -> None:
    items = harnesses.list_harnesses()
    if args.json:
        _emit([h.model_dump(mode="json") for h in items])
        return
    for h in items:
        print(f"{h.name:<10} {h.display_name:<24} {h.config_format:<5} {h.notes}")


def run_export(args: argparse.Namespace) -> None:
    spec = harnesses.get_harness(args.harness)
    if args.format == "skill":
        if not args.role:
            raise SystemExit("--format skill requires --role")
        print(harnesses.export_skill(args.role), end="")
        return
    if args.format == "mcp-config":
        print(harnesses.mcp_config_example(spec), end="")
        return
    text = harnesses.instructions_markdown(spec)
    if args.json:
        _emit(
            {
                "harness": spec.name,
                "format": args.format,
                "content": text,
            }
        )
        return
    print(text, end="")


def run_install(args: argparse.Namespace) -> None:
    try:
        result = harnesses.install(
            args.harness,
            scope=args.scope,
            target=args.target,
            with_skills=args.with_skills,
            force=args.force,
        )
    except harnesses.InstallError as exc:
        raise SystemExit(str(exc)) from exc
    if args.json:
        _emit(result.model_dump(mode="json", by_alias=True))
        return
    print(
        T(
            f"installed {result.harness} guidance → {result.instructions}",
            f"已安装 {result.harness} 指导文件 → {result.instructions}",
        )
    )
    print(f"  manifest: {result.manifest}")
    for path in result.skills:
        print(f"  skill: {path}")


def run_doctor(args: argparse.Namespace) -> None:
    result = harnesses.doctor(args.target)
    if args.json:
        _emit(result.model_dump(mode="json", by_alias=True))
        return
    state = "ok" if result.ok else "FAILED"
    print(f"agent adapter: {state}  ({result.base})")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    for error in result.errors:
        print(f"  error: {error}")


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    p = sub.add_parser(
        "agent",
        help=T(
            "install/inspect guidance for a user-selected agent harness",
            "为用户自选的 agent harness 安装/检查指导文件",
        ),
    )
    s = p.add_subparsers(dest="agent_command", required=True)

    ls = s.add_parser("list", help=T("list supported harnesses", "列出支持的 harness"))
    add_json(ls)
    ls.set_defaults(func=run_list)

    exp = s.add_parser(
        "export",
        help=T("print generated guidance/config to stdout", "输出生成的指导/配置"),
    )
    exp.add_argument("--harness", required=True)
    exp.add_argument(
        "--format",
        choices=["instructions", "mcp-config", "skill"],
        default="instructions",
    )
    exp.add_argument("--role", default="", help=T("role for --format skill", "skill 的角色"))
    add_json(exp)
    exp.set_defaults(func=run_export)

    inst = s.add_parser(
        "install",
        help=T("install generated guidance into a harness", "把生成的指导安装到 harness"),
    )
    inst.add_argument("--harness", required=True)
    inst.add_argument("--scope", choices=["project", "user"], default="project")
    inst.add_argument(
        "--target",
        default="",
        help=T("install base directory (default: cwd/home)", "安装根目录（默认 cwd/home）"),
    )
    inst.add_argument(
        "--with-skills",
        action="store_true",
        help=T("also write portable .bacmap/skills/<role>/SKILL.md", "同时写可移植 skills"),
    )
    inst.add_argument("--force", action="store_true", help=T("replace a user file", "覆盖用户文件"))
    add_json(inst)
    inst.set_defaults(func=run_install)

    doc = s.add_parser(
        "doctor",
        help=T("verify installed files and detect drift", "校验安装文件与漂移"),
    )
    doc.add_argument("--target", default="", help=T("install base directory", "安装根目录"))
    add_json(doc)
    doc.set_defaults(func=run_doctor)
