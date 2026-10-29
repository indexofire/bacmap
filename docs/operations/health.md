# Health checks and retention

## 1. `bacmap doctor`

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

## 2. Logs and task state

```bash
bacmap task list
bacmap task show <task_id>
ls "$BACMAP_HOME/workflow_state/log/"
```

- DBOS reconciles running tasks when status/list is read; a stale `running` usually means the
  process died and was not restarted.
- Pipeline logs are under `workflow_state/log/`; a mine task's stdout/stderr stays in its workspace.

## 3. Event retention

`tasks.sqlite.events` records plan/task transitions, steps and approvals. It is an audit aid, not the
source of truth.

```bash
bacmap events prune --days 180
bacmap events prune --days 0      # everything (rarely appropriate)
```

Gate evaluations, run records, approvals and releases live in their own tables and are **not**
touched. Decide the retention period with your institution's audit policy.

See [Troubleshooting](troubleshooting.md) for failure categories and fixes.
