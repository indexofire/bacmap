# Reference

Lookup material for exact names, flags, payloads and defaults.

| Page | Contents |
|---|---|
| [CLI](cli.md) | every command, subcommand, flag and exit behaviour |
| [MCP](mcp.md) | transports, profiles, tools, prompts, resources, error shapes |
| [HTTP API](api.md) | `/api/v1` endpoints, auth, CSRF, SSE and errors |
| [Configuration](configuration.md) | environment variables, TOML keys, defaults and constraints |
| [Tool registry](tools.md) | all 26 `bio_*` tools, effects, data classes and parameters |

Conventions:

- `<...>` is a placeholder; `[--flag]` is optional.
- CLI query commands accept `--json`.
- MCP tool arguments are shown as JSON objects; the actual call is made by the client.
- Data classes: D0 public, D1 aggregate, D2 single-strain, D3 sequence, D4 personal.
- The program version and the frozen design revision are independent (currently 0.1.2 / v1.9.3).
