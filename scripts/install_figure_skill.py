#!/usr/bin/env python3
"""安装 figures4papers 科研作图技能到 $BACMAP_HOME/skills/figure-maker/。

用法：
    pixi run python scripts/install_figure_skill.py          # 安装/更新（pin 版本）
    pixi run python scripts/install_figure_skill.py --main   # 跟随上游 main（不推荐）

技能来源：https://github.com/ChenLiu-1996/figures4papers 的
`scientific-figure-making/`（SKILL.md + references/，agentskills.io 格式）。
安装后 bacmap MCP 以 `skill://bacmap/figure-maker/**` 资源发布，供外部
Harness（DSH/Hermes/Pi）在 write/mine 任务生成出版级 matplotlib 图时查阅。

许可注意：上游为 **CC BY-NC 4.0（署名-非商业性使用）**，与 bacmap 的 MIT
不兼容，故本仓库不内嵌任何上游内容，只在部署期下载到本机数据目录。
非商业场景（公共卫生监测、学术研究）可正常使用；商业使用需另行获得
上游授权。安装会在技能目录保留 LICENSE 与来源清单以履行署名义务。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_URL = "https://github.com/ChenLiu-1996/figures4papers"
# pin 到验证过的提交（升级 = 更新此哈希并回归 figure-maker 资源测试）
PINNED_COMMIT = "b709de17da7e8f9a72e51a5de5bced924a01eeab"
SUBDIR = "scientific-figure-making"
SKILL_NAME = "figure-maker"


def _home() -> Path:
    return Path(os.environ.get("BACMAP_HOME", "~/.local/share/bacmap")).expanduser()


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd[:6]), "..." if len(cmd) > 6 else "", flush=True)
    subprocess.run(cmd, check=True, cwd=cwd)


def install(*, follow_main: bool = False) -> Path:
    target = _home() / "skills" / SKILL_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f4p-") as tmp:
        repo = Path(tmp) / "figures4papers"
        _run(["git", "clone", "--quiet", "--depth", "1", REPO_URL, str(repo)])
        commit = "main"
        if not follow_main:
            _run(["git", "fetch", "--quiet", "--depth", "1", REPO_URL, PINNED_COMMIT], cwd=repo)
            _run(["git", "checkout", "--quiet", PINNED_COMMIT], cwd=repo)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
            ).stdout.strip()
        src = repo / SUBDIR
        if not (src / "SKILL.md").is_file():
            raise SystemExit(f"上游结构变化：{src}/SKILL.md 不存在")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)
        # 署名义务：保留上游 LICENSE 与来源清单
        shutil.copy2(repo / "LICENSE", target / "LICENSE")
        (target / "PROVENANCE.txt").write_text(
            f"source: {REPO_URL}\ncommit: {commit}\n"
            f"license: CC BY-NC 4.0 (see LICENSE; non-commercial use only)\n"
            f"installed_at: {datetime.now(UTC).isoformat()}\n",
            encoding="utf-8",
        )
    print(f"figure-maker 技能已安装: {target}")
    print("MCP 资源：skill://bacmap/figure-maker/SKILL.md 及 references/*.md")
    print("注意：CC BY-NC 4.0 —— 限非商业使用（公共卫生/学术场景）。")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--main", action="store_true", help="跟随上游 main 最新提交（默认 pin 验证版本）"
    )
    args = parser.parse_args()
    if shutil.which("git") is None:
        print("需要 git", file=sys.stderr)
        return 1
    try:
        install(follow_main=args.main)
    except subprocess.CalledProcessError as exc:
        print(f"下载失败：{exc}", file=sys.stderr)
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
