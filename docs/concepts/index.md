# Concepts

This section explains how bacmap is put together and why. It is the place to read before changing
code, reviewing a security boundary, or interpreting an audit trail.

<div class="grid cards" markdown>

-   **Architecture**

    ---

    Layers, component map, dependency rules and request flows.

    [Architecture](architecture.md)

-   **Data model**

    ---

    isolate → dataset → run, databases, storage layout and lifecycle.

    [Data model](data-model.md)

-   **Task engine and gates**

    ---

    DBOS workflows, task states, the four gates, recovery and audit events.

    [Task engine & DBOS](task-engine.md)

-   **Security and data classes**

    ---

    D0–D4, MCP profiles, the confirmation boundary, sandbox and authentication.

    [Security](security.md)

-   **Frozen design**

    ---

    The authoritative ADR text; the Chinese version governs.

    [Frozen design](frozen-design.md)

</div>

## Vocabulary

| Term | Meaning |
|---|---|
| **isolate** | biological strain; stable across sequencing runs (`HZCPE-01`, `EVO-001-P037`) |
| **dataset** | one sequencing library or assembled genome (`HZCPE-01__ilm__20261012`) |
| **run** | one analysis execution of one or more datasets (`run_id`, immutable record) |
| **task** | unit of work in the engine (`analyze`, `curate`, `mine`, `write`, `record`) |
| **plan** | versioned, human-confirmable set of typed tasks proposed by an agent |
| **gate** | deterministic code check that can pass, reject or request human review |
| **approval** | human signature that lets a gated task/release proceed |
| **GOM** | Genome Object Model: immutable, versioned analysis/report/task objects |
| **data class** | D0–D4 sensitivity label used to constrain endpoints and MCP profiles |
| **profile** | fixed MCP permission context (`cloud` or `local-trusted`) |

## Reading order

1. [Architecture](architecture.md) — layers, components and dependency rules.
2. [Data model](data-model.md) — identity, databases and on-disk layout.
3. [Task engine and gates](task-engine.md) — DBOS, states, gates, recovery.
4. [Security and data classes](security.md) — trust boundaries and what code enforces.
5. [Frozen design](frozen-design.md) — the authoritative ADR text.

## One request, end to end

```text
analyze task
  submit ──► DBOS workflow ──► Snakemake (fixed DAG)
                                   │
                                   ├─ gside: species
                                   ├─ gapit: screening/typing
                                   └─ gmlst: MLST/cgMLST
                                   │
                            runs/<task_id>/...
                                   │
                    run record + GOM + strain index
                                   │
                    analysis-claims gate ──► report
                                   │
                        task table / events / Web
```

A **plan** adds one step before execution: the agent creates a typed task set, a human confirms the
exact `(plan_id, version, plan_hash)`, and only then does the engine submit deterministic task IDs.

## What is deliberately *not* in bacmap

- No built-in chat/assistant (v1.6, ADR-21); conversation is external.
- No bioinformatics algorithms for genome-only questions; `gside`/`gapit`/`gmlst` own those.
- No runtime pipeline editing by an LLM; the DAG is a frozen, versioned artifact.
- No direct store writes from interfaces; all writes are tasks.
