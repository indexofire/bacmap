# Multi-user accounts and roles

> Status: implemented (v1.10.49, 2026-11-26). Single-token deployments remain supported;
> `accounts` is an explicit opt-in mode.

bacmap supports two Web identity models:

| Mode | Configuration | Use case |
|---|---|---|
| Single token (default) | `BACMAP_WEB_AUTH=bearer` or `cookie` + `BACMAP_WEB_TOKEN` | Personal workstation, automation |
| Local accounts | `BACMAP_WEB_AUTH=accounts` | Several people sharing one workstation |

```bash
# The first administrator must be created from a local shell (no anonymous sign-up). A local
shell can read the database, so it is treated as operator/admin and is outside Web RBAC.
BACMAP_HOME=/srv/bacmap bacmap user create admin --role admin

export BACMAP_WEB_AUTH=accounts
BACMAP_HOME=/srv/bacmap bacmap start web
```

## Personal mode (hash-key login)

For a single-user workstation, personal mode needs only an access key, not a username/password.

```bash
bacmap personal init            # generate bk_… and the built-in owner (admin)
export BACMAP_WEB_AUTH=personal
bacmap start web                # still loopback-only by default

bacmap personal status          # initialized or not (never prints the key)
bacmap personal init --rotate   # rotate; the old key stops working immediately
```

- The key is shown once; `$BACMAP_HOME/personal.json` stores only its scrypt hash (mode 0600).
- Login creates a **server-side session** for the built-in `owner` (always admin, full features).
- Rotation does not revoke existing sessions; log out or restart the Web service if needed.
- `bacmap user` still manages accounts, but Web login accepts only the access key in this mode.

## Switching between personal and accounts

Both modes share the same tables (`users` / `web_sessions` / `api_tokens` from migration 4).
Switching only changes `BACMAP_WEB_AUTH`: **no migration runs and no domain table changes**,
so there is nothing to rebuild.

- **accounts → personal**: existing accounts, API tokens and browser sessions are kept.
  Other users' sessions remain valid until their 12-hour expiry, and personal API tokens keep
  working; for strict single-user operation, revoke those tokens and clear `web_sessions`
  while the Web service is stopped (or use a separate `BACMAP_HOME`).
- **personal → accounts**: the built-in `owner` created by `personal init` is an admin, but
  its password is random and never shown. Before switching, create or reset an administrator
  from the local shell:

  ```bash
  bacmap user create ops-admin --role admin
  # or
  bacmap user passwd owner
  ```

- `personal.json` only affects personal login; it can stay when switching back to accounts
  (it is ignored), and deleting it does not delete the `owner` account or sessions.
- Domain data, `owner_user_id` and import proposal `created_by` / `reviewed_by` are unchanged;
  personal mode logs in as `owner` (admin), so it can see all data.

## Roles

| Permission | admin | analyst | user |
|---|---|---|---|
| Read all specimens/isolates/results | yes | yes | own only |
| Submit analysis tasks | yes | yes | yes |
| Create/confirm plans, approve tasks | yes | yes | no |
| Record metadata/lab/knowledge | yes | yes | no |
| Upload wet-lab import proposals | yes | yes | yes (own only, review required) |
| Propose edits/deletes/creates/links | yes | yes | yes (own visible data, review required) |
| Review proposals | yes | yes | no |
| Delete specimens/isolates, purge runs | yes | yes | no |
| Research, runs, GOM, system overview | yes | yes | no |
| Manage users | yes | no | no |

After approval, unowned specimens/isolates are claimed for the submitter; existing owners
are never overwritten. For a `user`, "own" means tasks/plans whose `submitted_by` is their username, plus
specimens/isolates/results whose `owner_user_id` is theirs. Legacy unowned data is visible
only to analyst/admin; an administrator can assign it with
`bacmap specimen assign-owner <specimen> <username>`.

## Security

- Passwords: stdlib `scrypt` (N=16384, r=8, p=1), random per-user salt; only the derived
  value is stored.
- Browser sessions: the server stores a SHA-256 hash in `web_sessions`; the cookie carries
  only a random token. Disabling a user or resetting a password revokes that user's sessions and API
tokens immediately; a role change applies on the next request.
- Login throttling: 10 failures per username + source IP in 5 minutes returns 429.
- CSRF: the ADR-14 controls remain (`SameSite=Strict`, `Origin/Referer`, double-submit).
- Approvals and plan confirmations use the server-side principal; the request-body
  `approver`/`confirmer` fields are only kept for the legacy single-token mode.
- Audit: login/logout/user creation/role changes/disable are appended to the domain event
  log (D2; no passwords or token values).
- API tokens: `bacmap user token create <username>` issues `bm_...`, shown once. They are
  for scripts/API clients (the local CLI reads the database directly and needs no token) and
  inherit the account role. **MCP still uses a separate service token and
  Profile and is not per-user yet**; give it only to trusted operators/local agents, never a
  user's browser session.

## Storage

`data/bacmap.sqlite` migration 4:

```
users(user_id, username UNIQUE COLLATE NOCASE, password_hash, role,
      display_name, disabled, created_at, updated_at)
web_sessions(session_hash PK, user_id, created_at, expires_at,
             last_seen_at, client_ip, user_agent)
api_tokens(token_hash PK, user_id, name, created_at, last_used_at,
           expires_at, revoked_at)
specimens.owner_user_id / isolates.owner_user_id
```

The last active administrator cannot be disabled or demoted.

## CLI

```bash
bacmap user list
bacmap user create <username> --role admin|analyst|user
bacmap user set-role <username> admin
bacmap user disable <username> [--enable]
bacmap user passwd <username>
bacmap user token create <username> --name cli-laptop
bacmap user token list <username>
bacmap user token revoke <username> <token-prefix>

bacmap specimen assign-owner <specimen> <username>
bacmap specimen assign-owner <specimen> --clear
```

## AI data ceiling

Organisation mode can cap every AI call in configuration:

```toml
[llm.data_policy]
cloud_max_data_class = "D1"   # endpoint-location cap (default D1, at most D2)
ai_max_data_class = "D2"      # AI-wide cap: D0–D4, default D4
```

The effective class is **min(AI-wide cap, endpoint policy, role max_data_class)**.
With `ai_max_data_class = "D2"`, even a local endpoint receives no D3/D4 payload, and the
import-mapping advisor falls back to schema/aggregate-only mode. A cloud endpoint can only
ever see schema/aggregates (D1) unless the v1.10.51 debug double switch is explicitly on.

## Result index and browsing

At 100k scale bacmap no longer scans `results/*/report/*_summary.json` on every request or
loads every row into the browser:

- `strain_genotype_index` gains specimen/isolate IDs, assembly metrics, CARD/VFDB/plasmid
  counts, owner and analysis time;
- the analyze ingest step writes the index directly;
- run `bacmap results reindex --backfill-metadata` once for historical results (existing rows get only the new columns; GOM links are preserved);
- `/api/v1/samples`, `/api/v1/species`, `/api/v1/specimens` and `/api/v1/isolates` accept
  server-side filters (`q`, `species`, `st`, `serotype`, `amr_gene`) and paging;
- the console adds a Species page and a User management page; the sequencing-data table is
  server-paginated.

Measured on 100k synthetic results + 120k isolates + a 100k-row index (~38 MB): count
<0.1 ms, deep paging <1 ms, species filter + page ~3 ms, full-table `LIKE` ~20 ms.
**DuckDB is not introduced as a primary database.** Revisit an optional read-only analytics
sidecar only if data reaches tens of millions of rows or heavy Parquet/wide-table ad-hoc
analysis becomes a real requirement.
