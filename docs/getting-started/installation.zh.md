# 快速开始

本页带你从一台裸 Linux 工作站走到完成验证的 bacmap 安装与第一次分析。它也说明了在真正处理
样本之前所需的最低配置。

## 1. 环境要求

### 硬件配置（PLAN #10）

| 档位 | CPU | 内存 | 磁盘 | 适用 |
|---|---|---|---|---|
| 最低 | 8 核 | 16 GB | 100 GB | 基础分析，无 GTDB-Tk、无本地 LLM |
| 工作站 | 16 核 | 64 GB | 300 GB | 完整流程 + 本地 LLM（量化模型） |
| 服务器 | 64 核 | 256 GB | 1 TB | GTDB-Tk full-tree、大批量处理 |

### 本地 LLM（可选）

| 方案 | GPU | 内存 | 说明 |
|---|---|---|---|
| 入门 | RTX 5060 Ti 16 GB | 64 GB | 经 Strata 跑量化 DeepSeek/Qwen 模型 |
| 双机 | 2× DGX Spark | — | DeepSeek mini + 独立 x86_64 生信服务器 |

> **注意**：生信工具在 ARM 架构可能存在构建问题——bacmap 服务器建议用 x86_64。
> GPU 服务器可独立运行 LLM 推理（config.toml 中 `[llm.endpoints]` 设
> `location = "lan"`）。LLM 与管线同机时，设 `[llm.resources] co_located = true`，
> bacmap 会在管线重步骤时自动为 LLM 预留计算核。

### 软件

| 项目 | 推荐配置 | 原因 |
|---|---|---|
| 操作系统 | Linux x86_64 | 生信工具链为 Linux 原生 |
| 内存 | 64 GB | 本地 LLM（约 45 GB）与管线可同机共享；仅做确定性分析时 16 GB 即可 |
| 磁盘 | 50 GB+ | CARD/VFDB/MLST 方案与 cgMLST 方案体积较大 |
| 网络 | 仅安装时需要 | 运行时分析不得需要外联连接（ADR-16） |
| 沙箱 | Apptainer 或 Podman | `mine` 任务与外部数据访问必需 |

如果你不运行本地 LLM，所有确定性功能仍可正常工作。只有可选的任务内解读/网关路径会降级（C3）。

## 2. 安装

### 一键安装（Linux/macOS）

```bash
curl -fsSL https://raw.githubusercontent.com/indexofire/bacmap/main/scripts/setup.sh | bash
```

自动检查前置依赖、克隆仓库、`pixi install` 并运行 `bacmap doctor`。

<details>
<summary>手动安装（分步）</summary>

```bash
git clone https://github.com/indexofire/bacmap && cd bacmap
pixi install --all    # 安装所有环境：Python 3.12 + Snakemake 9 + 工具
pixi shell            # 激活环境
bacmap --version      # 0.1.5
```

`pixi install` 提供的内容：

- **Snakemake 与工具链**：fastp、shovill、flye、unicycler、bwa、minimap2、samtools、
  bcftools、blast、bedtools、iqtree、**bakta**、**eggnog-mapper**、**QUAST** 等
  （见 `pixi.toml`）。
- **常用分析工具**（ADR-20）：`gside`（物种鉴定）、`gspec`（基因筛查/分型）、
  `gmlst`（MLST/cgMLST/MST）。
- **AMR 筛查**使用 gspec 的 `card`/`vfdb`/`plasmidfinder`，以及 NCBI
  **AMRFinderPlus**（基因 + 点突变）。AMRFinderPlus 4.2.7+ 同时是 Bakta 内部
  AMR 专家系统依赖；gspec `ncbi` 数据库提供同一 Reference Gene Catalog 的存在性
  筛查（不含点突变）。不再需要 `abricate`。
