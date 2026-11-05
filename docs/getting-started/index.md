# Getting started

Install bacmap, point it at a data root, verify the environment, and complete one analysis.
Everything on this page is a short orientation; each step links to its detailed page.

## Only want to use natural language?

That is the intended main path:

1. run `pixi install` and `bacmap doctor` below;
2. connect `bacmap start mcp` to Hermes, Pi or DSH using the client configuration;
3. say in the chat: **“Analyse the eight *V. parahaemolyticus* read sets in `/data/run42` with the
   standard pipeline.”**
4. open the confirmation link returned by the agent and approve it;
5. return to the chat and ask: “Where is the run? Summarise serotype and AMR.”

The full dialogue (including troubleshooting) is the [tutorial](tutorial.md); MCP configuration is in
[Agents and plans](../guide/agent-plans.md).

<div class="grid cards" markdown>

-   **Installation and first run**

    ---

    Requirements, the pixi environment, reference databases, sandbox and `bacmap doctor`.

    [Installation](installation.md)

-   **Configuration**

    ---

    `BACMAP_HOME`, `samples.tsv`, LLM endpoints, MCP profiles and plan pre-authorisation.

    [Configuration](configuration.md)

-   **Tutorial**

    ---

    A complete agent-first session: data → plan → human confirmation → results → report.

    [Tutorial](tutorial.md)

</div>

## The shortest path

```bash
git clone <repo> bacmap && cd bacmap
pixi install
pixi shell
bacmap --version          # 0.1.2
bacmap doctor             # home, database, sandbox, LLM, disk, tools
bacmap start web          # http://127.0.0.1:8800
```

Then either use the Web console or connect an agent:

```bash
bacmap start mcp          # cloud profile (default)
bacmap start mcp --profile local-trusted   # D4 tools; requires [mcp] allow_local_trusted = true
```

## Before real samples

1. **Data root** — default `~/.local/share/bacmap`; see [Configuration](configuration.md).
2. **Sample registry** — `$BACMAP_HOME/workflows/bacmap/config/samples.tsv`; see
   [Data and identity](../guide/data.md).
3. **Sandbox** — Apptainer or Podman for `mine`; see [Installation](installation.md).
4. **Reference databases** — cgMLST schemes and optional GTDB-Tk/CheckM2 paths; see
   [Installation](installation.md).
5. **Human confirmation** — plans are confirmed in Web/CLI, never by the model; see
   [Agents and plans](../guide/agent-plans.md).

## Next steps

- Follow the [Tutorial](tutorial.md) for an end-to-end example.
- Learn the [interfaces](../guide/interfaces.md).
- Read the [architecture](../concepts/architecture.md) and [security](../concepts/security.md) concepts.
