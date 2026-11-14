# HTTP API (`/api/v1`)

The Web server exposes a versioned JSON API under the same authentication as the HTML console. It is
a **trusted operator surface**: a token holder can submit, cancel, confirm and approve. Do not give
the Web token to an external agent; agents use MCP.

## 1. Authentication

### Bearer mode (default)

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap start web --host 127.0.0.1 --port 8800
curl -H "Authorization: Bearer $BACMAP_WEB_TOKEN" http://127.0.0.1:8800/api/v1/tasks
```

### Cookie mode

```bash
export BACMAP_WEB_AUTH=cookie
bacmap start web
# browser: /login → signed session cookie + bacmap_csrf cookie
```

State-changing requests then need:

```http
X-CSRF-Token: <value of the bacmap_csrf cookie>
Origin: http://127.0.0.1:8800
```

## 2. Endpoints

| Method | Path | Purpose |
|---|---|---|
List endpoints accept `offset`/`limit` and return `{items, total, offset, limit}`; `/samples` keeps cursor mode for compatibility while the console uses offset.

| GET | `/api/v1/capabilities` | API version, bacmap version, plannable types, features |
| GET | `/api/v1/auth/status` | auth mode, login state and operator fingerprint (public) |
| POST | `/api/v1/auth/login` | exchange the deployment token for a signed session cookie (public; cookie mode only) |
| POST | `/api/v1/auth/logout` | clear session + CSRF cookies (CSRF-protected) |
| GET | `/api/v1/overview` | system overview (versions, paths, policy, sandbox, counts) |
| GET | `/api/v1/stats` | database statistics (tasks/runs/GOM/strains/serotypes/MLST/AMR/research/knowledge) |
| GET | `/api/v1/samples?cursor=&limit=` | completed-sample page (only the page is parsed) |
| GET | `/api/v1/samples/{id}` | sample digest + full steps + report-ready flag + gvixb latest-result links |
| GET | `/api/v1/specimens?limit=` | specimen list (with isolate counts) |
| GET | `/api/v1/specimens/{id}` | specimen + isolates + each isolate's libraries |
| GET | `/api/v1/isolates?limit=` | isolate list (specimen link, library counts) |
| GET | `/api/v1/isolates/{id}` | isolate + specimen + libraries |
| POST | `/api/v1/specimens/assign` | link isolates/datasets to a specimen (CSRF; creates the specimen) |
| POST | `/api/v1/specimens/{id}/delete` | delete a specimen (`force: true` unlinks isolates first; isolates/data are kept) |
| GET | `/api/v1/search?q=&serotype=&mlst_st=&amr_gene=` | sample search by keyword/serotype/ST/gene |
| GET | `/api/v1/search/identity?q=` | unified search: specimens and isolates |
| GET | `/api/v1/tasks?limit=` | recent tasks |
| POST | `/api/v1/tasks` | submit analyze/curate (`task_type`, `samples`, `scope`) |
| GET | `/api/v1/tasks/{id}` | task status and metadata |
| POST | `/api/v1/tasks/{id}/approve` | approval signature (`approver`, `decision`, `signature`, `comment?`) |
| POST | `/api/v1/tasks/{id}/cancel` | cancel a non-terminal task |
| POST | `/api/v1/tasks/{id}/pause` | pause a running task (interrupted workflows resumable) |
| POST | `/api/v1/tasks/{id}/resume` | resume a `paused`/`failed(interrupted)`/`cancelled` task in the same run directory |
| POST | `/api/v1/records/{kind}` | record task (`metadata`/`lab`/`knowledge-import`/`knowledge-approve`) |
| GET | `/api/v1/plans?limit=` | latest version of each plan |
| GET | `/api/v1/plans/{id}?version=` | plan detail |
| POST | `/api/v1/plans/{id}/confirm` | confirm + submit |
| POST | `/api/v1/plans/{id}/reject` | reject |
| GET | `/api/v1/events?after=&limit=&task_id=&plan_id=` | event poll (`last_seq` page cursor + `max_seq` for SSE start) |
| GET | `/api/v1/events/stream?after=&timeout=` | SSE stream (resumes from `Last-Event-ID`) |
| GET | `/api/v1/runs?limit=` | run records |
| GET | `/api/v1/runs/{id}` | run detail + gvixb views |
| GET | `/api/v1/runs/{id}/compare?other=` | provenance comparison |
| GET | `/api/v1/gom/objects?type=&limit=` | latest GOM objects |
| GET | `/api/v1/gom/objects/{id}?version=` | GOM object + linked gvixb views |
| GET | `/api/v1/gvixb/runs/{run_id}/manifest` | gvixb views available for a run |
| GET | `/api/v1/gvixb/runs/{run_id}/genome/{dataset}` | historical draft assembly payload |
| GET | `/api/v1/gvixb/samples/{dataset}/genome` | latest-result draft assembly payload |
| GET | `/api/v1/gvixb/runs/{run_id}/annotated-genome/{dataset}` | historical Bakta/eggNOG circle payload |
| GET | `/api/v1/gvixb/samples/{dataset}/annotated-genome` | latest-result circle payload |
| GET | `/api/v1/gvixb/runs/{run_id}/tree/{snp\|cgmlst}/{group}` | tree payload |
| GET | `/api/v1/gvixb/runs/{run_id}/mst/{group}` | original gmlst MST payload |

## 3. Examples

### Capabilities

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/capabilities | jq .
```

