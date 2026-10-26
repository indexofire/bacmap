[English](index.md) | **简体中文**

# bacmap

本地病原菌基因组分析系统，面向单工作站部署，数据不出本地网络。确定性分析（Snakemake +
gside/gapit/gmlst）、门、不可变证据链，以及面向外部智能体的 MCP；对话在 Hermes / Pi / DSH 中，
确认留在 bacmap。
冻结设计：[architecture-frozen-v1.md](architecture-frozen-v1.md)（权威版）。

| 文档 | 内容 |
|---|---|
| **[实战教程](tutorial.zh-CN.md)** | **从这里开始**——从安装到签出报告的一次完整走查 |
| [安装指南](installation.zh-CN.md) | 系统要求、pixi 安装、参考数据库 vendor |
| [配置指南](configuration.zh-CN.md) | 路径、环境变量、config.toml、数据分级 |
| [使用指南](usage.zh-CN.md) | CLI、Web 任务台、MCP 智能体接入、任务与门 |
| [运维指南](operations.zh-CN.md) | 体检、备份恢复、迁移与升级 |
| [智能体 Harness](harnesses.zh-CN.md) | Hermes / Pi / DSH 接入、数据边界、实测记录 |
| [工具参考](tools.zh-CN.md) | 全部 26 个注册工具与完整参数 |

快速开始：

```bash
pixi install && pixi shell
bacmap --help          # mcp / web / version
bacmap doctor           # 这台工作站准备好了吗？
bacmap tui              # 任务台（需要终端）
```
