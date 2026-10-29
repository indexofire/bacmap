# Interfaces: Web, CLI, TUI and JSON API

All four interfaces use the same task engine, gates and audit trail. Use whichever fits the moment;
you can start a task in one and approve it in another.

## 1. Web console

```bash
bacmap web                                  # 127.0.0.1:8800 by default
bacmap web --host 127.0.0.1 --port 8800
```

Pages:

| Route | Purpose |
|---|---|
| `/` | task list and submit form (analyze/curate) |
| `/tasks/{id}` | task detail, live status fragment, approval card |
| `/plans`, `/plans/{id}` | agent-proposed plans, full parameters, confirm/reject |
| `/samples`, `/samples/{id}` | completed samples, per-sample findings |
| `/samples/{id}/report` | inline HTML report (`?download=1` for attachment) |
| `/search` | keyword/serotype/ST/gene search |
| `/records` | metadata, lab result and knowledge entry forms |
| `/runs`, `/gom` | immutable run records and GOM objects |
| `/overview` | system overview (versions, paths, policy, sandbox) |
| `/api/v1/*` | JSON API (see [HTTP API reference](../reference/api.md)) |

The task detail page polls `/tasks/{id}/fragment` every two seconds; no external JavaScript or CDN
is used (offline-friendly).

### Submitting a task

The form accepts **registered dataset IDs**, separated by ASCII commas or newlines:

```text
SAM-TYP-001, SAM-TYP-002
```

Paths and natural-language requests are rejected. For `curate`, the optional `scope` is a JSON
object:

```json
{"pathogen": "Salmonella", "strains": ["HZCPE-01"]}
```

Use a plan (from an agent) for `mine`/`write`; the form deliberately exposes only `analyze` and
`curate`.

### Approval

When a task reaches `awaiting_approval`, the detail page shows an approval card. The approver name,
decision and signature are recorded in the `approvals` table and emitted as an event. Signing is one
of the human-only actions; agents cannot do it.

## 2. CLI

```bash
bacmap --version
bacmap overview [--json]
bacmap doctor [--json]
bacmap task list|show|submit|approve|cancel
bacmap plan list|show|confirm|reject
bacmap record metadata|lab|knowledge-import|knowledge-approve
bacmap run list|show|compare
bacmap gom list|show
bacmap isolate list|show
bacmap sample ls|show
bacmap search [--query ...] [--serotype ...] [--st ...] [--gene ...]
bacmap results migrate [--dry-run]
bacmap events prune --days N
bacmap backup --out FILE [--with-results]
bacmap restore --from FILE [--force]
bacmap mcp   # MCP server
bacmap web   # Web console
bacmap tui   # task console
bacmap console  # numbered menu
```

Query commands accept `--json`; task/plan IDs accept unique prefixes, so the 12 characters shown by
`task list` work directly.

### Submit and follow an analysis

```bash
bacmap task submit --type analyze --samples SAM-TYP-001
# => task_id

bacmap task list
bacmap task show 3f9c2a1b
bacmap task show 3f9c2a1b --json | jq .state
```

Register a directory instead of hand-editing samples.tsv:

```bash
bacmap task submit --type analyze --fasta-dir /data/genomes
bacmap task submit --type analyze --fastq-dir /data/run42 --species Salmonella
```

### Curate the local baseline

```bash
bacmap task submit --type curate --scope '{"pathogen":"Salmonella"}'
bacmap task show <task_id>          # ends in awaiting_approval
bacmap task approve <task_id> \
  --approver "Jane Doe" --decision approve --signature "jd-2026-10-30"
```

### Confirm an agent plan

```bash
bacmap plan list
bacmap plan show <plan_id>                 # full tasks, hash, input fingerprints
bacmap plan confirm <plan_id> --version 1 --hash <first 12+ chars>
bacmap plan reject <plan_id> --version 1 --reason "wrong sample"
```

If `--hash` is omitted, `plan confirm` prints the plan and asks interactively; scripts should pass
the hash explicitly.

### Records

```bash
bacmap record metadata --strain-id HZCPE-01 \
  --field isolation_date=2026-10-12 --field province=Guangdong --field sample_source=food
bacmap record lab --strain-id HZCPE-01 --category mic \
  --test-name meropenem --result 0.25 --unit mg/L --interpretation S
bacmap record knowledge-import --title "O3:K6 outbreak" --identifier PMID:12345678
bacmap record knowledge-approve 7
```

Each command submits a `record` task; check it with `bacmap task show`.

### Exit codes and JSON

- `0` success, `1` check failed / operation failed, `2` argument error (argparse).
- `--json` prints one JSON document; diagnostics go to stderr.
- `bacmap doctor` exits `1` only when a check has status `fail`.

## 3. TUI task console

```bash
bacmap tui
```

The TUI is a dashboard plus explicit operations; there is **no chat**.

| Key | Action |
|---|---|
| `Enter` | run the current slash command |
| `Esc` | cancel a pending approval / focus the input |
| `Ctrl+B` | toggle the sidebar |
| `Ctrl+R` | refresh |
| `Ctrl+L` | clear the log |
| `Ctrl+Y` | confirm a pending signature |
| `Ctrl+G` then `i/l/s/m/t/a/h/q` | focus input / tasks / samples / endpoint / theme / approve / help / quit |

Slash commands:

```text
/help
/clear
/tasks
/samples
/search <keyword>
/model
/result <sample>
/approve <task-id> [signature]
/analyze <sample>
/curate [scope-json]
/quit
```

`/approve` performs a two-step confirmation: the hint bar shows the task and signature; `Ctrl+Y`
submits, `Esc` cancels.

## 4. Interactive console

```bash
bacmap console
```

A numbered menu for users who prefer prompts over subcommands. It uses the same engine and gates;
it is not a separate implementation.

## 5. JSON API (`/api/v1`)

The Web server also exposes a versioned JSON API under the same authentication. It is a **trusted
operator surface**: whoever holds the Web token can approve and confirm. Never give that token to an
external harness — harnesses use MCP.

```bash
TOKEN=...                         # BACMAP_WEB_TOKEN
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/tasks | jq .

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version":1,"plan_hash":"c1d2e3f4a5b6...","confirmer":"jane"}' \
  http://127.0.0.1:8800/api/v1/plans/<plan_id>/confirm
```

Full endpoint and error reference: [HTTP API](../reference/api.md).

## 6. Remote access and authentication

`bacmap web` binds to `127.0.0.1` by default. For remote access, use an SSH tunnel:

```bash
ssh -L 8800:127.0.0.1:8800 user@workstation
# then open http://127.0.0.1:8800 locally
```

If you bind a non-loopback address, bacmap refuses to start without a token:

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap web --host 0.0.0.0 --port 8800
```

Two auth modes:

- `bearer` (default): API clients send `Authorization: Bearer <token>`; browsers cannot set this
  header, so the HTML console returns a short 401 explanation (use an SSH tunnel).
- `cookie`: set `BACMAP_WEB_AUTH=cookie`; log in at `/login`; the session cookie is signed and
  `HttpOnly`, and every state-changing POST needs a CSRF token. Add
  `BACMAP_WEB_COOKIE_SECURE=1` behind TLS.

The MCP HTTP transport is separate: it always requires `BACMAP_MCP_TOKEN` (or `--token-env`) and is
covered in [Agents & plans](agent-plans.md).
