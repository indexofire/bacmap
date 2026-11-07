# CLI reference

The `bacmap` executable has two kinds of top-level entries:

- **`start`** — launches a long-running interface that takes over the terminal or binds a port:
  `bacmap start mcp|web|tui|console`; each interface keeps its own flags;
- **commands** that perform one operation and exit: `overview`, `task`, `plan`, `record`, `run`,
  `gom`, `isolate`, `sample`, `search`, `selection`, `doctor`, `backup`, `restore`, `results`,
  `events`.

`--version` prints the program version.

| Common flag | Meaning |
|---|---|
| `--home DIR` | override `BACMAP_HOME` for this command |
| `--json` | print one JSON document (query commands) |
| `--by ACTOR` | audit actor for task/record submissions (default `cli`) |
| `--limit N` | cap list output |
| `--type TYPE` | filter GOM objects (`sample`, `analysis`, `report`, `task`, …) |

## Display language

CLI help and messages follow the display language: the `BACMAP_LANG` environment variable
(`en` | `zh`) takes precedence over `[ui] language` in `config.toml`; the built-in default is
`en`. See [Configuration](configuration.md).

## `bacmap start mcp`

```text
bacmap start mcp [--home H] [--read-only] [--profile {cloud,local-trusted}]
                 [--transport {stdio,http}] [--host H] [--port 8765]
                 [--uds PATH] [--token-env ENV]
```

- stdio is the default; HTTP is Streamable HTTP and requires a bearer token.
- `--read-only` removes task/plan write tools.
- `local-trusted` requires `[mcp] allow_local_trusted = true`.

```bash
bacmap start mcp
bacmap start mcp --read-only
bacmap start mcp --profile local-trusted
export BACMAP_MCP_TOKEN="$(openssl rand -hex 24)"
bacmap start mcp --transport http --host 127.0.0.1 --port 8765
bacmap start mcp --transport http --uds /run/bacmap-mcp.sock
```

## `bacmap start web`

```text
bacmap start web [--home H] [--host 127.0.0.1] [--port 8800] [--token-env BACMAP_WEB_TOKEN]
```

Binds loopback by default. A non-loopback host without a token refuses to start.

```bash
bacmap start web
BACMAP_WEB_TOKEN=secret bacmap start web --host 0.0.0.0 --port 8800
BACMAP_WEB_AUTH=cookie BACMAP_WEB_TOKEN=secret bacmap start web
```

## `bacmap start tui` / `bacmap start console`

```bash
bacmap start tui
bacmap start console
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

## `bacmap research`

```text
bacmap research list|ls [--limit N] [--json]
bacmap research show <session_id> [--json]
bacmap research create --run-id ID --gene NAME --test-name NAME
                       [--profile open-test|research|publication]
                       [--study ID] [--cohort ID] [--plan ID]
                       [--by ACTOR] [--json]
bacmap research artifact <session_id> {figure|report|manuscript|figure_spec|figure_custom|figure_manifest}
bacmap research figure recipes [--executable-only] [--json]
bacmap research figure spec <session_id> [--json]
bacmap research figure draft <session_id> --path FILE [--note TEXT]
bacmap research figure drafts <session_id>
bacmap research figure feedback <draft_id> --text TEXT
bacmap research figure finalize <draft_id> [--recipe ID] [--code FILE]
bacmap research figure reject <draft_id> [--note TEXT]
bacmap research figure attach <session_id> --path FILE [--code FILE] [--spec FILE]
                              [--renderer agent-script|bacmap-deterministic] [--recipe ID]

bacmap research phylo profile --alignment FILE [--dates FILE] [--partitions A,B]
bacmap research phylo plan --profile FILE [--goal ml|bayesian]
bacmap research phylo validate --profile FILE --plan FILE
bacmap research phylo xml --profile FILE --plan FILE --alignment FILE -o XML [--validate]
bacmap research phylo iqtree --plan FILE --alignment FILE [--prefix P]

bacmap research stats logistic --data FILE --outcome COL --predictors A,B
bacmap research stats iptw --data FILE --treatment COL --outcome COL --covariates A,B
bacmap research stats match --data FILE --treatment COL --outcome COL --covariates A,B [--caliper 0.05]
bacmap research stats survival --data FILE --time COL --event COL --group COL
bacmap research package <study_id> --out DIR

bacmap research request create --question TEXT [--run-id ID]... [--gene NAME]
                              [--test-name NAME] [--analysis association|logistic|phylo|figure]
bacmap research request list [--status proposed|approved|rejected]
bacmap research request show <request_id>
bacmap research request approve <request_id> [--members JSON] [--spec JSON]
bacmap research request reject <request_id> [--note TEXT]

bacmap research evidence <identifier>

bacmap research study create --question TEXT [--pathogen SCOPE] [--data-class 0-4]
bacmap research study ls|list [--limit N]
bacmap research study show <study_id>

bacmap research cohort create --study ID --members FILE [--name NAME] [--rules JSON]
bacmap research cohort preview --study ID --members FILE
bacmap research cohort freeze <cohort_id>
bacmap research cohort ls|list [--study ID]

