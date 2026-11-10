# Reference

Lookup material for exact names, flags, payloads and defaults.

<div class="grid cards" markdown>

-   **CLI**

    ---

    Every command, subcommand, flag and exit behaviour.

    [CLI](cli.md)

-   **MCP**

    ---

    Transports, profiles, tools, prompts, resources and error shapes.

    [MCP](mcp.md)

-   **HTTP API**

    ---

    `/api/v1` endpoints, authentication, CSRF, SSE and errors.

    [HTTP API](api.md)

-   **Configuration**

    ---

    Environment variables, TOML keys, defaults and constraints.

    [Configuration](configuration.md)

-   **Tool registry**

    ---

    All 27 `bio_*` tools, effects, data classes and parameters.

    [Tools](tools.md)


-   **Research API (P1)**

    ---

    Research sessions, statistics, figures and manuscript artifacts.

    [Research API](research-api.md)

</div>

Conventions:

- `<...>` is a placeholder; `[--flag]` is optional.
- CLI query commands accept `--json`.
- MCP tool arguments are shown as JSON objects; the actual call is made by the client.
- Data classes: D0 public, D1 aggregate, D2 single-strain, D3 sequence, D4 personal.
- The program version and the frozen design revision are independent (currently 0.1.5 / v1.10.17).
