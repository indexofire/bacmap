# Upgrades and migrations

## 1. Upgrade checklist

1. `bacmap doctor` — record the current state.
2. `bacmap backup --out …` — including `dbos.sqlite`.
3. Let running tasks finish or cancel them; `bacmap task list` shows non-terminal tasks.
4. Update the environment: `pixi install` (and `pixi install -e dev` for development).
5. Restart `bacmap web` / `bacmap mcp`; redeploy happens automatically with a content-hash check.
6. `bacmap doctor`; verify the database version.
7. Smoke test: `bacmap overview`, `bacmap run list`, one small `analyze` or `record`.

Rollback: restore the backup from step 2. A database migrated by a newer build cannot be opened by an
older build; do not downgrade in place.

## 2. Results layout migration

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

## 3. Schema migrations

- Every database has a numbered migration list and `PRAGMA user_version`.
- Migrations run automatically at startup in one transaction, after copying to `<db>.bak-v<N>`.
- A database newer than the running code is refused (no silent downgrade).
- Lists are append-only; never edit a published migration.
- Add new tables/columns through `store/migrations.py` or the file-level lists in
  `store/schema.py`.

## 4. Runtime isolation

MCP profiles protect data that flows through MCP, not a harness's own shell. For external harnesses:

- run bacmap under a dedicated OS account with `BACMAP_HOME` mode `0700`;
- run `bacmap web` and `bacmap mcp --transport http` as that account, bound to loopback;
- give the harness only the MCP URL/token, never the Web token.

See [Security](../concepts/security.md) for the threat model.
