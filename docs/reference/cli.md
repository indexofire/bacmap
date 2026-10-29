# CLI reference

The `bacmap` executable has two kinds of top-level entries:

- **interfaces/modes** that take over a terminal or bind a port: `mcp`, `web`, `tui`, `console`;
- **commands** that perform one operation and exit: `overview`, `task`, `plan`, `record`, `run`,
  `gom`, `isolate`, `sample`, `search`, `doctor`, `backup`, `restore`, `results`, `events`.

`--version` prints the program version.

| Common flag | Meaning |
|---|---|
| `--home DIR` | override `BACMAP_HOME` for this command |
| `--json` | print one JSON document (query commands) |
| `--by ACTOR` | audit actor for task/record submissions (default `cli`) |
| `--limit N` | cap list output |
| `--type TYPE` | filter GOM objects (`sample`, `analysis`, `report`, `task`, …) |

## `bacmap mcp`

```text
bacmap mcp [--home H] [--read-only] [--profile {cloud,local-trusted}]
           [--transport {stdio,http}] [--host H] [--port 8765]
           [--uds PATH] [--token-env ENV]
```

- stdio is the default; HTTP is Streamable HTTP and requires a bearer token.
- `--read-only` removes task/plan write tools.
- `local-trusted` requires `[mcp] allow_local_trusted = true`.

```bash
bacmap mcp
bacmap mcp --read-only
bacmap mcp --profile local-trusted
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap mcp --transport http --host 127.0.0.1 --port 8765
bacmap mcp --transport http --uds /run/bacmap-mcp.sock
```

## `bacmap web`

```text
bacmap web [--home H] [--host 127.0.0.1] [--port 8800] [--token-env BACMAP_WEB_TOKEN]
```

Binds loopback by default. A non-loopback host without a token refuses to start.

```bash
bacmap web
BACMAP_WEB_TOKEN=secret bacmap web --host 0.0.0.0 --port 8800
BACMAP_WEB_AUTH=cookie BACMAP_WEB_TOKEN=secret bacmap web
```

## `bacmap tui` / `bacmap console`

```bash
bacmap tui
bacmap console
```

TUI keys and slash commands are documented in [Interfaces](../guide/interfaces.md). `console` is a
numbered menu.

## `bacmap overview`

```bash
bacmap overview
bacmap overview --json
```

Read-only summary: versions, paths, data policy, endpoints, sandbox, task counts.

## `bacmap task`

```text
bacmap task list|ls [--limit N] [--home H] [--json]
bacmap task show <task_id> [--json]
bacmap task submit --type {analyze,curate}
                    (--samples IDS | --fasta-dir DIR | --fastq-dir DIR)
                    [--species CODE] [--scope JSON] [--by ACTOR] [--json]
bacmap task approve <task_id> --approver NAME --decision {approve,reject}
                    --signature SIG [--comment TEXT]
bacmap task cancel <task_id>
```

Examples:

```bash
bacmap task list
bacmap task show 3f9c2a1b
bacmap task submit --type analyze --samples SAM-001,SAM-002
bacmap task submit --type analyze --fasta-dir /data/genomes --species VPA
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task approve 3f9c2a1b --approver "Jane" --decision approve --signature "jd-2026-10-30"
bacmap task cancel 3f9c2a1b
```

Only `analyze`/`curate` can be submitted from the CLI. `mine`/`write` are plan-only; `record` has
its own command.

## `bacmap plan`

```text
bacmap plan list|ls [--limit N]
bacmap plan show <plan_id> [--version N]
bacmap plan confirm <plan_id> [--version N] [--hash PREFIX]
bacmap plan reject <plan_id> --version N --reason TEXT
```

`--hash` accepts a unique prefix of at least 12 hex characters. Without it, `confirm` prints the plan
and asks interactively. `reject` only works on an unconfirmed plan.

```bash
bacmap plan show 9a3f2c1b7d4e4f60
bacmap plan confirm 9a3f2c1b7d4e4f60 --version 1 --hash c1d2e3f4a5b6
bacmap plan reject 9a3f2c1b7d4e4f60 --version 1 --reason "wrong sample"
```

## `bacmap record`

```text
bacmap record metadata --strain-id ID [--sample-id ID] [--field k=v ...] [--by ACTOR]
bacmap record lab --strain-id ID --category CAT --test-name NAME --result VALUE
                  [--unit U] [--method M] [--interpretation I] [--standard S]
                  [--tested-date D] [--tested-by WHO] [--lab LAB] [--notes TEXT]
bacmap record knowledge-import --title TITLE [--authors A] [--year Y] [--source S]
                               [--identifier ID] [--content TEXT]
                               [--entry-kind {literature,method,report}]
bacmap record knowledge-approve <entry_id>
```

Examples in [Data & identity](../guide/data.md#5-records-metadata-lab-results-and-knowledge).

## `bacmap run`

```text
bacmap run list|ls [--limit N] [--json]
bacmap run show <run_id> [--json]
bacmap run compare <run_a> <run_b> [--json]
```

```bash
bacmap run compare 4f2c... 9a31...
```

## `bacmap gom`

```text
bacmap gom list|ls [--type TYPE] [--limit N] [--json]
bacmap gom show <object_id> [--version N] [--json]
```

Object types: `sample`, `analysis`, `report`, `workflow`, `plugin`, `knowledge`, `task`.

## `bacmap isolate`

```text
bacmap isolate list|ls [--json]
bacmap isolate show <isolate_id> [--json]
```

## `bacmap sample`

```text
bacmap sample ls [--json]
bacmap sample show <sample_id> [--json]
```

`sample` IDs are dataset IDs; output is derived from the latest summary.

## `bacmap search`

```text
bacmap search [--query TEXT] [--serotype TEXT] [--st ST] [--gene GENE]
              [--home H] [--json]
```

```bash
bacmap search --query Salmonella
bacmap search --serotype Typhimurium --st 19 --gene blaCTX-M-15
```

## `bacmap doctor`

```text
bacmap doctor [--json]
```

Checks home, database, sandbox, LLM, disk and tools. Exit code `1` only for `fail`.

## `bacmap backup` / `bacmap restore`

```text
bacmap backup --out FILE [--with-results]
bacmap restore --from FILE [--home DIR] [--force]
```

See [Operations](../operations/index.md).

## `bacmap results`

```text
bacmap results migrate [--dry-run]
```

Moves legacy flat result directories into `runs/legacy-<name>/` and replaces them with links.

## `bacmap events`

```text
bacmap events prune --days N [--json]
```

`--days 0` deletes all events. Gate approvals and run records are unaffected.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | operation failed or `doctor` found a `fail` |
| 2 | argument parsing error |
