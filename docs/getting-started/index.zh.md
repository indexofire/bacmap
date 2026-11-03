# 快速开始

安装 bacmap、设置数据根目录、验证环境，并完成一次分析。本页是简短导览，每一步都链接到详细页面。

## 只想用自然语言？

这是设计上的主路径：

1. 完成下面的 `pixi install` / `bacmap doctor`；
2. 按客户端配置把 `bacmap mcp` 接入 Hermes / Pi / DSH；
3. 在对话里说：**“用标准管线分析 `/data/run42` 下的八套副溶血性弧菌 reads。”**
4. 打开智能体给出的确认链接，点击确认；
5. 回到对话继续问：“运行到哪一步了？汇总血清型和耐药。”

完整对话与故障处理见[教程](tutorial.zh.md)；MCP 配置见
[智能体与计划](../guide/agent-plans.zh.md)。

<div class="grid cards" markdown>

-   **安装与首次运行**

    ---

    系统要求、pixi 环境、参考数据库、沙箱与 `bacmap doctor`。

    [安装](installation.zh.md)

-   **配置**

    ---

    `BACMAP_HOME`、`samples.tsv`、LLM 端点、MCP Profile 与计划预授权。

    [配置](configuration.zh.md)

-   **教程**

    ---

    完整的智能体优先流程：数据 → 计划 → 人工确认 → 结果 → 报告。

    [教程](tutorial.zh.md)

</div>

## 最短路径

```bash
git clone <repo> bacmap && cd bacmap
pixi install
pixi shell
bacmap --version          # 0.1.2
bacmap doctor             # 目录、数据库、沙箱、LLM、磁盘、工具
bacmap web                # http://127.0.0.1:8800
```

然后使用 Web 控制台，或接入智能体：

```bash
bacmap mcp                # 默认 cloud Profile
bacmap mcp --profile local-trusted   # D4 工具；需 [mcp] allow_local_trusted = true
```

## 处理真实样本之前

1. **数据根目录** —— 默认 `~/.local/share/bacmap`，见[配置](configuration.zh.md)。
2. **样本登记** —— `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`，见
   [数据与身份](../guide/data.zh.md)。
3. **沙箱** —— `mine` 需要 Apptainer 或 Podman，见[安装](installation.zh.md)。
4. **参考数据库** —— cgMLST 方案与可选的 GTDB-Tk/CheckM2 路径，见[安装](installation.zh.md)。
5. **人工确认** —— 计划只在 Web/CLI 确认，模型不能确认，见
   [智能体与计划](../guide/agent-plans.zh.md)。

## 下一步

- 按[教程](tutorial.zh.md)完整走一遍。
- 了解[界面](../guide/interfaces.zh.md)。
- 阅读[架构](../concepts/architecture.zh.md)与[安全](../concepts/security.zh.md)概念。
