# Guide: choose an interface

<div class="grid cards" markdown>

-   **Interfaces**

    ---

    Web, CLI, TUI and JSON API: routes, commands, keys and authentication.

    [Interfaces](interfaces.md)

-   **Tasks and gates**

    ---

    The five task types, parameters, states and the four gates.

    [Tasks & gates](tasks.md)

-   **Data and identity**

    ---

    isolate → dataset → run, `samples.tsv`, registration, records and external datasets.

    [Data & identity](data.md)

-   **Agents and plans**

    ---

    MCP profiles, Hermes/Pi/DSH setup, plan creation and human confirmation.

    [Agents & plans](agent-plans.md)

-   **Results and evidence**

    ---

    Run-scoped results, reports, run records, GOM objects and search.

    [Results & evidence](results.md)

</div>

bacmap has four human interfaces and one machine interface. They all talk to the same task engine,
so a task submitted from the CLI is visible and approvable in the Web console, and a plan created
over MCP is confirmed in the same place.

| Interface | Best for | Writes | Confirmation |
|---|---|---|---|
| **Web** (`bacmap web`) | daily work, reviewing reports, approving tasks and plans | submit tasks, approve, confirm/reject plans | browser session + CSRF |
| **CLI** (`bacmap …`) | automation, scripts, headless servers | submit/approve/cancel, confirm plans | explicit command |
| **TUI** (`bacmap tui`) | monitoring on the workstation | submit/approve from the keyboard | two-step keyboard confirmation |
| **JSON API** (`/api/v1`) | dashboards and integrations | submit/cancel/confirm | bearer token (trusted surface) |
| **MCP** (`bacmap mcp`) | external agents (Hermes/Pi/DSH) | **plan proposal / record tasks only** | never; a human confirms elsewhere |

## The lifecycle in one picture

```text
            ┌─────────────── human or agent ───────────────┐
            │                                              │
 CLI/Web/TUI submit ───────────────┐                      │
                                   ▼                      ▼
 MCP ── create plan ──► awaiting_confirmation ── human confirms ──► submitted
                                   │                      │
                                   └── reject/revise ◄────┘
                                                          │
                                                          ▼
                                  running ──► succeeded / failed / cancelled
                                                          │
                                          gate not passed │
                                                          ▼
                                                awaiting_approval
                                                          │ human signs
                                                          ▼
                                                     succeeded
```

## Common paths

- **First analysis**: [Getting started](../getting-started/index.md) → [Tutorial](../getting-started/tutorial.md).
- **Daily submission and monitoring**: [Interfaces](interfaces.md).
- **Agent-driven work**: [Agents & plans](agent-plans.md).
- **Sample registration and metadata**: [Data & identity](data.md).
- **Results, reports, run records**: [Results & evidence](results.md).
- **Task types and gates**: [Tasks & gates](tasks.md).

## Conventions used in this documentation

```text
$BACMAP_HOME       data root, default ~/.local/share/bacmap
<sample_id>        dataset ID (the `sample` column in samples.tsv)
task_id            32 lowercase hex characters; CLI accepts unique prefixes
plan_id            16 hex characters; plans are versioned
run_id             immutable analysis-run identifier
D0 … D4            data classes (public → personal); see Security
```

All command examples assume `pixi shell` is active. `--home DIR` can override `BACMAP_HOME` for any
command; `--json` makes query commands machine-readable.
