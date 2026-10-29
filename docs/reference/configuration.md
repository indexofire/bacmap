# Configuration reference

Configuration is **environment variables + one TOML file**. Paths are never derived from the source
tree (ADR-03). When `config.toml` is absent, built-in defaults apply.

## 1. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | data root |
| `BACMAP_DATA_DIR` | `$BACMAP_HOME/data` | metadata/reference databases |
| `BACMAP_DB_PATH` | `$DATA_DIR/bacmap.sqlite` | strain metadata + lab results |
| `BACMAP_GOM_DB` | `$BACMAP_HOME/gom.sqlite` | GOM, datasets, strain index |
| `BACMAP_RUNS_DB` | `$BACMAP_HOME/runs.sqlite` | run records |
| `BACMAP_RESULTS_DIR` | `$BACMAP_HOME/results` | results |
| `BACMAP_WORKFLOWS_DIR` | `$BACMAP_HOME/workflows` | deployed workflows |
| `BACMAP_WORKFLOW_STATE_DIR` | `$BACMAP_HOME/workflow_state` | Snakemake state/logs |
| `BACMAP_REFS_DIR` | `$BACMAP_HOME/refs` | external DBs + manifest |
| `BACMAP_ENV_LOCK` | `$BACMAP_HOME/pixi.lock` | env lock hashed into run records |
| `BACMAP_WEB_URL` | `http://127.0.0.1:8800` | base for plan `confirm_url` |
| `BACMAP_MCP_TOKEN` | — | bearer token for MCP HTTP |
| `BACMAP_WEB_TOKEN` | — | bearer token for Web/API |
| `BACMAP_WEB_AUTH` | `bearer` | `bearer` or `cookie` |
| `BACMAP_WEB_SECRET` | derived from token | HMAC key for session cookies |
| `BACMAP_WEB_COOKIE_SECURE` | off | `1` adds `Secure` to cookies |
| `BACMAP_ALLOW_UNSANDBOXED` | off | `1` allows direct execution (dev only) |
| `CHECKM2_DB` | — | CheckM2 database path |
| `GTDBTK_DATA_PATH` | — | GTDB-Tk database path |

`--home` overrides `BACMAP_HOME` per command. `--token-env` changes the env var name for the Web/MCP
token.

## 2. `config.toml` overview

```toml
[llm.data_policy]
cloud_max_data_class = "D1"

[llm.endpoints.strata]
location = "local"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3.8-flash-next-iq3_xxs"

[llm.routing]
interpretation = "strata"

[llm.resources]
co_located = true
min_free_ram_gb_for_heavy_steps = 24.0

[mcp]
allow_local_trusted = false

[plans.auto_confirm]
enabled = false
max_samples = 20
```

## 3. LLM endpoints

Endpoints are OpenAI-compatible. Multiple endpoints may coexist; `[llm.routing]` maps a purpose to an
endpoint by name.

### 3.1 Endpoint keys

| Key | Default | Notes |
|---|---|---|
| `location` | `local` | `local` / `lan` / `cloud`; cloud is data-class constrained |
| `base_url` | required | OpenAI-compatible base URL |
| `model` | required | model name |
| `kind` | `openai_compatible` | reserved |
| `tier` | `T2` | capability tier; roles declare a minimum |
| `max_concurrency` | `1` | per-endpoint semaphore (local models often need 1) |
| `api_key_env` | — | **name** of the env var holding the key |
| `enabled` | `true` | disable without deleting |
| `supports_tools_with_schema` | `false` | endpoint capability metadata |
| `constrained_decoding` | `false` | capability metadata |
| `request_timeout_s` | `300` | per-request timeout |
| `admin_url` | — | Strata `/load` `/unload` management endpoint |

### 3.2 Routing

```toml
[llm.routing]
interpretation = "deepseek"          # used by agent/interpret.py
```

If a purpose has no route, the first enabled endpoint is used and a warning is logged. Pin routes
explicitly to avoid accidental cloud egress.

### 3.3 Data policy

```toml
[llm.data_policy]
cloud_max_data_class = "D1"   # D1 or D2; D3/D4 rejected at parse time
```

