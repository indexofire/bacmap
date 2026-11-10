# Accounts & multi-user (PLAN #11)

> Status: design proposal (2026-11-09), awaiting user confirmation before implementation.

## Three deployment modes

```
Mode 1: single user            Mode 2: multi-user (org)       Mode 3: multi-system (regional)
┌──────────────┐               ┌──────────────────┐          ┌─────┐ ┌─────┐ ┌─────┐
│  bacmap      │               │      bacmap       │          │bm-A │ │bm-B │ │bm-C │
│  (one user)  │               │  (multiple OS     │          │     │ │     │ │     │
│              │               │   accounts)       │          └──┬──┘ └──┬──┘ └──┬──┘
│  full auto ✓ │               │  user→admin review│             └───────┼───────┘
│  no login ✓  │               │  roles            │                     │
└──────────────┘               └──────────────────┘          ┌──────────────────┐
                               │  OS-level        │          │ aggregation node  │
                               │  isolation       │          │ (queries many     │
                               └──────────────────┘          │  instances)       │
                                                             └──────────────────┘
```

## Mode 1: single user (default, current)

- Web without login (cookie token, loopback only)
- CLI without login
- `[plans.auto_confirm]` can go fully automatic
- **Suited for**: individual researchers, automated analysis

## Mode 2: multi-user (organisational deployment, e.g. a CDC)

### Architecture: multiple OS accounts (recommended)

One OS account per user; bacmap runs as a service account:

```
┌────────────────────────────────────────────────┐
│ bacmap service process (service account,       │
│ ports 8800/8765)                               │
├────────────────────────────────────────────────┤
│ Web UI (each user's browser login → own token) │
│ MCP (each agent → own token + profile)         │
└────────────────────────────────────────────────┘
```

### Roles

| Role | Permissions | Typical user |
|---|---|---|
| `admin` | Everything + user management + policy configuration + auto_confirm control | System administrator |
| `analyst` | Submit analyses + view results + review gates (mining signatures / citation review) | Laboratory technician |
| `user` | Submit requests + view own results | Clinical / field staff |

### Review workflow

```
user submits analysis request (web form)
    ↓
analyst/admin reviews → converts into a plan
    ↓
admin confirms the plan (or auto_confirm policy)
    ↓
analysis runs → results generated
    ↓
analyst reviews results (mining gate / citation gate)
    ↓
user views reviewed results/reports
```

### Technical realisation

| Layer | Change |
|---|---|
| Web auth | Multi-user tokens (`users` table + bcrypt passwords + roles) |
| Permissions | FastAPI middleware (role → allowed routes/operations) |
| MCP | Each token bound to a role → tool belt filtered by role |
| CLI | `bacmap login` (fetch token into `~/.bacmap/credentials`) |
| Audit | `events` table exists → add `actor_role` field |
| Plans | `PlanService` gains `submitted_by_role` → auto_confirm policy per role |

### TUI/CLI login

```bash
# First login (fetch token)
bacmap login --server http://bacmap.cdc.local:8800
# → browser opens OAuth page → or terminal username/password
# → token written to ~/.bacmap/credentials (mode 0600)

# Subsequent CLI commands use the token automatically
bacmap task list
bacmap plan confirm abc123
```

## Mode 3: multi-system (regional / provincial)

### Architecture: federation

Each server runs bacmap independently (data never leaves the local network); an
upper node **only aggregates reports**:

```
CDC-A (bacmap)     CDC-B (bacmap)     CDC-C (bacmap)
     │                   │                   │
     └─── aggregate ─────┴─── aggregate ─────┘
                │
     ┌──────────┴──────────┐
     │  regional reporting  │
     │  node (read-only API │
     │  aggregation; no raw │
     │  data storage)       │
     └─────────────────────┘
```

### Technical realisation

- Each node exposes a **read-only API** (`--read-only` mode + API token)
- The aggregation node calls each node's `/api/v1/stats`, `/api/v1/samples/search`
- **Raw sequences / sensitive data never leave the local network** (ADR-16)
- The aggregation node only receives: species distribution, ST distribution, resistance-rate statistics (D0/D1 aggregates)

```bash
# Aggregation-node query
bacmap federate query --node cdc-a:8800 --node cdc-b:8800 \
  --stats "species_distribution,amr_rates" --format table
```

## Implementation priority

| Phase | Content | Version |
|---|---|---|
| 1 | Mode 2 basics: web multi-user + roles + review UI | 0.2.0 |
| 2 | CLI login + token management | 0.2.0 |
| 3 | MCP role binding | 0.2.1 |
| 4 | Mode 3 federated queries (read-only API aggregation) | 0.3.0 |
