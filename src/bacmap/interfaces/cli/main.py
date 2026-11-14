"""bacmap 控制台命令（CLI）。

长驻界面（启动后接管终端或端口）统一经 ``bacmap start``：
- ``bacmap start mcp``       MCP 服务器：stdio（默认）或 Streamable HTTP（Bearer 鉴权，ADR-12）
- ``bacmap start web``       Web 控制台（默认 127.0.0.1:8800，ADR-16 只绑本机）
- ``bacmap start tui``       全屏 TUI（Textual；任务/样本监控、写操作与签批，无内置对话）
- ``bacmap start console``   交互式菜单（面向不使用子命令的用户）
- ``bacmap stop|restart``    后台 Web 守护进程（``start web -D``）的停止/重启

一次性命令（做完即退）：
- ``bacmap overview``  系统概览
- ``bacmap task list|show|submit|approve|cancel``  任务查询与写操作（list 别名 ls）
- ``bacmap sample ls|show``                        样本查询
- ``bacmap search``                                样本检索
- ``bacmap --version``                             版本号

显示语言：``[ui] language``（en|zh，默认 en）或环境变量 ``BACMAP_LANG``；
所有查询子命令支持 ``--json`` 便于脚本消费。
"""

from __future__ import annotations

import argparse
import contextlib
import json as _json
import os
import signal
import sys
from datetime import UTC, datetime
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

from bacmap.config import BACMAP_HOME
from bacmap.core.tool_selection import SelectionError
from bacmap.interfaces.cli import selection as selection_cli
from bacmap.interfaces.i18n import T

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _warn_if_exposed(host: str) -> None:
    if host not in _LOCAL_HOSTS:
        print(
            T(
                f"[bacmap] warning: bound to non-loopback address {host!r} "
                "(ADR-16 defaults to loopback; verify network boundary and auth "
                "before cross-machine access)",
                f"[bacmap] 警告：绑定非本机地址 {host!r}（ADR-16 默认只绑本机；"
                "跨机访问请确认网络边界与鉴权）",
            ),
            file=sys.stderr,
        )


def _engine(home: str) -> Any:
    from bacmap.tasks.engine.dbos_engine import DbosTaskEngine

    return DbosTaskEngine(Path(home))


