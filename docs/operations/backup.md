# Backup and restore

## 1. Backup

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

## 2. Restore

```bash
bacmap restore --from /backup/bacmap-2026-10-30.zip --home /srv/bacmap
bacmap restore --from ... --home /srv/bacmap --force   # target is non-empty
```

- Refuses a non-empty target unless `--force`; existing files not in the archive are not deleted.
- Rejects `..` and absolute entries (zip-slip).
- Runs `PRAGMA integrity_check` on every restored database; a failure aborts.
- After restoring, run `bacmap doctor`; migrations apply automatically if the archive is older.

## 3. What to back up outside bacmap

- Reference databases under `refs/` and any external CheckM2/GTDB-Tk paths (not copied by default).
- A copy of `BACMAP_HOME` permissions/ownership and systemd units.
- The environment lock (`pixi.lock`) if you rebuild the runtime elsewhere.

See [Upgrades](upgrades.md) for the upgrade sequence and rollback.
