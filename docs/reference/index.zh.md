# 参考

用于查阅精确的名称、参数、载荷与默认值。

<div class="grid cards" markdown>

-   **CLI**

    ---

    每条命令、子命令、参数与退出行为。

    [CLI](cli.zh.md)

-   **MCP**

    ---

    传输方式、Profile、工具、提示词、资源与错误结构。

    [MCP](mcp.zh.md)

-   **HTTP API**

    ---

    `/api/v1` 端点、鉴权、CSRF、SSE 与错误。

    [HTTP API](api.zh.md)

-   **配置**

    ---

    环境变量、TOML 键、默认值与约束。

    [配置](configuration.zh.md)

-   **工具注册表**

    ---

    全部 26 个 `bio_*` 工具、效果、数据分级与参数。

    [工具](tools.zh.md)

</div>

约定：

- `<...>` 是占位符；`[--flag]` 表示可选。
- CLI 查询命令接受 `--json`。
- MCP 工具参数以 JSON 对象展示；实际调用由客户端发起。
- 数据分级：D0 公开、D1 汇总、D2 单株、D3 序列、D4 个人。
- 程序版本与冻结设计修订相互独立（当前 0.1.2 / v1.9.3）。