- **注释数据库**不随 `pixi install` 下载：Bakta light ≈4 GB，eggNOG-mapper 数十 GB。
  首次使用请运行 `pixi run python scripts/setup_annotation_dbs.py`；可用
  `BACMAP_BAKTA_DB` / `BACMAP_EGGNOG_DATA_DIR` 覆盖路径。不需要注释时设置
  `BACMAP_ANNOTATION_ENABLED=0`（管线写 `disabled` 占位，绝不伪造注释结果）。
- **独立的 `recomb` 环境**，内含 Gubbins，用于可选的重组检测。因为其与
  IQ-TREE 版本锁定与主管线冲突；请用 `pixi run -e recomb …` 运行。
- **trycycler 不随默认环境安装**：其 conda 包要求 Python <3.11，而 bacmap 运行在
  3.12；高级 `platform=trycycler` 路径需另行提供 `trycycler` 可执行文件。

开发环境是独立的：

```bash
pixi install -e dev
pixi run -e dev test        # pytest（当前基线：2015 passed）
pixi run -e dev lint        # ruff
pixi run -e dev typecheck   # mypy
pixi run -e dev contracts   # import-linter 依赖契约
pixi run -e dev docs-build  # mkdocs（双语）
```

> 运行 pytest/ruff 时务必带 `-e dev`。不带它时 pixi 会解析到系统 Python，收集阶段报
> `No module named 'dbos'`——这是环境用错，不是代码坏了。

### 2.1 配置模板与配置位置

仓库根目录提供 `config.example.toml`（TOML，不是 YAML）。最简单的初始化方式：

```bash
bacmap config init          # 写入 $BACMAP_HOME/config.toml
bacmap config init --user   # 写入 ~/.config/bacmap/config.toml
bacmap config init --project # 写入当前源码检出 config.toml（已被 .gitignore 忽略）
```

pixi/源码检出中，项目本地配置不会被自动发现，需显式指定：

```bash
cp config.example.toml config.toml
export BACMAP_CONFIG="$PWD/config.toml"
```

pip/conda 安装时推荐：

```bash
bacmap config init --user
# ~/.config/bacmap/config.toml
```

读取顺序与细节见[配置](configuration.zh.md)。

### 2.1 独立 conda 环境与智能体环境的关系

pixi 环境本质上就是一个项目本地的 conda 环境（`.pixi/envs/default`）。当前官方支持且经过
测试的安装方式是 pixi；后续 bacmap 发布 conda 包后，目标安装方式是：

```bash
conda create -n bacmap -c conda-forge -c bioconda bacmap
conda activate bacmap
bacmap doctor
```

在此之前不建议手工拼一个 conda 环境：生信工具的版本、PyPI 依赖和原生依赖由
`pixi.toml` 锁定，手工复现容易漏项。

无论 bacmap 用 pixi 还是 conda，**Hermes / Pi / DSH 都不需要与 bacmap 共用环境**：

```text
Hermes / Pi / DSH（自己的安装环境）
        │ MCP stdio 或 HTTP
        ▼
bacmap（pixi/conda 环境，含 Snakemake 与生信工具）
        ▼
gside / gspec / gmlst / samtools / blast / ...
```

stdio 连接独立 conda 环境时推荐：

```yaml
command: conda
args: ["run", "--no-capture-output", "-n", "bacmap", "bacmap", "start", "mcp"]
```

`--no-capture-output` 保证 MCP stdio 不被 conda 缓冲。完整客户端配置见
[智能体与计划](../guide/agent-plans.zh.md)。

</details>

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
  {"name": "gspec:card", "version": "3.2.6", "checksum": "sha256:..."},
  {"name": "gmlst:senterica_2", "version": "2026-09", "checksum": "sha256:..."}
]}
```

## 6. 首次验证

```bash
bacmap --version
bacmap doctor
bacmap start web &                        # http://127.0.0.1:8800
bacmap start mcp --read-only < /dev/null  # stdio 冒烟测试；应干净退出
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
