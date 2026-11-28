# LLM 可执行的安装指引

把整篇文档粘贴到任意 LLM 对话中，让它为你安装 bacmap。

## 前置条件

1. **Linux**（推荐 x86_64；ARM 可能存在生信工具构建问题）
2. **git** —— `sudo apt install git`（或你的发行版等价命令）
3. **pixi** —— 包管理器（安装 Python + 全部生信工具）

## 安装 bacmap

```bash
git clone https://github.com/indexofire/bacmap.git ~/repos/bacmap
cd ~/repos/bacmap
pixi install
```

## 验证

```bash
# 版本检查
pixi run bacmap --version

# 健康检查（只读）
pixi run bacmap doctor
```

## 启动服务

```bash
# Web 界面（http://127.0.0.1:8800）
pixi run bacmap start web

# MCP 服务（供 AI 智能体接入）
pixi run bacmap start mcp

# 终端 UI
pixi run bacmap start tui
```

## 快速分析测试

```bash
# 提交一个 FASTA 目录进行分析
pixi run bacmap task submit --fasta-dir /path/to/assemblies --type analyze

# 查看任务状态
pixi run bacmap task list
```

## 硬件需求

| 档位 | CPU | 内存 | 磁盘 | 说明 |
|---|---|---|---|---|
| 最低 | 8 核 | 16 GB | 100 GB | 基础分析，不含 GTDB-Tk |
| 工作站 | 16 核 | 64 GB | 300 GB | 完整管线含 GTDB-Tk |
| 服务器 | 64 核 | 256 GB | 1 TB | GTDB-Tk 全树、批量重负载 |

### 本地 LLM（可选）

| 配置 | GPU | 内存 | 说明 |
|---|---|---|---|
| 入门 | RTX 5060 Ti 16 GB | 64 GB | 量化 DeepSeek/Qwen 模型 |
| 双机 | 2× DGX Spark | —— | DeepSeek mini + 独立 x86_64 生信服务器 |

> **注意**：生信工具在 ARM 上可能有构建问题，bacmap 服务器请用 x86_64。
> GPU 服务器可以单独跑 LLM 推理（在 config.toml 中将 `[llm.endpoints]`
> 的 `location` 设为 `"lan"`）。