def _emit_json(data: Any) -> None:
    print(_json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _console() -> Any:
    from rich.console import Console

    return Console()


def _safe(value: Any) -> str:
    """把不可信文本转义为 Rich 安全的字面量。

    样本摘要（物种/血清型/基因名/门消息）来自文件，可能含 ``[..]`` 之类的
    Rich 标记；直接进表格会改版式（CLI 层的注入面），故统一转义。
    """
    from rich.markup import escape

    return escape(str(value))


# ---------------------------------------------------------------------------
# start mcp / web / tui / console
# ---------------------------------------------------------------------------


def _run_mcp(args: argparse.Namespace) -> None:
    from bacmap.interfaces.mcp.launch import serve

    if args.transport != "stdio":
        _warn_if_exposed(args.host)
    serve(
        home=Path(args.home),
        profile_name=args.profile,
        read_only=args.read_only,
        transport=args.transport,
        host=args.host,
        port=args.port,
        uds=args.uds,
        token_env=args.token_env,
        engine_factory=lambda home: _engine(str(home)),
    )


def _pid_alive(pid: int) -> bool:
    """PID 是否仍存活（signal 0 探测；僵尸/无权限/不存在都视为已死）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 僵尸进程（已退出未回收）仍在进程表里，但对守护进程语义"已死"：
    # /proc/<pid>/stat 第 3 字段为 Z。非 Linux/无 /proc 时保守视为存活。
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return True
    tail = stat.rsplit(")", 1)[-1].split()
    return not (tail and tail[0] == "Z")


_WEB_DAEMON_STATE = "web.daemon.json"


def _read_pidfile(pid_path: Path) -> int | None:
    """读 PID 文件；缺失或内容非法返回 None。"""
    try:
        return int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return None


def _web_daemon_home(args: argparse.Namespace) -> Path:
    return Path(args.home or BACMAP_HOME)


def _web_daemon_pids(home: Path) -> list[int]:
    """扫描 /proc 找出同一 BACMAP_HOME 的 ``bacmap start web`` 守护进程。

    PID 文件随数据目录被删时的兜底：不依赖 pidfile 也能发现/停止旧实例，
    避免 restart 起第二个实例撞端口（实测事故：删目录后旧进程仍在服务）。
    """
    home_str = str(home)
    found: list[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        # 只认真正的控制台脚本进程（shebang 展开后 argv[1] 形如 .../bin/bacmap），
        # 排除 `pixi run bacmap ...` 之类的父进程（其 argv 里也有同样词元）。
        if len(parts) < 2 or not parts[1].endswith("/bacmap"):
            continue
        # `start web` 直启，或 `restart`（总是针对 web）派生的守护进程。
        is_web_daemon = ("start" in parts and "web" in parts) or "restart" in parts
        if not is_web_daemon:
            continue
        if home_str in parts or ("--home" not in parts and home_str == str(BACMAP_HOME)):
            found.append(pid)
    return found


def _port_in_use(host: str, port: int) -> bool:
    """端口是否已有监听者（守护启动前的快速守卫，避免"假成功"）。"""
    import socket

    target = host
    if host in {"0.0.0.0", ""}:  # noqa: S104 — 仅比较监听地址，不实际绑定
        target = "127.0.0.1"
    elif host == "::":
        target = "::1"
    try:
        with socket.create_connection((target, port), timeout=0.5):
            return True
    except OSError:
        return False


def _terminate_pid(pid: int, timeout: float) -> bool:
    """SIGTERM → 超时 SIGKILL；返回进程是否确认退出。"""
    import time

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    if not _pid_alive(pid):
        return True
    print(
        T(
            f"process {pid} did not exit within {timeout:g}s; sending SIGKILL",
            f"进程 {pid} 在 {timeout:g}s 内未退出，发送 SIGKILL",
        )
    )
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    for _ in range(20):
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


def _stop_web_daemon(home: Path, *, timeout: float = 10.0) -> int:
    """停止后台 Web 守护进程（pidfile 优先，丢失时按 /proc 兜底发现）。

    幂等：未运行/陈旧 PID 文件都返回 0（先清理残留再报告）。返回进程退出码。
    """
    pid_path = home / "web.pid"
    pid = _read_pidfile(pid_path) if pid_path.exists() else None
    targets: list[int] = []
    if pid is not None and _pid_alive(pid):
        targets = [pid]
    elif pid_path.exists():
        with contextlib.suppress(OSError):
            pid_path.unlink(missing_ok=True)
        print(T(f"stale pidfile removed: {pid_path}", f"已清理陈旧 PID 文件：{pid_path}"))
    if not targets:
        targets = _web_daemon_pids(home)
    if not targets:
        print(T("bacmap web is not running (no pidfile)", "bacmap web 未运行（无 PID 文件）"))
        return 0
    ok = True
    for target in targets:
        if not _terminate_pid(target, timeout):
            ok = False
            print(T(f"failed to stop process {target}", f"无法停止进程 {target}"))
    with contextlib.suppress(OSError):
        pid_path.unlink(missing_ok=True)
    if ok:
        for target in targets:
            print(T(f"bacmap web stopped (pid {target})", f"bacmap web 已停止（pid {target}）"))
    return 0 if ok else 1


def _load_daemon_state(home: Path) -> dict[str, Any]:
    """读取上次 `start web -D` 的启动参数（供 restart 复用）；缺失/损坏返回 {}。"""
    try:
        raw = (home / _WEB_DAEMON_STATE).read_text(encoding="utf-8")
        value = _json.loads(raw)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _save_daemon_state(home: Path, args: argparse.Namespace) -> None:
    payload = {
        "host": str(args.host),
        "port": int(args.port),
        "token_env": str(args.token_env),
    }
    with contextlib.suppress(OSError):
        (home / _WEB_DAEMON_STATE).write_text(
            _json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _run_stop(args: argparse.Namespace) -> None:
    raise SystemExit(_stop_web_daemon(_web_daemon_home(args), timeout=args.timeout))


def _run_restart(args: argparse.Namespace) -> None:
    """停止（若在运行）后按上次的启动参数重新拉起守护进程。"""
    home = _web_daemon_home(args)
    state = _load_daemon_state(home)
    host = args.host or str(state.get("host") or "127.0.0.1")
    port = args.port or int(state.get("port") or 8800)
    token_env = args.token_env or str(state.get("token_env") or "BACMAP_WEB_TOKEN")
    _stop_web_daemon(home, timeout=args.timeout)
    _run_web(
        argparse.Namespace(
            daemon=True,
            host=host,
            port=port,
            home=str(home),
            token_env=token_env,
        )
    )


def _tail_lines(path: Path, count: int) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-count:]


def _daemonize(log_path: Path, pid_path: Path) -> int:
    """双 fork 守护进程化：脱离会话、stdio 重定向到日志、PID 落盘。

    返回子进程的**启动握手 fd**：子进程在 engine 初始化成功后写一字节，
    父进程阻塞等待并据此返回 0；子进程在握手前退出（初始化失败）→ 父进程
    读到 EOF，打印日志末尾并以非 0 退出。这样 ``start -D`` / ``restart``
    不会在守护进程已死时仍报告成功（实测事故：DBOS 初始化失败但 CLI 返回 0）。

    仅在最终孙进程返回（父/中间子进程 ``os._exit`` 直接退出，不走 atexit/flush）。
    PID 文件由 atexit 摘除（uvicorn 优雅退出会触发）；SIGKILL 后残留的陈旧 PID
    由启动时探测兜底。
    """
    import atexit

    sys.stdout.flush()
    sys.stderr.flush()
    read_fd, write_fd = os.pipe()
    if os.fork() > 0:
        # 原始父进程：等待守护子进程的初始化握手。
        os.close(write_fd)
        with os.fdopen(read_fd, "rb", buffering=0) as pipe:
            status = pipe.read(1)
        if status == b"1":
            os._exit(0)
        sys.stderr.write(
            T(
                "bacmap web daemon failed to start; last log lines:\n",
                "bacmap web 守护进程启动失败；日志末尾：\n",
            )
        )
        for line in _tail_lines(log_path, 15):
            sys.stderr.write(f"  {line}\n")
        sys.stderr.flush()
        os._exit(1)
    os.close(read_fd)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    devnull = os.open(os.devnull, os.O_RDONLY)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
    os.dup2(devnull, 0)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    if devnull > 2:
        os.close(devnull)
    if log_fd > 2:
        os.close(log_fd)
    pid_path.write_text(f"{os.getpid()}\n")

    def _remove_pidfile() -> None:
        with contextlib.suppress(OSError):
            pid_path.unlink(missing_ok=True)

    atexit.register(_remove_pidfile)
    return write_fd


def _run_web(args: argparse.Namespace) -> None:
    import uvicorn

    from bacmap.interfaces.web.app import create_app
    from bacmap.interfaces.web.auth import require_auth_when_exposed

    ready_fd: int | None = None
    if getattr(args, "daemon", False):
        home = Path(args.home or BACMAP_HOME)
        pid_path = home / "web.pid"
        log_path = home / "web.log"
        old_pid = _read_pidfile(pid_path) if pid_path.exists() else None
        if old_pid and _pid_alive(old_pid):
            raise SystemExit(
                f"bacmap web already running (pid {old_pid}); pidfile: {pid_path}"
            )
        # pidfile 可能随数据目录被删：按 /proc 找出同一 HOME 的旧守护进程，
        # 否则会起第二个实例并撞端口（且它持有已删除文件的句柄，停止后数据不可见）。
        orphans = _web_daemon_pids(home)
        if orphans:
            raise SystemExit(
                T(
                    f"a bacmap web daemon for {home} is running (pid {orphans[0]}) "
                    f"but its pidfile is missing; run `bacmap stop --home {home}` first",
                    f"{home} 的 bacmap web 守护进程仍在运行（pid {orphans[0]}），"
                    f"但 PID 文件已丢失；请先运行 `bacmap stop --home {home}`",
                )
            )
        if _port_in_use(args.host, args.port):
            raise SystemExit(
                T(
                    f"port {args.host}:{args.port} is already in use; "
                    "stop the process serving it or choose another --port",
                    f"端口 {args.host}:{args.port} 已被占用；"
                    "请停止监听该端口的进程或换用其它 --port",
                )
            )
        print(
            f"bacmap start web -D → http://{args.host}:{args.port}/"
            f"  ·  pidfile: {pid_path}  ·  log: {log_path}"
        )
        ready_fd = _daemonize(log_path, pid_path)
        # 记录启动参数供 `bacmap restart` 复用（守护子进程内执行）。
        _save_daemon_state(home, args)

    token = os.environ.get(args.token_env, "")
    _warn_if_exposed(args.host)
    require_auth_when_exposed(args.host, token or None)
    try:
        engine = _engine(args.home)
    except BaseException:
        with contextlib.suppress(OSError):
            if ready_fd is not None:
                os.close(ready_fd)
        raise
    if ready_fd is not None:
        # 初始化成功 → 握手；父进程据此判定启动成功并返回 0。
        with contextlib.suppress(OSError):
            os.write(ready_fd, b"1")
            os.close(ready_fd)
    mode = (os.environ.get("BACMAP_WEB_AUTH") or "bearer").strip().lower()
    if not token:
        hint = T(
            f"auth disabled ({args.token_env} not set; local-only is safe)",
            f"鉴权关闭（未设置 {args.token_env}；仅本机安全）",
        )
    elif mode == "cookie":
        hint = T(
            f"browser login: http://{args.host}:{args.port}/login (token in {args.token_env})",
            f"浏览器登录：http://{args.host}:{args.port}/login（令牌见 {args.token_env}）",
        )
    else:
        hint = T(
            f"bearer mode (API clients); for browser login set BACMAP_WEB_AUTH=cookie "
            f"and restart, or use Authorization: Bearer <{args.token_env}>",
            f"bearer 模式（API 客户端）；浏览器登录请设 BACMAP_WEB_AUTH=cookie 后重启，"
            f"或用 Authorization: Bearer <{args.token_env}>",
        )
    from bacmap.config import debug_mode, debug_warning

    if debug_mode():
        print(debug_warning("bacmap start web"), file=sys.stderr)
    print(f"bacmap start web → http://{args.host}:{args.port}/  ·  {hint}")
    app = create_app(engine, auth_token=token or None, host=args.host)
    uvicorn.run(app, host=args.host, port=args.port)


def _run_tui(args: argparse.Namespace) -> None:
    from bacmap.interfaces.tui.app import BacmapTUI

    BacmapTUI(_engine(args.home)).run()


def _run_console(args: argparse.Namespace) -> None:
    from bacmap.interfaces.cli.console import interactive_menu

    interactive_menu(_engine(args.home))


# ---------------------------------------------------------------------------
# overview / task / sample / search
# ---------------------------------------------------------------------------


def _run_overview(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import overview_data

    data = overview_data(_engine(args.home))
    if args.json:
        _emit_json(data)
        return
    c = _console()
    c.print(T("[bold]bacmap system overview[/bold]", "[bold]bacmap 系统概览[/bold]"))
    c.print(f"  BACMAP_HOME : {data['paths']['BACMAP_HOME']}")
    c.print(
        T(
            f"  data policy : cloud ≤ {data['cloud_max_data_class']} (ADR-16)",
            f"  数据策略     : cloud ≤ {data['cloud_max_data_class']}（ADR-16）",
        )
    )
    c.print(T(f"  sandbox     : {data['sandbox']}", f"  沙箱后端     : {data['sandbox']}"))
    c.print(
        T(
            f"  tool selection: {data['paths'].get('tool_selection', '-')}",
            f"  工具选择     : {data['paths'].get('tool_selection', '-')}",
        )
    )
    c.print(
        T(
            f"  components  : {', '.join(f'{k} {v}' for k, v in data['versions'].items())}",
            f"  组件版本     : {', '.join(f'{k} {v}' for k, v in data['versions'].items())}",
        )
    )
    if data["task_counts"]:
        c.print(
            T(
                f"  tasks       : {data['task_counts']}",
                f"  任务分布     : {data['task_counts']}",
            )
        )
    for ep in data["endpoints"]:
        flag = T(" (disabled)", "（禁用）") if not ep["enabled"] else ""
        c.print(
            T(
                f"  LLM endpoint: {ep['name']} [{ep['location']}] {ep['model']}{flag}",
                f"  LLM 端点     : {ep['name']} [{ep['location']}] {ep['model']}{flag}",
            )
        )


def _run_task_ls(args: argparse.Namespace) -> None:
    tasks = _engine(args.home).list_tasks(args.limit)
    if args.json:
        _emit_json(tasks)
        return
    from rich import box
    from rich.table import Table

    c = _console()
    # box.SQUARE：全线细线（默认 HEAVY_HEAD 的表头粗线与表体不一致，视觉突兀）
    table = Table(
        title=T(f"Tasks (latest {len(tasks)})", f"任务（最近 {len(tasks)}）"),
        show_lines=False,
        box=box.SQUARE,
    )
    for col in ("task_id", "type", "state", "step", "submitted_by", "updated_at"):
        table.add_column(col)
    for t in tasks:
        table.add_row(
            t["task_id"][:12],
            t["task_type"],
            t["state"],
            _safe(t.get("current_step") or ""),
            _safe(t.get("submitted_by") or ""),
            t.get("updated_at") or "",
        )
    c.print(table)


def _resolve_task_id(engine: Any, raw: str) -> Any:
    """CLI 任务命令的 ID 入参归一：完整 ID 直用，短前缀（task list 显示 12 位）解析。"""
    from bacmap.tasks.spec import TaskId

    if len(raw) == 32:  # 完整 ID：无需查表
        return TaskId(raw)
    try:
        return engine.resolve_task_id(raw)
    except KeyError as exc:
        raise SystemExit(T(f"Task not found: {raw}", f"任务不存在：{raw}")) from exc
    except ValueError as exc:
        raise SystemExit(
            T(f"Ambiguous ID prefix, lengthen it: {exc}", f"ID 前缀多义，请加长：{exc}")
        ) from exc


def _run_task_show(args: argparse.Namespace) -> None:
    engine = _engine(args.home)
    task_id = _resolve_task_id(engine, args.task_id)
    try:
        st = engine.status(task_id)
    except KeyError as exc:
        raise SystemExit(
            T(f"Task not found: {args.task_id}", f"任务不存在：{args.task_id}")
        ) from exc
    if args.json:
        _emit_json(st.model_dump())
        return
    c = _console()
    c.print(f"[bold]{st.task_id}[/bold]  state={st.state.value}  step={st.current_step or '-'}")
    if st.message:
        c.print(f"  message: {_safe(st.message)}")


def _run_task_submit(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import TaskType

    if args.type not in ("analyze", "curate"):
        raise SystemExit(
            T(
                "task submit only accepts analyze|curate (mine/write go through plans)",
                "task submit 仅支持 analyze|curate（mine/write 属开放路径）",
            )
        )
    params: dict[str, Any] = {}
    if args.fasta_dir or args.fastq_dir:
        if args.samples or (args.fasta_dir and args.fastq_dir):
            raise SystemExit(
                T(
                    "--fasta-dir/--fastq-dir and --samples are mutually exclusive; "
                    "give exactly one directory argument",
                    "--fasta-dir/--fastq-dir 与 --samples 互斥，目录参数二选一",
                )
            )
        # 登记属写操作（samples.tsv）：交由任务引擎首步 _step_register_inputs 执行
        # （v1.5：写只经任务，ADR-07），CLI 只做只读的存在性预检。
        key = "fasta_dir" if args.fasta_dir else "fastq_dir"
        directory = Path(args.fasta_dir or args.fastq_dir).expanduser().resolve()
        if not directory.is_dir():
            raise SystemExit(
                T(f"Directory not found: {directory}", f"目录不存在：{directory}")
            )
        params[key] = str(directory)
        if args.species:
            params["species"] = args.species
    elif args.samples:
        params["samples"] = [s.strip() for s in args.samples.split(",") if s.strip()]
    if args.scope:
        try:
            scope = _json.loads(args.scope)
        except ValueError as exc:
            raise SystemExit(
                T(f"scope is not valid JSON: {exc}", f"scope 不是合法 JSON: {exc}")
            ) from exc
        if not isinstance(scope, dict):
            raise SystemExit(T("scope must be a JSON object", "scope 必须是 JSON 对象"))
        params["scope"] = scope
    try:
        tid = _engine(args.home).submit(TaskType(args.type), params, args.by)
    except (ValueError, NotImplementedError) as exc:
        raise SystemExit(T(f"Submission failed: {exc}", f"提交失败：{exc}")) from exc
    if args.json:
        _emit_json({"task_id": tid, "state": "running"})
    else:
        _console().print(
            T(
                f"Submitted task [bold]{tid}[/bold] ({args.type}); "
                f"poll with `bacmap task show {tid}`",
                f"已提交任务 [bold]{tid}[/bold]（{args.type}）；用 `bacmap task show {tid}` 轮询",
            )
        )


def _run_task_approve(args: argparse.Namespace) -> None:
    from bacmap.tasks.spec import Approval

    approval = Approval(
        approver=args.approver,
        decision=args.decision,
        signature=args.signature,
        comment=args.comment,
        at=datetime.now(UTC),
    )
    try:
        engine = _engine(args.home)
        engine.approve(_resolve_task_id(engine, args.task_id), approval)
    except (KeyError, ValueError) as exc:
        raise SystemExit(T(f"Approval failed: {exc}", f"审批失败：{exc}")) from exc
    if args.decision == "approve":
        _console().print(T(f"Task {args.task_id} approved", f"任务 {args.task_id} 已通过"))
    else:
        _console().print(T(f"Task {args.task_id} rejected", f"任务 {args.task_id} 已拒绝"))


def _run_task_cancel(args: argparse.Namespace) -> None:
    try:
        engine = _engine(args.home)
        engine.cancel(_resolve_task_id(engine, args.task_id))
    except KeyError as exc:
        raise SystemExit(
            T(f"Task not found: {args.task_id}", f"任务不存在：{args.task_id}")
        ) from exc
    except ValueError as exc:
        raise SystemExit(T(f"Cancel failed: {exc}", f"取消失败：{exc}")) from exc
    _console().print(T(f"Task {args.task_id} cancelled", f"任务 {args.task_id} 已取消"))


def _run_task_pause(args: argparse.Namespace) -> None:
    try:
        engine = _engine(args.home)
        engine.pause(_resolve_task_id(engine, args.task_id))
    except KeyError as exc:
        raise SystemExit(
            T(f"Task not found: {args.task_id}", f"任务不存在：{args.task_id}")
        ) from exc
    except ValueError as exc:
        raise SystemExit(T(f"Pause failed: {exc}", f"暂停失败：{exc}")) from exc
    _console().print(
        T(
            f"Task {args.task_id} paused (resume: bacmap task resume {args.task_id})",
            f"任务 {args.task_id} 已暂停（恢复：bacmap task resume {args.task_id}）",
        )
    )


def _run_task_resume(args: argparse.Namespace) -> None:
    try:
        engine = _engine(args.home)
        engine.resume(_resolve_task_id(engine, args.task_id))
    except KeyError as exc:
        raise SystemExit(
            T(f"Task not found: {args.task_id}", f"任务不存在：{args.task_id}")
        ) from exc
    except ValueError as exc:
        raise SystemExit(T(f"Resume failed: {exc}", f"恢复失败：{exc}")) from exc
    _console().print(
        T(
            f"Task {args.task_id} resumed (continues in this process; same run dir)",
            f"任务 {args.task_id} 已恢复（在本进程内继续执行；同一 run 目录续跑）",
        )
    )


def _run_sample_ls(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows

    rows = sample_rows(_engine(args.home))
    # 分页（PLAN #15）：显式给 --limit/--offset 时返回分页信封，否则保持纯列表（兼容）
    offset = getattr(args, "offset", 0) or 0
    limit = getattr(args, "limit", 0) or 0
    if offset or limit:
        total = len(rows)
        if offset:
            rows = rows[offset:]
        if limit:
            rows = rows[:limit]
        if args.json:
            _emit_json({"total": total, "offset": offset, "count": len(rows), "rows": rows})
            return
    if args.json:
        _emit_json(rows)
        return
    from rich.table import Table

    c = _console()
    if offset or limit:
        table = Table(title=T(
            f"Samples ({len(rows)}/{total}, offset={offset})",
            f"样本（{len(rows)}/{total}，偏移 {offset}）",
        ))
    else:
        table = Table(title=T(f"Samples ({len(rows)})", f"样本（{len(rows)}）"))
    for col in ("sample_id", "species", "ST", "serovar", "AMR", "VF", "plasmid"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["sample_id"], _safe(r["verdict"]), str(r["st"]), _safe(r["serovar"]),
            str(r["n_card"]), str(r["n_vfdb"]), str(r["n_plasmid"]),
        )
    c.print(table)


def _run_sample_show(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows

    rows = sample_rows(_engine(args.home))
    row = next((r for r in rows if r["sample_id"] == args.sample_id), None)
    if row is None:
        raise SystemExit(
            T(f"Sample not found: {args.sample_id}", f"样本不存在: {args.sample_id}")
        )
    if args.json:
        _emit_json(row)
        return
    c = _console()
    c.print(
        T(
            f"[bold]{row['sample_id']}[/bold]  species={_safe(row['verdict'])}  "
            f"ST={_safe(row['st'])}  serovar={_safe(row['serovar'])}",
            f"[bold]{row['sample_id']}[/bold]  物种={_safe(row['verdict'])}  "
            f"ST={_safe(row['st'])}  血清型={_safe(row['serovar'])}",
        )
    )
    c.print(
        T(
            f"  virulence/AMR genes: "
            f"{_safe(', '.join(row['card_genes'] + row['vfdb_genes']) or 'none')}",
            f"  毒力/耐药基因: {_safe(', '.join(row['card_genes'] + row['vfdb_genes']) or '无')}",
        )
    )
    c.print(
        T(
            f"  plasmids: {_safe(', '.join(row['plasmids']) or 'none')}",
            f"  质粒: {_safe(', '.join(row['plasmids']) or '无')}",
        )
    )


def _run_search(args: argparse.Namespace) -> None:
    from bacmap.interfaces.views import sample_rows, search_rows

    hits = search_rows(
        sample_rows(_engine(args.home)),
        query=args.query,
        serotype=args.serotype,
        mlst_st=args.st,
        amr_gene=args.gene,
    )
    if args.json:
        _emit_json(hits)
        return
    from rich.table import Table

    c = _console()
    table = Table(title=T(f"Search hits ({len(hits)})", f"检索命中（{len(hits)}）"))
    for col in ("sample_id", "species", "ST", "serovar"):
        table.add_column(col)
    for r in hits:
        table.add_row(r["sample_id"], _safe(r["verdict"]), str(r["st"]), _safe(r["serovar"]))
    c.print(table)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _add_home(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--home",
        default=str(BACMAP_HOME),
        help=T("BACMAP_HOME root directory", "BACMAP_HOME 根目录"),
    )


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--json",
        action="store_true",
        help=T("print JSON output (script-friendly)", "以 JSON 输出（脚本友好）"),
    )


def _add_start_parsers(sub: Any) -> None:
    """长驻界面入口（启动后接管终端或端口）统一挂在 ``bacmap start`` 之下。"""
    p_start = sub.add_parser(
        "start",
        help=T(
            "start a long-running interface: mcp | web | tui | console",
            "启动长驻界面：mcp | web | tui | console",
        ),
    )
    start_sub = p_start.add_subparsers(
        dest="start_target",
        required=True,
        metavar="{mcp,web,tui,console}",
    )

    p_mcp = start_sub.add_parser(
        "mcp",
        help=T(
            "start the MCP server (stdio or Streamable HTTP)",
            "启动 MCP 服务器（stdio 或 Streamable HTTP）",
        ),
    )
    _add_home(p_mcp)
    p_mcp.add_argument(
        "--read-only",
        action="store_true",
        help=T("read-only mode (no task-submission tools)", "只读模式（不暴露任务提交工具）"),
    )
    from bacmap.interfaces.mcp.launch import add_profile_argument

    add_profile_argument(p_mcp)
    p_mcp.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help=T("transport", "传输"),
    )
    p_mcp.add_argument(
        "--host",
        default="127.0.0.1",
        help=T("HTTP bind address (default loopback only)", "HTTP 绑定地址（默认仅本机）"),
    )
    p_mcp.add_argument(
        "--port",
        type=int,
        default=8765,
        help=T("HTTP port (default 8765)", "HTTP 端口（默认 8765）"),
    )
    p_mcp.add_argument(
        "--uds", default="", help=T("use a unix socket path instead", "改用 unix socket 路径")
    )
    p_mcp.add_argument(
        "--token-env",
        default="BACMAP_MCP_TOKEN",
        help=T("bearer token env var name", "Bearer token 环境变量名"),
    )
    p_mcp.set_defaults(func=_run_mcp)

    p_web = start_sub.add_parser("web", help=T("start the Web console", "启动 Web 控制台"))
    _add_home(p_web)
    p_web.add_argument(
        "--host",
        default="127.0.0.1",
        help=T("bind address (default loopback only)", "绑定地址（默认仅本机）"),
    )
    p_web.add_argument(
        "--port",
        type=int,
        default=8800,
        help=T("port (default 8800)", "端口（默认 8800）"),
    )
    p_web.add_argument(
        "--token-env",
        default="BACMAP_WEB_TOKEN",
        help=T("bearer token env var name", "Bearer token 环境变量名"),
    )
    p_web.add_argument(
        "-D",
        "--daemon",
        action="store_true",
        help=T(
            "run in the background (daemon); PID file at $BACMAP_HOME/web.pid, "
            "log at $BACMAP_HOME/web.log; stop with `bacmap stop`",
            "后台守护进程方式运行；PID 写入 $BACMAP_HOME/web.pid，日志 "
            "$BACMAP_HOME/web.log；停止用 `bacmap stop`",
        ),
    )
    p_web.set_defaults(func=_run_web)

    p_tui = start_sub.add_parser(
        "tui", help=T("start the fullscreen TUI (Textual)", "启动全屏 TUI（Textual）")
    )
    _add_home(p_tui)
    p_tui.set_defaults(func=_run_tui)

    p_console = start_sub.add_parser(
        "console", help=T("start the interactive menu", "启动交互式菜单")
    )
    _add_home(p_console)
    p_console.set_defaults(func=_run_console)


def _add_daemon_parsers(sub: Any) -> None:
    """后台 Web 守护进程的生命周期管理（stop/restart）。

    目前只有 ``start web -D`` 会守护化；``stop``/``restart`` 默认目标即 web，
    保留显式 ``web`` 目标以便与 ``bacmap start web`` 对称书写。
    """
    for command, func, help_text, help_zh in (
        (
            "stop",
            _run_stop,
            "stop the background Web daemon (SIGTERM, then SIGKILL on timeout)",
            "停止后台 Web 守护进程（SIGTERM，超时后 SIGKILL）",
        ),
        (
            "restart",
            _run_restart,
            "restart the background Web daemon (reuses the last start options)",
            "重启后台 Web 守护进程（复用上次启动参数）",
        ),
    ):
        p = sub.add_parser(command, help=T(help_text, help_zh))
        p.add_argument(
            "target",
            nargs="?",
            default="web",
            choices=["web"],
            help=T("daemon target (only web for now)", "守护进程目标（目前仅 web）"),
        )
        _add_home(p)
        p.add_argument(
            "--timeout",
            type=float,
            default=10.0,
            help=T(
                "seconds to wait for graceful shutdown before SIGKILL",
                "优雅退出等待秒数，超时后 SIGKILL",
            ),
        )
        if command == "restart":
            p.add_argument("--host", default="", help=T("override host", "覆盖绑定地址"))
            p.add_argument("--port", type=int, default=0, help=T("override port", "覆盖端口"))
            p.add_argument(
                "--token-env",
                default="",
                help=T("override bearer token env var", "覆盖 Bearer 令牌环境变量名"),
            )
        p.set_defaults(func=func)


def _epilog() -> str:
    """双列分组帮助：长驻界面 vs 一次性命令（`bacmap --help` 尾部说明）。"""
    interfaces_label = T(
        "Long-running interfaces (take over the terminal or a port)",
        "界面/模式（启动后接管终端或端口）",
    )
    commands_label = T(
        "One-shot commands (query/write; all support --json)",
        "命令（一次性查询/写操作，均支持 --json）",
    )
    note = T(
        "Each interface keeps its own flags, e.g. `bacmap start mcp --profile local-trusted`.",
        "注：各界面保留自己的参数，如 `bacmap start mcp --profile local-trusted`。",
    )
    return (
        f"{interfaces_label}: bacmap start {{mcp|web|tui|console}} · bacmap stop|restart\n"
        f"{commands_label}: overview · task · plan · record · run · gom · "
        "sample · search · selection · research · agent\n"
        f"{note}"
    )


_COMMAND_METAVAR = (
    "{start,overview,task,plan,record,run,gom,config,doctor,backup,"
    "restore,results,events,isolate,specimen,sample,search,selection,db,research,"
    "agent,stats,detect,species,reference,completion,ops}"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bacmap",
        description=T(
            "bacmap local pathogen genomics analysis system (architecture-frozen-v1)",
            "bacmap 本地病原菌基因组分析系统（architecture-frozen-v1）",
        ),
        epilog=_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"bacmap {pkg_version('bacmap')}")
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        metavar=_COMMAND_METAVAR,
    )

    _add_start_parsers(sub)
    _add_daemon_parsers(sub)

    p_ov = sub.add_parser("overview", help=T("system overview", "系统概览"))
    _add_home(p_ov)
    _add_json(p_ov)
    p_ov.set_defaults(func=_run_overview)

    p_task = sub.add_parser("task", help=T("task queries and write operations", "任务查询与写操作"))
    task_sub = p_task.add_subparsers(dest="task_command", required=True)

    t_ls = task_sub.add_parser("list", aliases=["ls"], help=T("list recent tasks", "列出最近任务"))
    _add_home(t_ls)
    _add_json(t_ls)
    t_ls.add_argument("--limit", type=int, default=50)
    t_ls.set_defaults(func=_run_task_ls)

    t_show = task_sub.add_parser("show", help=T("show task status", "查看任务状态"))
    t_show.add_argument("task_id")
    _add_home(t_show)
    _add_json(t_show)
    t_show.set_defaults(func=_run_task_show)

    t_sub = task_sub.add_parser(
        "submit", help=T("submit an analyze/curate task", "提交 analyze/curate 任务")
    )
    t_sub.add_argument(
        "--fasta-dir",
        help=T(
            "assembly FASTA directory: recursively scan .fna/.fasta/.fa, "
            "register, then submit analyze",
            "组装 FASTA 目录：递归扫描 .fna/.fasta/.fa 登记后提交 analyze",
        ),
    )
    t_sub.add_argument(
        "--fastq-dir",
        help=T(
            "reads directory: detect *_R1/_R2 pairs, register, then submit analyze",
            "reads 目录：识别 *_R1/_R2 配对登记后提交 analyze",
        ),
    )
    t_sub.add_argument(
        "--species",
        help=T(
            "sample species (code or name; per-isolate auto-detection from FASTA when omitted)",
            "样本物种（码或名称；省略时 FASTA 逐株自动识别）",
        ),
    )
    t_sub.add_argument("--type", choices=["analyze", "curate"], required=True)
    t_sub.add_argument(
        "--samples",
        default="",
        help=T("comma-separated sample IDs (analyze)", "样本 ID，逗号分隔（analyze）"),
    )
    t_sub.add_argument(
        "--scope",
        default="",
        help=T(
            'filter JSON (curate, e.g. {"pathogen":"Salmonella"})',
            '筛选 JSON（curate，如 {"pathogen":"Salmonella"}）',
        ),
    )
    t_sub.add_argument("--by", default="cli", help=T("submitter", "提交者"))
    _add_home(t_sub)
    _add_json(t_sub)
    t_sub.set_defaults(func=_run_task_submit)

    t_appr = task_sub.add_parser(
        "approve",
        help=T("sign an approval (tasks awaiting_approval)", "审批签名（awaiting_approval 任务）"),
    )
    t_appr.add_argument("task_id")
    t_appr.add_argument("--approver", required=True)
    t_appr.add_argument("--decision", choices=["approve", "reject"], required=True)
    t_appr.add_argument("--signature", required=True)
    t_appr.add_argument("--comment", default=None)
    _add_home(t_appr)
    t_appr.set_defaults(func=_run_task_approve)

    t_cancel = task_sub.add_parser("cancel", help=T("cancel a task", "取消任务"))
    t_cancel.add_argument("task_id")
    _add_home(t_cancel)
    t_cancel.set_defaults(func=_run_task_cancel)

    t_pause = task_sub.add_parser(
        "pause",
        help=T(
            "pause a running task (workflow stops at the next step boundary)",
            "暂停任务（工作流在下一个步骤边界收场，snakemake 跑完当前规则）",
        ),
    )
    t_pause.add_argument("task_id")
    _add_home(t_pause)
    t_pause.set_defaults(func=_run_task_pause)

    t_resume = task_sub.add_parser(
        "resume",
        help=T(
            "resume a paused/failed(interrupted) task (same run dir, snakemake "
            "rerun-incomplete continues from completed rules)",
            "恢复暂停/中断的任务（同一 run 目录，已完成规则不重算）",
        ),
    )
    t_resume.add_argument("task_id")
    _add_home(t_resume)
    t_resume.set_defaults(func=_run_task_resume)

    from bacmap.interfaces.cli.plans import add_parser as add_plan_parser

    add_plan_parser(sub, _add_home, _add_json)

    from bacmap.interfaces.cli.agent import add_parser as add_agent_parser
    from bacmap.interfaces.cli.config_cmd import add_parser as add_config_parser
    from bacmap.interfaces.cli.evidence import add_parser as add_evidence_parser
    from bacmap.interfaces.cli.isolates import add_parser as add_isolate_parser
    from bacmap.interfaces.cli.ops import add_parser as add_ops_parser
    from bacmap.interfaces.cli.quickwin import add_parser as add_quickwin_parser
    from bacmap.interfaces.cli.records import add_parser as add_record_parser
    from bacmap.interfaces.cli.research import add_parser as add_research_parser
    from bacmap.interfaces.cli.specimens import add_parser as add_specimen_parser

    add_record_parser(sub, _add_home, _add_json)
    add_config_parser(sub, _add_home, _add_json)
    add_research_parser(sub, _add_home, _add_json)
    add_agent_parser(sub, _add_home, _add_json)
    add_evidence_parser(sub, _add_home, _add_json)
    add_isolate_parser(sub, _add_home, _add_json)
    add_specimen_parser(sub, _add_home, _add_json)
    add_ops_parser(sub, _add_home, _add_json)
    add_quickwin_parser(sub, _add_home, _add_json)

    p_sample = sub.add_parser("sample", help=T("sample queries", "样本查询"))
    sample_sub = p_sample.add_subparsers(dest="sample_command", required=True)
    s_ls = sample_sub.add_parser("ls", help=T("list completed samples", "列出已完成样本"))
    s_ls.add_argument("--limit", type=int, default=0, help=T("0=all", "0=全部"))
    s_ls.add_argument("--offset", type=int, default=0, help=T("skip N rows", "跳过 N 行"))
    _add_home(s_ls)
    _add_json(s_ls)
    s_ls.set_defaults(func=_run_sample_ls)
    s_show = sample_sub.add_parser("show", help=T("show sample details", "查看样本详情"))
    s_show.add_argument("sample_id")
    _add_home(s_show)
    _add_json(s_show)
    s_show.set_defaults(func=_run_sample_show)

    def _add_selection_commands(parent: Any, *, default_tool: str, dest: str) -> None:
        subparsers = parent.add_subparsers(dest=dest, required=True)

        d_path = subparsers.add_parser(
            "path", help=T("show the resolved selection path", "显示工具选择解析路径")
        )
        _add_home(d_path)
        _add_json(d_path)
        d_path.add_argument(
            "--selection",
            default="",
            help=T("explicit tool_selection.yaml", "显式 tool_selection.yaml 路径"),
        )
        d_path.set_defaults(func=selection_cli.run_selection_path)

        d_options = subparsers.add_parser(
            "options", help=T("list species defaults and catalogs", "列出物种默认值与 catalog")
        )
        _add_home(d_options)
        _add_json(d_options)
        d_options.add_argument("--tool", choices=["gspec", "gmlst", "all"], default=default_tool)
        d_options.add_argument(
            "--species", default="", help=T("species code/label", "物种码/标签（如 VPA）")
        )
        d_options.add_argument("--datadir", default="", help=T("gspec datadir", "gspec datadir"))
        d_options.add_argument(
            "--selection",
            default="",
            help=T("explicit tool_selection.yaml", "显式 tool_selection.yaml 路径"),
        )
        d_options.add_argument(
            "--downloaded-only",
            action="store_true",
            help=T("gmlst: only cached schemes", "gmlst: 只看已下载 scheme"),
        )
        d_options.set_defaults(func=selection_cli.run_selection_options)

        d_show = subparsers.add_parser(
            "show", help=T("show the effective selection", "显示生效的工具选择")
        )
        _add_home(d_show)
        _add_json(d_show)
        d_show.add_argument("--species", default="", help=T("filter one species", "只看一个物种"))
        d_show.add_argument(
            "--selection",
            default="",
            help=T("explicit tool_selection.yaml", "显式 tool_selection.yaml 路径"),
        )
        d_show.add_argument(
            "--diff",
            action="store_true",
            help=T("diff against registry defaults", "显示与 registry 默认的差异"),
        )
        d_show.set_defaults(func=selection_cli.run_selection_show)

        d_validate = subparsers.add_parser(
            "validate", help=T("validate the selection", "校验工具选择")
        )
        d_validate.add_argument(
            "path",
            nargs="?",
            default="",
            help=T("file to validate (default: effective)", "待校验文件（缺省用生效路径）"),
        )
        _add_home(d_validate)
        _add_json(d_validate)
        d_validate.add_argument("--datadir", default="", help=T("gspec datadir", "gspec datadir"))
        d_validate.add_argument(
            "--downloaded-only",
            action="store_true",
            help=T("gmlst: only cached schemes", "gmlst: 只看已下载 scheme"),
        )
        d_validate.set_defaults(func=selection_cli.run_selection_validate)

        d_select = subparsers.add_parser(
            "select", help=T("interactive or JSON/YAML proposal", "交互/从 JSON 生成工具选择")
        )
        _add_home(d_select)
        _add_json(d_select)
        d_select.add_argument("--tool", choices=["gspec", "gmlst", "all"], default=default_tool)
        d_select.add_argument(
            "--species", default="", help=T("species code/label", "物种码/标签（交互时可省略）")
        )
        d_select.add_argument(
            "--databases",
            default="",
            help=T("gspec: comma-separated DB names", "gspec: 逗号分隔的库名"),
        )
        d_select.add_argument(
            "--modes",
            default="",
            help=T("gmlst: mlst,cgmlst,wgmlst,tgmlst", "gmlst: mlst,cgmlst,wgmlst,tgmlst"),
        )
        d_select.add_argument(
            "--schemes",
            default="",
            help=T("gmlst: mlst=name,cgmlst=name", "gmlst: mlst=name,cgmlst=name"),
        )
        d_select.add_argument(
            "--from-json", default="", help=T("full proposal JSON", "完整 proposal JSON")
        )
        d_select.add_argument(
            "--from-yaml", default="", help=T("full proposal YAML", "完整 proposal YAML")
        )
        d_select.add_argument(
            "--selection",
            default="",
            help=T("target tool_selection.yaml", "目标 tool_selection.yaml 路径"),
        )
        d_select.add_argument("--datadir", default="", help=T("gspec datadir", "gspec datadir"))
        d_select.add_argument(
            "--downloaded-only",
            action="store_true",
            help=T("gmlst: only cached schemes", "gmlst: 只看已下载 scheme"),
        )
        d_select.add_argument("--mode", choices=["extend", "replace"], default="replace")
        d_select.add_argument("--yes", action="store_true", help=T("skip confirmation", "跳过确认"))
        d_select.add_argument(
            "--dry-run", action="store_true", help=T("print only, do not write", "只打印，不写盘")
        )
        d_select.set_defaults(func=selection_cli.run_selection_select)

    p_selection = sub.add_parser(
        "selection",
        help=T(
            "species→tool reference selection (gspec DBs / gmlst modes and schemes)",
            "物种→工具参考数据选择（gspec 库 / gmlst 模式与 scheme）",
        ),
    )
    _add_selection_commands(p_selection, default_tool="all", dest="selection_command")

    p_db = sub.add_parser(
        "db",
        help=T(
            "gspec-only alias for `selection --tool gspec`",
            "gspec-only 别名（等价于 selection --tool gspec）",
        ),
    )
    _add_selection_commands(p_db, default_tool="gspec", dest="db_command")

    p_search = sub.add_parser("search", help=T("search samples", "样本检索"))
    p_search.add_argument(
        "--query",
        default="",
        help=T("keyword (species/serotype/ST/gene)", "关键词（物种/血清型/ST/基因）"),
    )
    p_search.add_argument("--serotype", default="", help=T("serotype filter", "血清型过滤"))
    p_search.add_argument("--st", default="", help=T("MLST ST filter", "MLST ST 过滤"))
    p_search.add_argument(
        "--gene", default="", help=T("gene filter (AMR/virulence)", "基因过滤（AMR/毒力）")
    )
    _add_home(p_search)
    _add_json(p_search)
    p_search.set_defaults(func=_run_search)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except SelectionError as exc:
        raise SystemExit(str(exc)) from exc
