[English](index.md) | **简体中文**

# bacmap

本地病原菌基因组分析系统（含内置智能体层），面向单工作站部署，数据不出本地网络。
冻结设计：[architecture-frozen-v1.md](architecture-frozen-v1.md)（权威版）。

| 文档 | 内容 |
|---|---|
| [安装指南](installation.zh-CN.md) | 系统要求、pixi 安装、参考数据库 vendor |
| [配置指南](configuration.zh-CN.md) | 路径、环境变量、config.toml、数据分级 |
| [使用指南](usage.zh-CN.md) | CLI、Web 任务台、MCP 智能体接入、任务与门 |
| [工具参考](tools.zh-CN.md) | 全部 23 个注册工具与完整参数 |

快速开始：

```bash
pixi install && pixi shell
bacmap --help          # mcp / web / version
```
