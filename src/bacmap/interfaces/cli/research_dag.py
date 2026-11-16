"""``bacmap research dag``：研究编排层 P1 命令行。

入口只有两条写路径：
- ``dag submit``：把 DAG 包成 **一个 research 任务** 的版本化计划；
- ``dag resume``：从检查点/暂停处继续（复用既有 task resume 语义）。
确认仍在 ``bacmap plan confirm``（或 debug 模式自动确认），不在此处越权。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bacmap.interfaces.i18n import T
from bacmap.research.dag import DagValidationError, ResearchDag


def _actor() -> str:
    import getpass

    try:
        return f"cli:{getpass.getuser()}"
    except OSError:  # pragma: no cover - 极简容器
        return "cli:unknown"


def _load(path: str) -> ResearchDag:
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return ResearchDag.model_validate(raw)


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_ask(args: argparse.Namespace) -> None:
    """自然语言 → DAG 草案（只写文件/打印，不创建计划、不执行）。"""
    from bacmap.agent.llm.endpoints import load_llm_config
    from bacmap.agent.llm.gateway import LlmGateway, LlmUnavailableError
    from bacmap.agent.planner import PlannerConstraints, propose_dag, recent_run_summaries
    from bacmap.config import config_path

    home = Path(args.home)
    gateway = LlmGateway(load_llm_config(config_path(home)))
    try:
        proposal = propose_dag(
            args.question,
            gateway,
            constraints=PlannerConstraints(
                max_data_class=min(max(args.max_class, 0), 2),
                allow_checkpoints=not args.no_checkpoints,
            ),
            runs=recent_run_summaries(home),
        )
    except LlmUnavailableError as exc:
        raise SystemExit(
            f"planner unavailable: {exc}\n"
            f"hint: check `planner = <endpoint>` under [llm.routing] and the endpoint's"
            f" api_key_env in {config_path(home)}"
        ) from exc

    payload = proposal.model_dump(mode="json")
    if args.out:
        Path(args.out).expanduser().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.json:
        _emit(payload, True)
        return
    if proposal.questions:
        print(T("The planner needs more information:", "计划器需要更多信息："))
        for question in proposal.questions:
            print(f"  - {question}")
    if proposal.dag:
        print(T("DAG draft (not submitted):", "DAG 草案（未提交）："))
        print(json.dumps(proposal.dag, ensure_ascii=False, indent=2))
        if proposal.problems:
            print(T("validation problems:", "校验问题："))
            for problem in proposal.problems:
                print(f"  - {problem}")
    if args.out:
        print(T(f"written to {args.out}", f"已写入 {args.out}"))
    if proposal.dag and not proposal.problems:
        print(
            T(
                "next: bacmap research dag submit <file> && bacmap plan confirm <plan_id>",
                "下一步：bacmap research dag submit <file> && bacmap plan confirm <plan_id>",
            )
        )


def run_catalog(args: argparse.Namespace) -> None:
    from bacmap.research.operators import catalog

    entries = catalog()
    if args.json:
        _emit(entries, True)
        return
    for entry in entries:
        inputs = ", ".join(f"{k}:{v}" for k, v in entry["inputs"].items()) or "-"
        outputs = ", ".join(f"{k}:{v}" for k, v in entry["outputs"].items()) or "-"
        print(f"{entry['ref']:<24} D{entry['data_class']}  {inputs} -> {outputs}")
        print(f"  {entry['doc']}")


def run_validate(args: argparse.Namespace) -> None:
    try:
        dag = _load(args.file)
        dag.validate_dag()
    except DagValidationError as exc:
        if args.json:
            _emit({"ok": False, "problems": exc.problems}, True)
        else:
            print(T("DAG invalid:", "DAG 校验失败："))
            for problem in exc.problems:
                print(f"  - {problem}")
        raise SystemExit(1) from exc
    except Exception as exc:  # 解析错误也要可读
        raise SystemExit(f"{type(exc).__name__}: {exc}") from exc

    order = [node.id for node in dag.linear_order()]
    if args.json:
        _emit(
            {
                "ok": True,
                "nodes": order,
                "checkpoints": dag.checkpoints,
                "data_class": dag.data_class,
                "hash": dag.plan_hash(),
            },
            True,
        )
        return
    print(T("DAG valid", "DAG 校验通过"))
    print(f"  hash: {dag.plan_hash()[:16]}")
    print(f"  order: {' -> '.join(order)}")
    if dag.checkpoints:
        print(f"  checkpoints: {', '.join(dag.checkpoints)}")


def run_submit(args: argparse.Namespace) -> None:
    from bacmap.application.plans import PlanService
    from bacmap.interfaces.cli.main import _engine
    from bacmap.tasks.params import ResearchParams

    dag = _load(args.file)
    dag.validate_dag()
    engine = _engine(args.home)
    service = PlanService(engine, Path(args.home) / "tasks.sqlite")
    params = ResearchParams(analysis="dag", dag=dag.model_dump(mode="json", by_alias=True))
    plan = service.create(
        [params],
        args.rationale or f"research dag: {len(dag.nodes)} nodes",
        _actor(),
    )
    payload = {
        "plan_id": plan.plan_id,
        "version": plan.version,
        "plan_hash": plan.plan_hash,
        "state": plan.state.value,
        "task_ids": plan.task_ids,
    }
    if args.json:
        _emit(payload, True)
        return
    print(T("Plan created", "计划已创建"))
    for key, value in payload.items():
        print(f"  {key}: {value}")
    if plan.state.value != "submitted":
        print(
            T(
                "  next: bacmap plan confirm " + plan.plan_id,
                "  下一步：bacmap plan confirm " + plan.plan_id,
            )
        )


def run_nodes(args: argparse.Namespace) -> None:
    from bacmap.research.dagstore import DagStore

    with DagStore(Path(args.home)) as store:
        rows = store.node_rows(args.task_id)
    if args.json:
        _emit(rows, True)
        return
    if not rows:
        print(T("no nodes recorded (task not started?)", "无节点记录（任务尚未开始？）"))
        return
    print(f"{'node':<16} {'state':<10} {'op':<24} artifacts")
    for row in rows:
        outputs = json.loads(row.get("outputs_json") or "{}")
        print(
            f"{row['node_id']:<16} {row['state']:<10} {row['op']:<24}"
            f" {len(outputs)}"
        )
        if row.get("error"):
            print(f"  error: {row['error']}")


def run_artifacts(args: argparse.Namespace) -> None:
    from bacmap.research.dagstore import DagStore

    with DagStore(Path(args.home)) as store:
        rows = store.list_artifacts(args.task_id)
    if args.json:
        _emit(rows, True)
        return
    if not rows:
        print(T("no artifacts", "无产物"))
        return
    for row in rows:
        line = (
            f"{row['artifact_id']}  {row['type']:<8}"
            f" {row['size_bytes']:>8}B  {row['producer_node']}"
        )
        print(line)


def run_report(args: argparse.Namespace) -> None:
    from bacmap.research.dagstore import DagStore

    with DagStore(Path(args.home)) as store:
        rows = store.list_artifacts(args.task_id)
        texts = [row for row in rows if row["type"] == "Text"]
        if not texts:
            raise SystemExit(T("no Text artifact for this task", "该任务没有 Text 产物"))
        payload = store.load_artifact(str(texts[-1]["artifact_id"]))["value"]
    print(payload.get("markdown", ""))


def run_export(args: argparse.Namespace) -> None:
    """导出报告/图片/可追溯清单（P2；不写回仓库，只落到用户指定目录）。"""
    import json as _json
    from datetime import UTC, datetime

    from bacmap.research.dagstore import DagStore

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    with DagStore(Path(args.home)) as store:
        run = store.get_run(args.task_id)
        rows = store.list_artifacts(args.task_id)
        nodes = store.node_rows(args.task_id)
        texts = [row for row in rows if row["type"] == "Text"]
        figures = [row for row in rows if row["type"] == "Figure"]
        if not texts:
            raise SystemExit(T("no Text artifact for this task", "该任务没有 Text 产物"))
        text = store.load_artifact(str(texts[-1]["artifact_id"]))["value"]
        figure_payload: dict[str, Any] = {}
        if figures:
            figure_payload = store.load_artifact(str(figures[-1]["artifact_id"]))["value"]

    template = str(text.get("template") or "surveillance-zh")
    text_name = "manuscript.md" if template.startswith("imrad") else "report.md"
    (out / text_name).write_text(str(text.get("markdown", "")), encoding="utf-8")
    if figure_payload:
        (out / "figure.svg").write_text(str(figure_payload.get("data", "")), encoding="utf-8")

    provenance = {
        "task_id": args.task_id,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dag": run,
        "nodes": nodes,
        "artifacts": rows,
        "template": template,
        "claims": text.get("claims", []),
        "slots": text.get("slots", {}),
        "audit": text.get("audit", {}),
    }
    (out / "provenance.json").write_text(
        _json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if args.json:
        _emit({"out": str(out), "files": sorted(p.name for p in out.iterdir())}, True)
        return
    print(T(f"exported to {out}", f"已导出到 {out}"))
    for name in (text_name, "figure.svg", "provenance.json"):
        path = out / name
        if path.is_file():
            print(f"  {name}  ({path.stat().st_size}B)")


def run_replay(args: argparse.Namespace) -> None:
    """单节点重放：同一算子/参数/输入，绕过缓存重算并比对产物哈希。"""
    import sqlite3

    from bacmap.research.dag import ResearchDag
    from bacmap.research.dagstore import DagStore
    from bacmap.tasks.engine import dag_engine

    home = Path(args.home)
    db = home / "tasks.sqlite"
    if not db.is_file():
        raise SystemExit(T("tasks.sqlite not found", "找不到 tasks.sqlite"))
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT params_json FROM tasks WHERE task_id = ?", (args.task_id,)
        ).fetchone()
    if row is None:
        raise SystemExit(T(f"no such task: {args.task_id}", f"无此任务：{args.task_id}"))
    params = json.loads(row[0])
    dag = ResearchDag.model_validate(params.get("dag") or {})
    node = next((item for item in dag.nodes if item.id == args.node), None)
    if node is None:
        raise SystemExit(T(f"no such node: {args.node}", f"无此节点：{args.node}"))

    with DagStore(home) as store:
        original = store.node_outputs(args.task_id, node.id)
        inputs = {}
        for port, ref in node.inputs.items():
            src, _, src_port = ref.partition(".")
            artifact_id = store.node_outputs(args.task_id, src).get(src_port)
            if not artifact_id:
                raise SystemExit(
                    T(f"upstream artifact missing: {ref}", f"上游产物缺失：{ref}")
                )
            inputs[port] = artifact_id
        store.ensure_run(f"{args.task_id}-replay", dag.plan_hash(), dag.data_class)
        result = dag_engine.execute_node(
            {
                "home": str(home),
                "task_id": f"{args.task_id}-replay",
                "node_id": node.id,
                "op": node.op,
                "params": node.params,
                "inputs": inputs,
                "data_class": dag.data_class,
                "no_cache": True,
            }
        )
        replayed = result.get("outputs") or {}
    payload = {
        "node": node.id,
        "status": result.get("status"),
        "match": replayed == original,
        "original": original,
        "replayed": replayed,
    }
    if args.json:
        _emit(payload, True)
        return
    print(T(f"node {node.id}: {payload['status']}", f"节点 {node.id}：{payload['status']}"))
    if payload["match"]:
        print(T("artifact hashes match (deterministic)", "产物哈希一致（确定性）"))
    else:
        print(T("artifact hashes differ", "产物哈希不一致"))


def run_gc(args: argparse.Namespace) -> None:
    from bacmap.research.dagstore import DagStore

    with DagStore(Path(args.home)) as store:
        result = store.gc(keep_days=args.keep_days, dry_run=not args.apply)
    if args.json:
        _emit(result, True)
        return
    mode = T("would remove", "将删除") if result["dry_run"] else T("removed", "已删除")
    print(f"{mode}: {result['artifacts']} artifacts, {result['bytes']} bytes")


def run_resume(args: argparse.Namespace) -> None:
    from bacmap.interfaces.cli.main import _engine
    from bacmap.tasks.spec import TaskId

    engine = _engine(args.home)
    try:
        engine.resume(TaskId(args.task_id))
    except (KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(T(f"resumed {args.task_id}", f"已恢复 {args.task_id}"))


def add_parser(sub: Any, add_home: Any, add_json: Any) -> None:
    ask = sub.add_parser(
        "ask",
        help=T(
            "Compile a research question into a DAG draft (P3; no submission)",
            "把研究问题编译成 DAG 草案（P3；不提交）",
        ),
    )
    ask.add_argument("question", help=T("research question", "研究问题"))
    ask.add_argument(
        "--max-class",
        type=int,
        default=2,
        dest="max_class",
        help=T("data-class ceiling (max D2)", "数据级别上限（最高 D2）"),
    )
    ask.add_argument(
        "--no-checkpoints",
        action="store_true",
        help=T("do not propose checkpoints", "不生成检查点"),
    )
    ask.add_argument("--out", default="", help=T("write the draft to a file", "草案写入文件"))
    add_home(ask)
    add_json(ask)
    ask.set_defaults(func=run_ask)

    p = sub.add_parser(
        "dag",
        help=T(
            "Research DAG orchestration (P1: linear + checkpoints)",
            "研究编排 DAG（P1：线性 + 检查点）",
        ),
    )
    s = p.add_subparsers(dest="dag_command", required=True)

    cat = s.add_parser("catalog", help=T("List registered operators", "列出已注册算子"))
    add_json(cat)
    cat.set_defaults(func=run_catalog)

    val = s.add_parser("validate", help=T("Validate a DAG JSON file", "校验 DAG JSON 文件"))
    val.add_argument("file", help=T("path to dag.json", "dag.json 路径"))
    add_json(val)
    val.set_defaults(func=run_validate)

    sub_p = s.add_parser(
        "submit",
        help=T("Submit a DAG as a versioned research plan", "把 DAG 提交为版本化研究计划"),
    )
    sub_p.add_argument("file", help=T("path to dag.json", "dag.json 路径"))
    sub_p.add_argument("--rationale", default="", help=T("plan rationale", "计划说明"))
    add_home(sub_p)
    add_json(sub_p)
    sub_p.set_defaults(func=run_submit)

    nodes = s.add_parser("nodes", help=T("Show node states", "查看节点状态"))
    nodes.add_argument("task_id")
    add_home(nodes)
    add_json(nodes)
    nodes.set_defaults(func=run_nodes)

    arts = s.add_parser("artifacts", help=T("List task artifacts", "列出任务产物"))
    arts.add_argument("task_id")
    add_home(arts)
    add_json(arts)
    arts.set_defaults(func=run_artifacts)

    rep = s.add_parser("report", help=T("Print the rendered report", "打印渲染后的报告"))
    rep.add_argument("task_id")
    add_home(rep)
    rep.set_defaults(func=run_report)

    exp = s.add_parser(
        "export",
        help=T("Export report.md + figure.svg + provenance.json", "导出报告/图/溯源清单"),
    )
    exp.add_argument("task_id")
    exp.add_argument("--out", required=True, help=T("output directory", "输出目录"))
    add_home(exp)
    add_json(exp)
    exp.set_defaults(func=run_export)

    replay = s.add_parser(
        "replay",
        help=T("Replay one node and compare artifact hashes", "重放单节点并比对产物哈希"),
    )
    replay.add_argument("task_id")
    replay.add_argument("--node", required=True, help=T("node id", "节点 id"))
    add_home(replay)
    add_json(replay)
    replay.set_defaults(func=run_replay)

    gc = s.add_parser(
        "gc",
        help=T(
            "Remove unreferenced artifacts (dry-run by default)",
            "清理无引用产物（默认 dry-run）",
        ),
    )
    gc.add_argument("--keep-days", type=int, default=0, dest="keep_days")
    gc.add_argument("--apply", action="store_true", help=T("actually delete", "实际删除"))
    add_home(gc)
    add_json(gc)
    gc.set_defaults(func=run_gc)

    res = s.add_parser(
        "resume", help=T("Resume a paused/checkpointed DAG task", "恢复暂停/检查点任务")
    )
    res.add_argument("task_id")
    add_home(res)
    res.set_defaults(func=run_resume)
