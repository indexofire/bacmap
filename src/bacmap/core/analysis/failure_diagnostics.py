"""Pipeline failure diagnostics — parse Snakemake errors and suggest fixes.

Usage:
    from bacmap.core.analysis.failure_diagnostics import diagnose
    result = diagnose(stderr_text)
    print(result.summary)
    print(result.suggested_fix)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bacmap.config import WORKFLOW_LOG_DIR


@dataclass
class Diagnosis:
    error_type: str = "unknown"
    rule_name: str = ""
    details: str = ""
    suggested_fix: str = ""
    severity: str = "medium"
    recovery_commands: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"[{self.error_type}]"]
        if self.rule_name:
            parts.append(f"rule={self.rule_name}")
        if self.details:
            parts.append(self.details[:120])
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type,
            "rule_name": self.rule_name,
            "details": self.details,
            "suggested_fix": self.suggested_fix,
            "severity": self.severity,
            "recovery_commands": self.recovery_commands,
            "summary": self.summary,
        }


_PATTERNS: list[tuple[str, re.Pattern[str], str, str, list[str]]] = [
    (
        "sandbox_unavailable",
        re.compile(r"no apptainer|no podman|沙箱(?:启动)?失败|sandbox unavailable", re.I),
        "找不到可用的沙箱后端（Apptainer/Podman）",
        "安装 Apptainer 或 Podman 后重试；直通模式仅用于受控开发",
        ["pixi global install podman"],
    ),
    (
        "lock",
        re.compile(r"Directory cannot be locked|Error locking directory|lock.*exist", re.I),
        "Snakemake 工作目录被锁定，可能由前一次中断的运行留下",
        "解锁工作目录后重试（路径按 BACMAP_HOME 解析，ADR-03）",
        ['snakemake --unlock -d "$BACMAP_HOME/workflows/bacmap"'],
    ),
    (
        "missing_input",
        re.compile(r"MissingInputException|Missing input files", re.I),
        "缺少输入文件，可能 FASTQ 路径错误或文件未下载",
        "检查 samples.tsv 中的路径，确保 FASTQ 文件存在",
        [
            'cat "$BACMAP_HOME/workflows/bacmap/config/samples.tsv"',
            'ls "$BACMAP_HOME/gs"',
        ],
    ),
    (
        "oom",
        re.compile(
            r"ChildIOException|signal 9|SIGKILL|out of memory"
            r"|Cannot allocate memory|MemoryError",
            re.I,
        ),
        "内存不足（OOM），组装或比对步骤消耗过多 RAM",
        "降低 config.yaml 的 cores/threads 后重试（避免与本地模型争内存）",
        ["bacmap task submit --type analyze --samples <ID>"],
    ),
    (
        "missing_tool",
        re.compile(
            r"command not found|No such file or directory.*\.pixi"
            r"|not installed|executable not found",
            re.I,
        ),
        "生信工具未安装或不在 PATH 中",
        "运行 pixi install 安装工具链",
        ["pixi install", "which fastp shovill blastn abricate"],
    ),
    (
        "missing_db",
        re.compile(
            r"Database.*error|No volumes were created|database.*not found"
            r"|\.nhr|\.phr.*not found",
            re.I,
        ),
        "BLAST 数据库索引缺失或损坏",
        "重建数据库索引",
        ["makeblastdb -in data/reference/<db>.fasta -dbtype nucl -out data/reference/<db>"],
    ),
    (
        "timeout",
        re.compile(r"TimeoutExpired|timed out", re.I),
        "管线执行超时（可能卡在 I/O 或死锁）",
        "检查是否有僵尸进程，或增加超时时间",
        [
            "ps aux | grep -E 'bwa|samtools|blast' | grep -v grep",
            'snakemake --unlock -d "$BACMAP_HOME/workflows/bacmap"',
        ],
    ),
    (
        "disk_full",
        re.compile(r"No space left on device|disk full|ENOSPC", re.I),
        "磁盘空间不足",
        "清理临时文件或更换更大磁盘",
        ["df -h", 'rm -rf "$BACMAP_HOME/workflows/bacmap/.snakemake/tmp"/*'],
    ),
    (
        "permission",
        re.compile(r"Permission denied|Operation not permitted", re.I),
        "文件权限不足",
        "检查文件/目录权限",
        ["ls -la <path>", 'chmod -R u+rwX "$BACMAP_HOME/results"'],
    ),
    (
        "snakemake_v8",
        re.compile(r"TypeError.*snakefile|AttributeError.*dag|version.*8.*incompatible", re.I),
        "Snakemake 版本不兼容（本仓库锁定 9.27.*，见 ADR-05）",
        "运行 pixi install 按 pixi.lock 恢复锁定版本",
        ["pixi install"],
    ),
]

_RULE_RE = re.compile(r"(?:Error in rule|rule)\s+(\w+)[:\s]", re.I)
_EXIT_RE = re.compile(r"non-zero exit status (\d+)")
_FILE_RE = re.compile(r"(?:Missing|Could not find|No such file).*?(/[^\s,]+)", re.I)


def diagnose(stderr: str) -> Diagnosis:
    """Parse Snakemake stderr and return a structured diagnosis."""
    if not stderr or not stderr.strip():
        return Diagnosis(
            error_type="empty",
            details="No stderr output captured",
            suggested_fix="Check .snakemake/log/ manually",
            severity="low",
        )

    result = Diagnosis()

    for err_type, pattern, details, fix, commands in _PATTERNS:
        m = pattern.search(stderr)
        if m:
            result.error_type = err_type
            result.details = details
            result.suggested_fix = fix
            result.recovery_commands = commands
            break

    rule_m = _RULE_RE.search(stderr)
    if rule_m:
        result.rule_name = rule_m.group(1)

    exit_m = _EXIT_RE.search(stderr)
    if exit_m:
        result.details = f"{result.details}; exit code {exit_m.group(1)}".strip("; ")

    file_m = _FILE_RE.search(stderr)
    if file_m and result.error_type == "missing_input":
        result.details = f"{result.details}; missing file: {file_m.group(1)}"

    if result.error_type in ("oom", "disk_full"):
        result.severity = "critical"
    elif result.error_type in ("lock", "missing_tool", "missing_db"):
        result.severity = "high"
    elif result.error_type == "unknown":
        last_lines = stderr.strip().split("\n")[-3:]
        tail = "; ".join(ln.strip() for ln in last_lines if ln.strip())[:300]
        result.details = f"{result.details}; {tail}" if result.details else tail

    return result


def diagnose_from_log(log_path: str) -> Diagnosis:
    """Read the latest Snakemake log file and diagnose."""

    p = Path(log_path)
    if not p.exists():
        log_dir = WORKFLOW_LOG_DIR
        if log_dir.exists():
            logs = sorted(log_dir.glob("*.snakemake.log"))
            if logs:
                p = logs[-1]

    if not p.exists():
        return Diagnosis(
            error_type="no_log",
            details="No Snakemake log file found",
            severity="low",
        )

    text = p.read_text(errors="replace")
    error_lines = [
        ln
        for ln in text.split("\n")
        if any(kw in ln.lower() for kw in ("error", "exception", "failed", "traceback"))
    ]

    if not error_lines:
        return Diagnosis(
            error_type="no_error",
            details="Log file exists but no errors found",
            severity="low",
        )

    return diagnose("\n".join(error_lines))
