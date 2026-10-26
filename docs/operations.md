**English** | [简体中文](operations.zh-CN.md)

# Operations guide

Day-two tasks: health checks, backups, restores, event retention, schema migrations and upgrades.
Everything here runs on the single workstation; no service or daemon is required.

## 1. Health check: `bacmap doctor`

```bash
bacmap doctor                 # human-readable
bacmap doctor --json          # machine-readable (CI / monitoring)
```

Checks and what to do when they are not green:

| Check | Meaning | If it fails |
|---|---|---|
| `home` | `BACMAP_HOME` exists and is writable | Fix ownership (`chown`) or point `--home` at the right directory |
| `database` | `tasks.sqlite` schema version matches the code | Older: start any command to migrate (a backup is taken automatically). Newer than the code: you downgraded — use the newer bacmap build |
| `sandbox` | Sandbox backend (`apptainer`/`podman`); `passthrough` means **no isolation** | Install Apptainer or Podman (installation guide §6) before running `mine` |
| `llm` | Configured LLM endpoint reachability | Deterministic functions still work (C3); fix the endpoint per configuration guide §2 |
| `disk` | Free space ≥ 1 GB | Free space or move `BACMAP_HOME` |
| `tools` | `gside`, `gapit`, `gmlst`, `snakemake` on `PATH` | Run inside `pixi shell`, or reinstall the environment |

Exit code is `1` when any check is `fail` (warnings do not fail the command).

## 2. Backup: `bacmap backup`

```bash
bacmap backup --out /backup/bacmap-2026-10-26.zip
bacmap backup --out /backup/full.zip --with-results   # includes results/ (large)
```

What goes in, and how:

- `config.toml`, `refs/manifest.json`;
- every SQLite database (`tasks`, `runs`, `gom`, `baseline`, `data/bacmap`, `data/knowledge`) —
  copied with SQLite's **backup API**, so the snapshot is consistent even while a task runs;
- `runs/*/run_manifest.json` (the on-disk half of the evidence chain, ADR-18).

`results/` (reports, per-sample artefacts) and `workspaces/` are **not** included by default; add
`--with-results` when you need a full archive.

## 3. Restore: `bacmap restore`

```bash
bacmap restore --from /backup/bacmap-2026-10-26.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # target already has data
```

- Refuses a non-empty target unless `--force` (and never deletes files that are not in the archive).
- Rejects archive entries with `..` or absolute paths (zip-slip protection).
- Runs `PRAGMA integrity_check` on every restored database; a failure aborts with a clear message.
- After restoring, run `bacmap doctor` and start the service; migrations apply automatically if the
  archive is older than the code.

## 4. Event retention: `bacmap events prune`

Domain events (`tasks.sqlite.events`) record plan and task transitions, steps and approvals. They are
the audit trail for coordination, **not** the source of truth (task/plan tables are).

```bash
bacmap events prune --days 180     # keep half a year, delete older
bacmap events prune --days 0       # delete everything (rarely appropriate)
```

Decide the retention period with your institution's audit policy. Gate evaluations, run records and
approvals in their own tables are **not** touched by this command.

## 5. Schema migrations

- Every database has a numbered migration list and a `PRAGMA user_version`; see
  `bacmap/store/migrations.py` and the per-file lists (`tasks`, `runs`, `baseline`, `gom`, `data`,
  `knowledge`).
- Migrations run automatically at start-up, in one transaction, after copying the file to
  `<db>.bak-v<N>`.
- A database newer than the running code is refused rather than silently downgraded.
- Migrations are append-only; never edit a published migration.

## 6. Upgrade checklist

1. `bacmap doctor` (record the current state).
2. `bacmap backup --out …` (see §2).
3. Stop running tasks or let them finish; `bacmap task ls` shows non-terminal ones.
4. Update the environment (`pixi install`) and restart `bacmap web` / `bacmap mcp`.
5. `bacmap doctor` again; check `database` shows the new version.
6. Re-run the smoke test: `bacmap overview`, `bacmap run ls`, one small `analyze` or `bacmap record`.

Rollback: restore the backup from step 2 with `bacmap restore --force`. Note that a database migrated
by a newer build cannot be opened by an older one (the version check refuses it) — restore the backup
instead of downgrading in place.

## 7. Runtime isolation (recommended)

MCP profiles protect data that flows through MCP; they cannot stop a harness's own shell. For
deployments with external harnesses:

- run bacmap under a dedicated system account with `BACMAP_HOME` mode `0700`;
- run `bacmap web` and `bacmap mcp --transport http` as that account, bound to `127.0.0.1`;
- give the harness only the MCP URL and token, never the Web token.

See the [agent harness guide](harnesses.md) §4 for the reasoning and residual risks.