bacmap research plan create --study ID --cohort ID --spec JSON|FILE
bacmap research plan freeze <plan_id>
bacmap research plan run <plan_id>

bacmap research claim create --study ID --type association --wording TEXT --level E2
bacmap research claim review <claim_id> --decision support|challenge|reject|approve
bacmap research claim ls|list [--study ID]

bacmap research experiment record --plan ID --status success|failed|negative|deviated
                                   [--run-id ID ...] [--outcome JSON] [--deviation TEXT]
bacmap research experiment ls|list [--study ID] [--plan ID]
bacmap research publication <study_id> [--json]

bacmap research benchmark {amr|bvbrc|osf|verify-bvbrc|verify-osf} [--data DIR]

bacmap research outbreak --events FILE [--min-count N]
bacmap research sensitivity --table a,b,c,d [--strata JSON|FILE]
bacmap research explore --study ID --cases FILE
                        [--max-tests N] [--max-candidates N] [--min-n N] [--max-q Q]
```

P1 creates a deterministic AMR association draft from an existing run. `open-test` output is
`TEST/UNVERIFIED`; `research`/`publication` output is `REVIEW REQUIRED`.

P2 adds the full object lifecycle: Study → frozen Cohort → frozen AnalysisPlan → Experiment
ledger → Claim review → publication-readiness (G0–G3). `--members`, `--spec`, `--rules`,
`--evidence` and `--outcome` accept inline JSON or a JSON file. `cohort create` also accepts a
whole `cohort_members.json` object (the `members` array is used).

## `bacmap selection`

```text
bacmap selection path [--selection PATH] [--home H] [--json]
bacmap selection options [--tool gapit|gmlst|all] [--species CODE] [--datadir DIR]
                         [--selection PATH] [--downloaded-only] [--home H] [--json]
bacmap selection show [--species CODE] [--selection PATH] [--diff] [--home H] [--json]
bacmap selection validate [PATH] [--datadir DIR] [--downloaded-only] [--home H] [--json]
bacmap selection select [--tool gapit|gmlst|all] [--species CODE] [--databases A,B]
                        [--modes mlst,cgmlst] [--schemes mlst=NAME,cgmlst=NAME]
                        [--from-json FILE] [--from-yaml FILE] [--selection PATH]
                        [--mode extend|replace] [--yes] [--dry-run] [--home H] [--json]
```

Inspect and edit the `tool_selection.yaml` overlay (see
[Configuration §13](configuration.md#13-tool-reference-selection-tool_selectionyaml)):

- `path` prints the overlay path actually resolved (explicit → env → home; nothing is created);
- `options` merges the live catalogs (gapit `db list --json`, gmlst `scheme list -f json`) with
  the current selection and emits one JSON document — the same document the read-only MCP tool
  `bio_tool_selection_options` returns;
- `show` prints the effective species mapping; `--diff` compares it with the registry defaults;
- `validate` rejects unknown databases/schemes, mode/scheme mismatches, undownloaded schemes,
  cgmlst/wgmlst conflicts, cluster databases on read input and license violations; a bad
  selection exits `1`;
- `select` builds the selection interactively, from flags, or from `--from-json`/`--from-yaml`,
  validates it, then writes atomically (`.bak` keeps the previous document); `--dry-run` prints
  only.

`bacmap db ...` is the same parser with `--tool gapit` fixed, kept as the gapit-only alias:
`bacmap db path|options|show|validate|select`.

```bash
bacmap selection options --tool all --json | jq '.species[0]'
bacmap selection show --diff
bacmap selection select --tool gapit --species VPA --databases vpa_ok,vpa_pai
```

## `bacmap agent`

```text
bacmap agent list [--json]
bacmap agent export --harness NAME [--format instructions|mcp-config|skill] [--role ROLE] [--json]
bacmap agent install --harness NAME [--scope project|user] [--target DIR]
                      [--with-skills] [--inline-skills] [--inline-role ROLE]
                      [--force] [--json]
bacmap agent doctor [--target DIR] [--json]
```

Generates the thin adapter files for a user-selected agent harness. The source of truth stays
in bacmap (MCP instructions, role prompts and `skill://` resources); installed files are
guidance, not permissions.

- `list` prints the supported harnesses and their config format;
- `export` prints instructions, an MCP configuration snippet or one role's `SKILL.md`;
- `install` writes the harness instructions and `.bacmap-agent.json`; it is idempotent and
  refuses to overwrite a user file without `--force`; `--with-skills` also writes
  `.bacmap/skills/<role>/SKILL.md`;
- `doctor` verifies file hashes and warns when the installed content or bacmap version differs.

## `bacmap config`

```text
bacmap config init [--user|--project] [--force]
bacmap config path [--json]
```

- default writes `$BACMAP_HOME/config.toml`;
- `--user` writes `$XDG_CONFIG_HOME/bacmap/config.toml` (default `~/.config/bacmap/config.toml`);
- `--project` writes `./config.toml`; in source checkouts this file is gitignored and requires
  `BACMAP_CONFIG="$PWD/config.toml"`;
- the template is `config.example.toml` at the repository root;
- `path` prints the file bacmap currently reads.

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
