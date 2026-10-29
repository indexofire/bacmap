# 配置

bacmap 通过**环境变量**加一个可选的 TOML 文件（`$BACMAP_HOME/config.toml`）进行配置。
任何路径都不会从源码树位置推导（ADR-03）。本页覆盖大多数安装需要的设置；逐键完整参考见
[配置参考](../reference/configuration.zh.md)。

## 1. 各类内容的位置

```bash
export BACMAP_HOME="$HOME/.local/share/bacmap"
mkdir -p "$BACMAP_HOME"
```

```text
$BACMAP_HOME/
├── config.toml
├── data/                 # metadata.sqlite、实验室结果、knowledge.sqlite
├── results/              # 运行范围的结果 + 最新运行符号链接
├── workflows/bacmap/     # 部署的 Snakemake 工作流；samples.tsv 位于此处
├── workflow_state/       # .snakemake 日志/状态
├── gs/                   # 约定的原始数据布局
├── workspaces/           # mine 任务工作区
├── runs/                 # 每次运行的 run_manifest.json
├── tasks.sqlite          # 任务、计划、事件
├── dbos.sqlite           # DBOS 工作流检查点
├── runs.sqlite           # 运行记录
├── gom.sqlite            # GOM 对象、数据集、菌株索引
├── baseline.sqlite       # 基线候选/发布
└── refs/                 # 外部数据库 + manifest.json
```

大多数命令接受 `--home DIR`；环境变量是默认值。

## 2. 样本登记（samples.tsv）

标准 `analyze` 任务要求样本 ID 已登记在
`$BACMAP_HOME/workflows/bacmap/config/samples.tsv` 中：

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-TYP-001	Salmonella	gs/SAM-TYP-001/SAM-TYP-001_R1.fastq.gz	gs/SAM-TYP-001/SAM-TYP-001_R2.fastq.gz			SAM-TYP-001	ilm	<sha256>
ASM-STD-001	Salmonella		gs/ASM-STD-001/ASM-STD-001.fasta			ASM-STD-001	ont	<sha256>
HZCPE-01__ilm__20261012	VPA	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R1.fastq.gz	gs/HZCPE-01__ilm__20261012/HZCPE-01__ilm__20261012_R2.fastq.gz			HZCPE-01	ilm	<sha256>
```

规则：

- `sample` 是**数据集 ID**；允许字符为 `A-Z a-z 0-9 . _ -`，且不能是 `.` 或 `..`。
- `R1`/`R2` 与 `assembly` 相对于 **`BACMAP_HOME`**（绝对路径也可用）。
- 每个数据集使用**双端 reads** **或**一个组装好的 FASTA，二者择一。若两者都存在，reads
  优先。
- `species` 接受三字母代码（`SAL`、`ECO`、`SHI`、`VPA` 等）或 gside 标签/名称
  （`Salmonella`、`V_parahaemolyticus`、`E. coli`）。优先使用代码。
- `isolate` 是生物学菌株；多个数据集可以指向同一个菌株实体。`platform` 记录测序平台。
- 通过 CLI 登记会计算 `checksum` 并检测内容冲突；仅在手工添加行时留空。

与其手动编辑表格，不如登记一个目录：

```bash
# 组装好的 FASTA：ID 由文件名推导；物种用 gside 自动鉴定
bacmap task submit --type analyze --fasta-dir /data/genomes

# Reads：成对的 *_R1/_R2（或 *_1/_2）文件；物种默认为 UNK，直到管线完成鉴定
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

当同一菌株被多次测序时，数据集名应遵循 `<isolate>__<platform>[__<date>]`：

```text
HZCPE-01__ilm__20261012
HZCPE-01__ont__20261020
```

用相同数据集 ID 登记不同内容是硬错误；bacmap 绝不会悄悄分析旧文件。完整模型见
[数据与身份](../guide/data.zh.md)。

## 3. LLM 端点（可选）

bacmap 的确定性管线不需要 LLM。如果你使用任务内解读/网关或云端 MCP 客户端，请配置
OpenAI 兼容端点：

```toml
# $BACMAP_HOME/config.toml
[llm.endpoints.strata]
location = "local"                      # local | lan | cloud
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.endpoints.deepseek]
location = "cloud"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"        # 只保存变量名

[llm.routing]
interpretation = "deepseek"             # 用途 → 端点

[llm.data_policy]
cloud_max_data_class = "D1"             # 仅 D1 或 D2；D3/D4 永远不可上调
```

在与启动 bacmap 相同的 shell/systemd 单元中注入密钥：

```bash
export DEEPSEEK_API_KEY="sk-..."
bacmap overview
```

数据分级规则在请求发出之前由代码强制执行：

| 分级 | 示例 | 云端端点 |
|---|---|---|
| D0–D1 | 公开数据、去标识化摘要 | 默认允许 |
| D2 | 单菌株分型细节 | 除非管理员将上限提高到 D2，否则阻止 |
| D3–D4 | 序列、个人/流行病学标识符 | 永不发往云端端点 |

## 4. MCP 侧（智能体）

**cloud** MCP 实例是默认实例，只暴露输出在 `cloud_max_data_class` 范围内的工具。**local-trusted**
实例可以暴露到 D4，且必须显式启用：

```toml
[mcp]
allow_local_trusted = true       # 必须是布尔值 true
```

```bash
bacmap mcp --profile local-trusted
```

只有当 Harness 连接的是本地/局域网模型时才使用 `local-trusted`。客户端配置见
[智能体与计划](../guide/agent-plans.zh.md)。

## 5. 计划确认（可选的预授权）

计划由人在受信界面上确认。对于低风险、重复性的分析，管理员可以预授权自动确认：

```toml
[plans.auto_confirm]
enabled = true
max_samples = 20        # 仅 analyze、已登记的样本、无目录摄入、
                        # 无脚本；mine/write/curate 永不自动确认
```

审计操作者记为 `policy:auto-confirm`。默认的人工流程（Web 链接、本地对话框、CLI）见
[智能体与计划](../guide/agent-plans.zh.md)。

## 6. 第一次分析

```bash
# 手工登记一个样本，然后提交
bacmap task submit --type analyze --samples SAM-TYP-001
bacmap task list
bacmap task show <task_id>

# 结果是运行范围的；扁平路径是指向最新运行的链接
ls "$BACMAP_HOME/results/SAM-TYP-001/report/"
ls "$BACMAP_HOME/results/runs/"
```

如果任务最终处于 `awaiting_approval`，打开 Web 任务页，或使用：

```bash
bacmap task approve <task_id> --approver "Your Name" --decision approve --signature "your-signature"
```

想跟着做一次有引导的首次会话，请继续阅读[教程](tutorial.zh.md)。
