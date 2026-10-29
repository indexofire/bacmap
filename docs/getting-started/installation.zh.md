# 快速开始

本页带你从一台裸 Linux 工作站走到完成验证的 bacmap 安装与第一次分析。它也说明了在真正处理
样本之前所需的最低配置。

## 1. 环境要求

| 项目 | 推荐配置 | 原因 |
|---|---|---|
| 操作系统 | Linux x86_64 | 生信工具链为 Linux 原生 |
| 内存 | 64 GB | 本地 LLM（约 45 GB）与管线可同机共享；仅做确定性分析时 16 GB 即可 |
| 磁盘 | 50 GB+ | CARD/VFDB/MLST 方案与 cgMLST 方案体积较大 |
| 网络 | 仅安装时需要 | 运行时分析不得需要外联连接（ADR-16） |
| 沙箱 | Apptainer 或 Podman | `mine` 任务与外部数据访问必需 |

如果你不运行本地 LLM，所有确定性功能仍可正常工作。只有可选的任务内解读/网关路径会降级（C3）。

## 2. 安装

```bash
git clone <repo> bacmap
cd bacmap
pixi install          # 默认环境：Python 3.12 + Snakemake 9 + 工具
pixi shell            # 激活环境
bacmap --version      # 0.1.2
```

`pixi install` 提供的内容：

- **Snakemake 与工具链**：fastp、shovill、bwa、minimap2、samtools、bcftools、blast、
  bedtools、iqtree 等（见 `pixi.toml`）。
- **外部分析工具**（ADR-20）：`gside`（物种鉴定）、`gapit`（基因筛查/分型）、
  `gmlst`（MLST/cgMLST/MST）。
- **独立的 `recomb` 环境**，内含 Gubbins，用于可选的重组检测。它之所以隔离，是因为其
  IQ-TREE 版本锁定与主管线冲突；请用 `pixi run -e recomb …` 运行。

开发环境是独立的：

```bash
pixi install -e dev
pixi run -e dev test        # pytest（当前基线：1610 passed）
pixi run -e dev lint        # ruff
pixi run -e dev typecheck   # mypy
pixi run -e dev contracts   # import-linter 依赖契约
pixi run -e dev docs-build  # mkdocs（双语）
```

> 运行 pytest/ruff 时务必带 `-e dev`。不带它时 pixi 会解析到系统 Python，收集阶段报
> `No module named 'dbos'`——这是环境用错，不是代码坏了。

## 3. 数据根目录与首次体检

bacmap 把所有内容存放在 `BACMAP_HOME`（默认 `~/.local/share/bacmap`）之下：

```text
$BACMAP_HOME/
├── config.toml              # 可选；缺省时使用默认值
├── data/                    # 元数据、实验室结果、知识库、参考数据
├── results/
│   └── runs/<task_id>/<sample>/...   # 每次执行的物理输出
├── workflows/bacmap/        # 部署的 Snakemake 工作流 + config/samples.tsv
├── workflow_state/          # .snakemake 日志/状态
├── gs/<sample>/             # 约定的原始数据布局
├── workspaces/<task_id>/    # mine 任务工作区
├── runs/                    # 运行清单（证据链）
├── tasks.sqlite             # 任务/计划/事件表
├── dbos.sqlite              # DBOS 工作流检查点
├── runs.sqlite              # 不可变的运行记录
├── gom.sqlite               # GOM 对象、数据集、菌株索引
├── baseline.sqlite          # 基线候选/发布
└── refs/                    # 外部数据库 + manifest.json
```

```bash
export BACMAP_HOME="$HOME/.local/share/bacmap"   # 可选：覆盖默认值
bacmap doctor                                    # 人类可读
bacmap doctor --json                             # 机器可读
```

`doctor` 检查可写性、任务数据库结构版本、沙箱后端、LLM 端点、可用磁盘与外部工具。
它只在 `fail` 项时返回 `1`；警告不会让命令失败。

## 4. 沙箱后端

`mine` 任务在无网络的容器中执行 Python：

```bash
sudo apt-get install podman        # 单工作站的推荐选择
# 或：sudo apt-get install apptainer
which apptainer podman             # 任有其一即可
```

回退顺序为 Apptainer → Podman。两者都未安装时，`mine` 会以明确的 `sandbox unavailable`
消息失败。除非为受控开发显式设置 `BACMAP_ALLOW_UNSANDBOXED=1`，否则拒绝在宿主机直接执行。
Docker 被刻意排除在支持范围之外。

## 5. 参考数据库

cgMLST 方案只需下载一次，并缓存在 pixi 环境中：

```bash
gmlst scheme download senterica_2
gmlst scheme list                       # ✓ = 已缓存
gmlst scheme download ecoli_2
```

重建 pixi 环境会丢失缓存；重建后请重新下载。EnteroBase 对匿名下载有限速，请耐心重试。

大型可选数据库（CheckM2、GTDB-Tk）通过环境变量定位：

```bash
export CHECKM2_DB=/srv/db/checkm2
export GTDBTK_DATA_PATH=/srv/db/gtdbtk
```

在 `$BACMAP_HOME/refs/manifest.json` 中登记外部工具数据库，这样每条运行记录都能写明所用
的确切版本：

```json
{"databases": [
  {"name": "gapit:card", "version": "3.2.6", "checksum": "sha256:..."},
  {"name": "gmlst:senterica_2", "version": "2026-09", "checksum": "sha256:..."}
]}
```

## 6. 首次验证

```bash
bacmap --version
bacmap doctor
bacmap web &                              # http://127.0.0.1:8800
bacmap mcp --read-only < /dev/null        # stdio 冒烟测试；应干净退出
```

这些通过后，继续阅读[配置](configuration.zh.md)与[教程](tutorial.zh.md)。若使用外部
智能体，请按[智能体与计划](../guide/agent-plans.zh.md)接入。

## 7. 常见安装问题

| 现象 | 处理 |
|---|---|
| pytest 报 `No module named 'dbos'` | 用 `pixi run -e dev …`，不要用系统 Python |
| `bacmap: command not found` | 运行 `pixi shell`，或使用 `.pixi/envs/default/bin/bacmap` |
| `snakemake: command not found` | 工作流必须在 pixi 环境内运行；激活环境或通过 `bacmap` 运行 |
| `sandbox unavailable` | 安装 Apptainer 或 Podman；没有沙箱时 `mine` 无法运行 |
| 重建后 cgMLST 方案缺失 | 重新运行 `gmlst scheme download <scheme>` |
| `database schema version N is newer` | 你降级了 bacmap；请恢复匹配的备份，而不是用旧代码打开它 |
