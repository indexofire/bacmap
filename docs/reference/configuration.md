# Configuration reference

Configuration is **environment variables + one TOML file** (not YAML), plus an optional YAML
overlay for per-tool reference selection (§13). Data paths are never derived from the source tree
(ADR-03). Missing configuration means built-in defaults.

Template: [`config.example.toml`](https://github.com/indexofire/bacmap/blob/main/config.example.toml)
in the repository root, or run:

```bash
bacmap config init           # write $BACMAP_HOME/config.toml
bacmap config init --user    # write ~/.config/bacmap/config.toml
bacmap config init --project # write ./config.toml (gitignored in source checkouts)
bacmap config path           # show the file actually used
```

Resolution order:

1. a file explicitly named by `BACMAP_CONFIG`;
2. `$BACMAP_HOME/config.toml` (the existing single-machine form remains compatible);
3. `$XDG_CONFIG_HOME/bacmap/config.toml`, defaulting to `~/.config/bacmap/config.toml`;
4. built-in defaults when none exists.

A project-local `config.toml` is **not** discovered automatically; this is intentional (ADR-03).
After copying the template into a source checkout, export:

```bash
export BACMAP_CONFIG="$PWD/config.toml"
```

## 1. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `BACMAP_HOME` | `~/.local/share/bacmap` | data root |
| `BACMAP_CONFIG` | see resolution order | explicit config-file path; useful for project-local overrides |
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
| `BACMAP_LANG` | — | CLI display language override (`en`/`zh`); takes precedence over `[ui].language` |
| `BACMAP_TOOL_SELECTION` | — | explicit `tool_selection.yaml` overlay path (§13) |
| `BACMAP_DB_SELECTION` | — | legacy gapit-only overlay path (translated to `tool_selection.yaml`) |
| `BACMAP_RESEARCH_PROFILE` | `research` | default governance profile for Research Workbench (`open-test`/`research`/`publication`) |
| `BACMAP_DEBUG` | off | **development only**: explicit override of `[debug].enabled`; `1` enables, `0` disables. Disables Web auth/CSRF, plan confirmation, task approvals, gates, Research claim/publication gates and sandbox fallback. **MCP data-class ceilings and HTTP auth are not relaxed**; D3/D4→cloud remains blocked. |
| `BACMAP_BENCHMARK_DATA` | — | local public-data snapshot for research benchmarks; may be a dataset dir or a parent containing `bvbrc_kpn_meropenem`/`osf_n78q3` |
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

[ui]
language = "en"

[mcp]
allow_local_trusted = false

[debug]
enabled = false

[plans.auto_confirm]
enabled = false
task_types = ["analyze"]
max_samples = 20
max_tasks = 10
allow_directory_ingestion = false
allow_scripts = false
allow_drafts = false
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

## 4.1 Development debug mode

Debug mode can also be persisted in the configuration file instead of exported per command:

```toml
# $BACMAP_HOME/config.toml
[debug]
enabled = true
```

Precedence: an explicit `BACMAP_DEBUG` overrides `[debug].enabled`. After enabling it in the
file, `BACMAP_DEBUG=0` temporarily disables it:

```bash
BACMAP_DEBUG=0 bacmap doctor
```

A configuration-file setting is persistent; `bacmap doctor` reports `debug=warn`. Never enable
it in production. It does not relax the ADR-16 data boundary: D3/D4 still cannot be sent to a
cloud LLM endpoint. It also does not raise MCP data-class ceilings or bypass MCP HTTP auth:
`cloud` keeps `cloud_max_data_class`, `local-trusted` still needs
`[mcp] allow_local_trusted = true`, and HTTP always needs a token.

## 5. Plans

Auto-confirmation is off by default and remains fail-closed.

```toml
[plans.auto_confirm]
enabled = false
task_types = ["analyze"]       # choices: analyze / curate / mine / write
max_samples = 20               # analyze over an explicit samples list
max_tasks = 10                 # tasks per plan (hard maximum is also 10)
allow_directory_ingestion = false
allow_scripts = false
allow_drafts = false
```

The default is compatible with v1.9: only an `analyze` plan is auto-confirmed when it:

- uses a non-empty list of registered `samples`;
- does not use `fasta_dir`/`fastq_dir`;
- has at most `max_samples` samples.

Administrators may explicitly broaden it for automated iteration:

| Key | Broadens | Boundaries that remain |
|---|---|---|
| `task_types` | task types eligible for auto-confirm | unlisted types still need a human |
| `allow_directory_ingestion` | analyze over directory inputs | input fingerprints are still rechecked |
| `allow_scripts` | `mine` plans | scripts still run offline in a sandbox and pass the mining gate |
| `allow_drafts` | `write` plans | citation gate remains; export still needs a human signature |
| `max_tasks` | multi-task plans | over the limit means fail-closed |

`mine` requires both `task_types` containing `mine` and `allow_scripts = true`;
`write` requires both `write` and `allow_drafts = true`. Invalid policy values fall back to
human confirmation. The audit actor is `policy:auto-confirm`.

Example: fully automated analyze + mine iteration (explicit administrator choice):

```toml
[plans.auto_confirm]
enabled = true
task_types = ["analyze", "mine"]
max_samples = 100
allow_directory_ingestion = true
allow_scripts = true
```

Task-level approval gates are not removed. `curate` release, `mine` artefact sign-off, `write`
export and analysis-claim review can still enter `awaiting_approval` and require a human in
bacmap's trusted surfaces.

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
├── config/               # config.toml, optional tool_selection.yaml
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
bacmap start web --host 127.0.0.1 --port 8800
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
- Invalid `plans.auto_confirm` policy (`max_samples`/`max_tasks`/`task_types`/flags) disables auto-confirm (fail-safe).
- A database newer than the code is refused; restore a matching backup instead of downgrading.
- `config.toml` may contain only the name of a secret env var, never the key itself.

## 12. Display language

| Setting | Default | Notes |
|---|---|---|
| `[ui].language` | `en` | CLI help and message language; `en` or `zh` (case-insensitive) |
| `BACMAP_LANG` | — | environment override; takes precedence over the config file |

Invalid or missing values fall back to `en` deterministically (same tolerance as `[debug]`).
The setting affects CLI help, prompts and messages only — data, reports and JSON output are
unaffected.

## 13. Tool reference selection (`tool_selection.yaml`)

`core/pathogens.yaml` is the packaged species→reference mapping and is **never edited by users**;
local choices go into a YAML overlay so they survive upgrades:

| Layer | Location |
|---|---|
| packaged defaults | `core/pathogens.yaml` (gapit databases, gmlst schemes) |
| user/project overlay | `$BACMAP_HOME/config/tool_selection.yaml`, `BACMAP_TOOL_SELECTION`, the workflow `tool_selection` key, or `bacmap selection --selection PATH` |
| runtime species verdict | `species/species_id.json` (gside; workflow only) |

Overlay resolution: explicit path → `BACMAP_TOOL_SELECTION` → legacy `BACMAP_DB_SELECTION` →
`$BACMAP_HOME/config/tool_selection.yaml` → `$BACMAP_HOME/config/db_selection.yaml`. The legacy
file (`bacmap.db_selection/1`) is accepted as a gapit-only alias and flagged at load time.

Schema `bacmap.tool_selection/1`:

```yaml
schema: bacmap.tool_selection/1
defaults:                        # optional merge mode when an entry omits `mode`
  gapit: {mode: extend}          # extend (default) | replace
  gmlst: {mode: extend}
species:
  VPA:
    gapit:
      mode: extend               # registry defaults + listed databases
      databases: [vpa_ok, vpa_pai]
    gmlst:
      mode: replace
      modes: [mlst]              # mlst | cgmlst | wgmlst | tgmlst
      schemes: {mlst: vparahaemolyticus_1}
samples:
  S42:
    gapit: {databases: [vpa_ok]} # sample entry replaces the species list
meta:                            # optional provenance written by `selection select`
  generated_by: cli
  generated_at: "2026-11-07T00:00:00+00:00"
  approved_by: operator
```

Precedence is **sample > species > registry**. `gapit.databases` extends the registry list unless
`mode: replace`; `gmlst.modes` and `gmlst.schemes` merge unless `mode: replace`. Unknown species
codes, database names or scheme names are validation errors — nothing is guessed. A scheme is
only accepted when the gmlst catalog knows it (and, with `--downloaded-only`, when it is cached).

Inspect and write the overlay with the deterministic CLI; the pipeline never calls an LLM:

```bash
bacmap selection options --tool all --json   # catalog rows + current selection
bacmap selection show --diff                 # effective mapping vs registry
bacmap selection validate                    # unknown / undownloaded / mismatched entries
bacmap selection select --tool gmlst --species VPA --modes mlst --schemes mlst=vparahaemolyticus_1
bacmap db ...                                # gapit-only alias (--tool gapit)
```

`bacmap selection options --json` and the read-only MCP tool `bio_tool_selection_options` return
the same option document, so an agent can propose a selection and a human approves it. Run records
store `tool_selection_effective` and `tool_selection_sha256` (the legacy `db_selection_*` names
remain readable).
