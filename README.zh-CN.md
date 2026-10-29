[English](README.md) | **简体中文**

# bacmap

本地病原菌基因组分析系统（含内置智能体层）——standalone 架构，冻结设计见
[docs/architecture-frozen-v1.zh.md](docs/architecture-frozen-v1.zh.md)（v1.4.10）。

## 定位

面向**单工作站**（64 GB 内存、本地数据不出网）的病原菌基因组流行病学分析系统：

- **工具注册表**（25 个 `bio_*` 工具）：只读/计算类工具直接暴露，写操作一律经任务提交；
- **任务引擎**：DBOS 工作流（analyze / curate / mine / write 四类任务，断点可恢复）；
- **Snakemake 9 管线**：QC → 组装 → 分型 → AMR/毒力 → 报告；
- **智能体层**：本地 LLM（Strata / OpenAI 兼容端点）意图分类 + 解读撰写，全链路数据分级门控；
- **外部工具分工**（ADR-20）：物种鉴定归 [gside](https://github.com/indexofire/gside)、基因筛查/血清型归 gapit、MLST/cgMLST/MST 归 gmlst——bacmap 只做编排与判定；
- **接入方式**：MCP（v1.4.8 裁定；默认 stdio，另支持带 Bearer 鉴权的 Streamable HTTP，ADR-12），Hermes / Claude / Codex 等客户端均可接入。v1.5 起对话交互推荐在外部 Harness（Hermes、Pi、DeepSeek Harness）的原生界面中进行，计划确认与审批仍在 bacmap 的 CLI/Web 完成（ADR-21）。MCP 实例按数据级别 **Profile** 运行：默认 `cloud`（仅 D0–D1 工具），`local-trusted`（至 D4）须显式开启。

## 快速开始

详细文档：[实战教程](docs/tutorial.zh.md) · [安装指南](docs/installation.zh.md) · [配置指南](docs/configuration.zh.md) · [使用指南](docs/usage.zh.md) · [运维指南](docs/operations.zh.md) · [智能体 Harness](docs/harnesses.zh.md)

```bash
pixi install          # 安装运行时环境（含生信工具链）
pixi shell            # 进入环境
bacmap --help         # 统一命令行入口
```

| 命令 | 说明 |
|---|---|
| `bacmap tui [--home H]` | 任务台（Textual）：任务/样本侧栏、操作日志、命令输入、leader 和弦（`Ctrl+G`）、签批 |
| `bacmap console [--home H]` | 交互式菜单（rich），面向偏好引导式操作的用户 |
| `bacmap overview [--json]` | 系统概览（端点 / 数据策略 / 版本 / 路径 / 沙箱） |
| `bacmap task ls\|show\|submit\|approve\|cancel` | 任务查询与写操作（显式、无 LLM 路径） |
| `bacmap plan ls\|show\|confirm\|reject` | 审阅并确认智能体经 MCP 提出的分析计划（v1.5.1；Web 见 `/plans`） |
| `bacmap record metadata\|lab\|knowledge-import\|knowledge-approve` | 经任务层录入元数据/化验/知识库（v1.7；Web 见 `/records`） |
| `bacmap run ls\|show\|compare` · `bacmap gom ls\|show` | 证据链：运行记录与 GOM 对象（v1.7.1；Web 见 `/runs`、`/gom`） |
| `bacmap doctor` · `bacmap backup` · `bacmap restore` · `bacmap events prune` | 体检、备份/恢复、事件保留（v1.7.2；见运维指南） |
| `bacmap sample ls\|show` / `bacmap search` | 样本浏览与检索 |
| `bacmap mcp [--read-only] [--profile cloud\|local-trusted] [--home H]` | 启动 MCP 服务器：stdio（默认）或带 Bearer 鉴权的 Streamable HTTP（ADR-12）。最多 22 个读/算工具外加任务工具，按 Profile 裁剪（默认 `cloud`） |
| `bacmap web [--host 127.0.0.1] [--port 8800]` | 启动 Web 控制台（任务 / 助手 / 样本 / 检索 / 报告） |
| `bacmap --version` | 版本号 |

查询类子命令均支持 `--json` 便于脚本消费。等价模块方式：
`python -m bacmap.interfaces.mcp` / `python -m bacmap.interfaces.web`。

## 开发

```bash
pixi run -e dev test        # pytest（基线：1369 passed）
pixi run -e dev lint        # ruff
pixi run -e dev contracts   # import-linter 依赖方向契约
```

> 注意：pytest / ruff 装在 **dev 环境**，任务必须带 `-e dev`；
> default 环境只有运行时依赖。

## 数据目录布局（ADR-03）

任何路径不由源码位置推导，全部落在 `BACMAP_HOME`（默认 `~/.local/share/bacmap`，
可用环境变量 `BACMAP_HOME` 覆盖）：

```
$BACMAP_HOME/
├── data/            # 本地库（bacmap.sqlite：元数据/化验/特征索引）与参考库（reference/、db/）
├── results/         # 分析结果
├── workflows/       # 工作流文件
├── workflow_state/  # .snakemake 运行状态与日志
├── gom.sqlite       # GOM：分析对象 + 门/审计事件
├── runs.sqlite      # 分析运行记录（ADR-18）
├── tasks.sqlite     # 任务表
├── dbos.sqlite      # DBOS 系统库
└── config.toml      # 可选配置（LLM 端点、路由、数据策略）
```

## 配置第三方 LLM API

所有端点走 **OpenAI 兼容协议**（`pydantic-ai` openai 通道）。在 `$BACMAP_HOME/config.toml`：

```toml
[llm.endpoints.strata]
location = "local"                # local | lan | cloud
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.endpoints.deepseek]          # 任意 OpenAI 兼容第三方 API
location = "cloud"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"  # 密钥从环境变量读取，不落盘

[llm.routing]
intent_classifier = "strata"
interpretation = "deepseek"

[llm.data_policy]
cloud_max_data_class = "D1"       # ADR-16：cloud 端点默认 D1，管理员最多放宽到 D2；D3/D4 永不
```

## 验证状态（§8）

| 项 | 内容 | 状态 |
|---|---|---|
| V1 | 12 株金标准端到端（Snakemake 9.x） | ✅ PASS |
| V3 | 意图分类/工具调用/挖掘样例/许可证（Strata 实测，证据 §10.20） | ✅ 99/100 · 工具 45/46 · 挖掘 3/3 · 许可确认 · IQ3_XXS 单档+仲裁 |
| V4 | MCP 接入 Hermes（22 工具） | ✅ Connected 2038ms |
| V8 | 三次重跑逐字段一致 | ✅ IDENTICAL |
| V10 | gside/gmlst/gapit 接入复核 | ✅ 10/12（2 项已归因：marker 法原理边界） |
| V11 | 六道门强制力 | ✅ 全部拦截 |
| V2/V6/V7 | DBOS 恢复 / pydantic-ai×Strata / 同机仲裁 | ✅（随迁移步骤完成） |
| V5 | 信创麒麟 V10 上 Apptainer | ⏳ 等物理机 |
| V9 | 云端 API + 数据分级拦截实测 | ⏳ 等 API 凭据 |

## 许可证

[MIT](LICENSE) © 2026 indexofire