The gateway compares the payload class before sending to a `cloud` endpoint and raises
`DataClassViolationError` above the ceiling. This cannot be raised above D2 by configuration.

### 3.4 Resources (ADR-17)

```toml
[llm.resources]
co_located = true
min_free_ram_gb_for_heavy_steps = 24.0
```

When the model and pipeline share a host, heavy steps can request the model be unloaded. Set
`co_located = false` when the model runs elsewhere.

## 4. MCP

```toml
[mcp]
allow_local_trusted = false   # must be the boolean true to start --profile local-trusted
```

MCP servers default to the `cloud` profile. The profile ceiling is the same
`cloud_max_data_class`. See [MCP reference](mcp.md).

## 5. Plans

```toml
[plans.auto_confirm]
enabled = false
max_samples = 20
```

Auto-confirm applies only to `analyze` plans that:

- reference a non-empty list of already registered `samples`;
- do not use `fasta_dir`/`fastq_dir` (directory ingestion) or scripts;
- have at most `max_samples` samples.

`mine`, `write`, `curate` and record tasks are never auto-confirmed. A malformed `max_samples`
fails safe to “human confirmation required”. The audit actor is `policy:auto-confirm`.

## 6. Sample registration

`samples.tsv` is a data file, not `config.toml`:

```tsv
sample	species	R1	R2	assembly	isolate	platform	checksum
SAM-001	Salmonella	gs/SAM-001/SAM-001_R1.fastq.gz	gs/SAM-001/SAM-001_R2.fastq.gz			SAM-001	ilm	<sha256>
```

See [Data & identity](../guide/data.md) for column semantics, naming, collisions and registration.

## 7. Directory and database layout

```text
$BACMAP_HOME/
├── data/                 # bacmap.sqlite, knowledge.sqlite
├── results/runs/<task_id>/...
├── workflows/bacmap/     # deployed DAG + samples.tsv
├── workflow_state/       # logs/state
├── gs/                   # raw inputs (convention)
├── workspaces/<task_id>/ # mine workspaces
├── runs/<run_id>/run_manifest.json
├── refs/manifest.json
├── tasks.sqlite
├── dbos.sqlite
├── runs.sqlite
├── gom.sqlite
└── baseline.sqlite
```

## 8. External databases

`refs/manifest.json` is read into every run record:

```json
{"databases": [
  {"name": "gapit:card", "version": "3.2.6", "checksum": "sha256:..."},
  {"name": "gmlst:senterica_2", "version": "2026-09", "checksum": "sha256:..."}
]}
```

Missing or malformed files yield an empty list; bacmap does not guess versions.

## 9. Web and API auth

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
export BACMAP_WEB_AUTH=cookie          # optional browser login
export BACMAP_WEB_SECRET="..."         # optional explicit HMAC key
export BACMAP_WEB_COOKIE_SECURE=1      # behind TLS
bacmap web --host 127.0.0.1 --port 8800
```

- A non-loopback host without a token refuses to start.
- Bearer mode is for API clients; browsers cannot set the header.
- Cookie mode adds `/login`, signed `HttpOnly` sessions and CSRF on POST.
- `BACMAP_WEB_URL` controls the plan `confirm_url` (default loopback).

## 10. Sandbox

| Setting | Default | Notes |
|---|---|---|
| backend | Apptainer → Podman | auto-detected at runtime |
| image | `mine.sandbox_image`, default `docker://python:3.12-slim` | per-plan field; no environment variable |
| `BACMAP_ALLOW_UNSANDBOXED` | off | direct host execution; dev only |
| network | none | enforced by the container backend |
| mounts | results/GOM/datasets read-only | declared input paths only |

Docker is not supported. Without a backend, `mine` fails with `sandbox_unavailable`.

## 11. Validation and failure behaviour

- Unknown TOML keys in typed sections are rejected (pydantic `extra="forbid"`).
- `cloud_max_data_class` above D2 is a parse error.
- Invalid `plans.auto_confirm.max_samples` disables auto-confirm (fail-safe).
- A database newer than the code is refused; restore a matching backup instead of downgrading.
- `config.toml` may contain only the name of a secret env var, never the key itself.
