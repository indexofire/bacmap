# HTTP API (`/api/v1`)

The Web server exposes a versioned JSON API under the same authentication as the HTML console. It is
a **trusted operator surface**: a token holder can submit, cancel, confirm and approve. Do not give
the Web token to an external agent; agents use MCP.

## 1. Authentication

### Bearer mode (default)

```bash
export BACMAP_WEB_TOKEN="$(openssl rand -hex 24)"
bacmap web --host 127.0.0.1 --port 8800
curl -H "Authorization: Bearer $BACMAP_WEB_TOKEN" http://127.0.0.1:8800/api/v1/tasks
```

### Cookie mode

```bash
export BACMAP_WEB_AUTH=cookie
bacmap web
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
| GET | `/api/v1/capabilities` | API version, bacmap version, plannable types, features |
| GET | `/api/v1/samples?cursor=&limit=` | completed-sample page (only the page is parsed) |
| GET | `/api/v1/tasks?limit=` | recent tasks |
| GET | `/api/v1/tasks/{id}` | task status |
| POST | `/api/v1/tasks/{id}/cancel` | cancel a non-terminal task |
| GET | `/api/v1/plans?limit=` | latest version of each plan |
| GET | `/api/v1/plans/{id}?version=` | plan detail |
| POST | `/api/v1/plans/{id}/confirm` | confirm + submit |
| POST | `/api/v1/plans/{id}/reject` | reject |
| GET | `/api/v1/events?after=&limit=&task_id=&plan_id=` | event poll |
| GET | `/api/v1/events/stream?after=&timeout=` | SSE stream (resumes from `Last-Event-ID`) |
| GET | `/api/v1/runs?limit=` | run records |
| GET | `/api/v1/runs/{id}` | run detail |
| GET | `/api/v1/runs/{id}/compare?other=` | provenance comparison |
| GET | `/api/v1/gom/objects?type=&limit=` | latest GOM objects |
| GET | `/api/v1/gom/objects/{id}?version=` | GOM object |

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
