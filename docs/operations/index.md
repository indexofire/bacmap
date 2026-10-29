# Operations

Day-two work on a single workstation: health checks, backup/restore, migrations, upgrades and
retention. No daemon or service manager is required.

In this section: [Troubleshooting](troubleshooting.md) · [Security and data classes](../concepts/security.md) · [Development](../development/index.md).

## 1. Health check

```bash
bacmap doctor
bacmap doctor --json
```

| Check | What it verifies | If it fails |
|---|---|---|
| `home` | `BACMAP_HOME` exists and is writable | fix ownership or pass `--home` |
| `database` | `tasks.sqlite` schema version matches the code | older: start any command to migrate (backup is automatic); newer: you downgraded — use the newer build |
| `sandbox` | Apptainer/Podman availability | install one before `mine`; `passthrough` means no isolation |
| `llm` | configured endpoint reachability | deterministic functions still work (C3) |
| `disk` | ≥1 GB free | free space or move `BACMAP_HOME` |
| `tools` | `gside`, `gapit`, `gmlst`, `snakemake` on `PATH` | run inside the pixi environment |

Exit code `1` only when a check is `fail`.

## 2. Backup

```bash
bacmap backup --out /backup/bacmap-2026-10-30.zip
bacmap backup --out /backup/full.zip --with-results
```

Included by default:

- `config.toml`, `refs/manifest.json`;
- every SQLite database: `tasks`, `dbos`, `runs`, `gom`, `baseline`, `data/bacmap`,
  `data/knowledge` — via SQLite's backup API for a consistent snapshot;
- `runs/*/run_manifest.json` (the on-disk evidence chain).

`dbos.sqlite` contains workflow/step checkpoints; including it lets in-flight tasks resume after a
restore. Results (`results/`) and `workspaces/` are not included unless `--with-results`.

A backup is only as good as its restore test. Restore into a scratch directory periodically:

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /tmp/bacmap-restore
bacmap doctor --home /tmp/bacmap-restore
```

## 3. Restore

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # target is non-empty
```

- Refuses a non-empty target unless `--force`; existing files not in the archive are not deleted.
- Rejects `..` and absolute entries (zip-slip).
- Runs `PRAGMA integrity_check` on every restored database; a failure aborts.
- After restoring, run `bacmap doctor`; migrations apply automatically if the archive is older.

## 4. Event retention

`tasks.sqlite.events` records plan/task transitions, steps and approvals. It is an audit aid, not
the source of truth.

```bash
bacmap events prune --days 180
bacmap events prune --days 0      # everything (rarely appropriate)
```

Gate evaluations, run records, approvals and releases live in their own tables and are **not**
touched.

## 5. Results layout migration

Results are written to `results/runs/<task_id>/<dataset>/`; flat paths are links to the latest run.

```bash
bacmap results migrate --dry-run   # list legacy flat directories (datasets + snp/cgmlst)
bacmap results migrate             # move to runs/legacy-<name>/ and link
```

Rules:

- Never deletes data: an existing `runs/legacy-*` target gets an incrementing suffix.
- A new analysis also migrates leftovers before linking, so an upgrade cannot turn a successful run
  into a failed task.
- Do not create real `results/<dataset>` directories by hand; they are migrated on the next run.

## 6. Schema migrations

- Every database has a numbered migration list and `PRAGMA user_version`.
- Migrations run automatically at startup in one transaction, after copying to `<db>.bak-v<N>`.
- A database newer than the running code is refused (no silent downgrade).
- Lists are append-only; never edit a published migration.
- Add new tables/columns through `store/migrations.py` or the file-level lists in
  `store/schema.py`.

## 7. Upgrade checklist

1. `bacmap doctor` — record the current state.
2. `bacmap backup --out …` — including `dbos.sqlite`.
3. Let running tasks finish or cancel them; `bacmap task list` shows non-terminal tasks.
4. Update the environment: `pixi install` (and `pixi install -e dev` for development).
5. Restart `bacmap web` / `bacmap mcp`; redeploy happens automatically with a content-hash check.
6. `bacmap doctor`; verify the database version.
7. Smoke test: `bacmap overview`, `bacmap run list`, one small `analyze` or `record`.

Rollback: restore the backup from step 2. A database migrated by a newer build cannot be opened by an
older build; do not downgrade in place.

## 8. Runtime isolation

MCP profiles protect data that flows through MCP, not a harness's own shell. For external harnesses:

- run bacmap under a dedicated OS account with `BACMAP_HOME` mode `0700`;
- run `bacmap web` and `bacmap mcp --transport http` as that account, bound to loopback;
- give the harness only the MCP URL/token, never the Web token.

See [Security](../concepts/security.md) for the threat model.