### Poll tasks

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/tasks?limit=20" | jq '.items[] | {task_id,state,current_step}'

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/tasks/3f9c2a1b | jq .
```

### Submit and approve a task

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"task_type":"analyze","samples":["SAM-TYP-001"]}' \
  http://127.0.0.1:8800/api/v1/tasks | jq '{task_id,state}'

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"approver":"jane","decision":"approve","signature":"jd-2026-11-09"}' \
  http://127.0.0.1:8800/api/v1/tasks/<task_id>/approve | jq '{state,message}'
```

### Search and overview

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/search?q=Salmonella&mlst_st=11" | jq '.items[] | {sample_id,verdict,st}'
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/overview | jq '{sandbox,versions,cloud_max_data_class}'
```

### Confirm a plan (bearer mode)

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version":1,"plan_hash":"c1d2e3f4a5b6","confirmer":"jane"}' \
  http://127.0.0.1:8800/api/v1/plans/9a3f2c1b7d4e4f60/confirm | jq .
```

Cookie mode adds `-H "X-CSRF-Token: $CSRF"` and a cookie jar.

### Reject a plan

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"version":1,"reason":"wrong sample"}' \
  http://127.0.0.1:8800/api/v1/plans/9a3f2c1b7d4e4f60/reject
```

### Events and SSE

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/events?after=120" | jq .

curl -N -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/events/stream?after=120"
```

SSE frames use `id: <seq>`, `event: <type>`, `data: <json>`. Reconnect with `Last-Event-ID` or
`after=`. A keepalive comment is sent while idle.

### Run comparison

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8800/api/v1/runs/<run_a>/compare?other=<run_b>" | jq .
```

### gvixb manifest

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8800/api/v1/gvixb/runs/<run_id>/manifest | jq .
```

A `circle:<dataset>` entry means the Bakta/eggNOG sidecar layout exists for that dataset. Detailed
contracts, browser URLs and troubleshooting are in [gvixb 3D
visualization](../guide/visualization.md).

## 4. Errors

```json
{"code": "validation_error", "error": "..."}
{"code": "not_found", "error": "..."}
{"code": "conflict", "error": "..."}
```

| Code | HTTP |
|---|---|
| `validation_error` | 400 |
| `not_found` | 404 |
| `conflict` | 409 |

Authentication failures are 401; CSRF failures are 403. The API returns JSON, not HTML.

## 5. Notes

- `limit` is clamped (tasks/plans 200, GOM 500, runs 200).
- Events are coordination aids, not truth; after a disconnect, re-read tasks/plans.
- Plans are versioned; always confirm the `(version, plan_hash)` you reviewed.
- The API is not a substitute for MCP in agent integrations.
