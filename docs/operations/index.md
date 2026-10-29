# Operations

Day-two work on a single workstation: health checks, backup/restore, migrations, upgrades and
retention. No daemon or service manager is required.

<div class="grid cards" markdown>

-   **Health and retention**

    ---

    `bacmap doctor`, task/log inspection and event retention.

    [Health checks](health.md)

-   **Backup and restore**

    ---

    Consistent SQLite snapshots, run manifests, DBOS checkpoints and restore safety.

    [Backup and restore](backup.md)

-   **Upgrades and migrations**

    ---

    Upgrade checklist, result-layout migration, schema migrations and rollback.

    [Upgrades](upgrades.md)

-   **Troubleshooting**

    ---

    Submission/plan errors, pipeline failures, sandbox, auth and evidence problems.

    [Troubleshooting](troubleshooting.md)

</div>

## Daily checks

```bash
bacmap doctor
bacmap task list
bacmap run list
```

For the security model behind runtime isolation, see [Security](../concepts/security.md).
