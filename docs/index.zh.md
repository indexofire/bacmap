# bacmap

本地病原菌基因组分析系统，面向单工作站部署，数据不出本地网络。确定性分析（Snakemake +
gside/gapit/gmlst）、门、不可变证据链，以及面向外部智能体的 MCP；对话在 Hermes / Pi / DSH 中，
确认留在 bacmap。
冻结设计：[architecture-frozen-v1.zh.md](architecture-frozen-v1.zh.md)（权威版）。

| 文档 | 内容 |
|---|---|
| **[实战教程](tutorial.zh.md)** | **从这里开始**——从安装到签出报告的一次完整走查 |
| [安装指南](installation.zh.md) | 系统要求、pixi 安装、参考数据库 vendor |
| [配置指南](configuration.zh.md) | 路径、环境变量、config.toml、数据分级 |
| [使用指南](usage.zh.md) | CLI、Web 任务台、MCP 智能体接入、任务与门 |
| [运维指南](operations.zh.md) | 体检、备份恢复、迁移与升级 |
| [智能体 Harness](harnesses.zh.md) | Hermes / Pi / DSH 接入、数据边界、实测记录 |
| [工具参考](tools.zh.md) | 全部 26 个注册工具与完整参数 |

快速开始：

```bash
pixi install && pixi shell
bacmap --help          # mcp / web / version
bacmap doctor           # 这台工作站准备好了吗？
bacmap tui              # 任务台（需要终端）
```
