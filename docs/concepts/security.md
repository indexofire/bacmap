# Security and data classes

bacmap assumes the workstation is trustworthy and the *model* is not. The design keeps data on the
machine, constrains what an external agent can see, and makes a human responsible for consequential
actions.

## 1. Data classes (ADR-16)

| Class | Examples | Cloud endpoint | Cloud MCP profile |
|---|---|---|---|
| **D0** | public reference metadata, diagnostics | allowed | allowed |
| **D1** | de-identified aggregate statistics | allowed (default ceiling) | allowed |
| **D2** | single-strain typing results, sample IDs | blocked by default; admin may raise ceiling to D2 | allowed only if ceiling is D2 |
| **D3** | sequences, alignments, assemblies | **never** | requires `local-trusted` |
| **D4** | personal/epidemiological identifiers, metadata, lab results | **never** | requires `local-trusted` |

The ceiling is enforced twice:

1. **LLM gateway** — before sending, `LlmGateway` compares the payload class with
   `[llm.data_policy].cloud_max_data_class`; D3/D4 cannot be configured above D2.
2. **MCP profile** — the `cloud` server does not even register tools whose output class exceeds the
   ceiling; a call is re-checked at execution time.

```toml
[llm.data_policy]
cloud_max_data_class = "D1"      # "D1" or "D2" only
```

```
DataClassViolationError: payload D4 exceeds cloud limit D1
```

## 2. MCP profiles

```bash
bacmap mcp                          # cloud (default)
bacmap mcp --profile local-trusted  # requires [mcp] allow_local_trusted = true
```

| | `cloud` | `local-trusted` |
|---|---|---|
| Tool output | ≤ cloud ceiling | up to D4 |
| Task messages | withheld | full |
| Task result | gate counts | per-sample verdicts |
| Record tool | not registered | `bacmap_record_data` |
| Intended model | cloud API | local/LAN |

The profile is fixed at launch; a client cannot escalate mid-session. Run separate instances (ports
and tokens) if you need both.

## 3. Confirmation is not a tool approval

MCP elicitation and harness tool approvals are answered by the client/model. bacmap therefore
accepts confirmation only from:

- Web plan page / approval card (session + CSRF);
- CLI `plan confirm` / `task approve`;
- local system dialog (`bacmap_confirm_plan_locally`, stdio, human click);
- optional `[plans.auto_confirm]` policy for low-risk analyze plans over registered samples.

A model can propose, revise and poll, but cannot confirm or sign.

## 4. Sandbox

`mine` scripts run in a container (Apptainer or Podman) with:

- no network (`--network none`);
- a writable workspace;
- read-only mounts for results, GOM and registered datasets;
- the host filesystem not mounted (except declared inputs).

Passthrough is refused unless `BACMAP_ALLOW_UNSANDBOXED=1` (development only). Docker is
deliberately unsupported. The container, not an allow-list, is the security boundary.

## 5. Web and MCP authentication

### Web

- Loopback bind by default; a non-loopback host without a token refuses to start.
- `bearer` mode: `Authorization: Bearer <BACMAP_WEB_TOKEN>`; browsers cannot set it, so use an SSH
  tunnel or cookie mode.
- `cookie` mode: `/login` issues a signed `HttpOnly`, `SameSite=Strict` session cookie; every
  state-changing POST needs a CSRF token and a same-origin Origin/Referer.
- `BACMAP_WEB_COOKIE_SECURE=1` adds `Secure` behind TLS.
- Security headers include strict CSP, nosniff, frame-deny, referrer-policy and COOP.
- The JSON API is a trusted operator surface; never give its token to a harness.

### MCP HTTP

- Bearer token is mandatory (`BACMAP_MCP_TOKEN` or `--token-env`).
- Bound to loopback by default; a non-loopback bind still requires the bearer token and should sit behind a tunnel/firewall.
- DNS-rebinding protection via allowed hosts; MCP SDK transport security.
- stdio sessions use the OS user as actor (`mcp-stdio:<profile>:<user>`); HTTP uses
  `mcp-http:<profile>`.

## 6. Redaction and least privilege

- `cloud` `bacmap_task_status` withholds the raw task message (it may contain sample IDs, paths or
  other D2 data) and returns a redacted failure block:
  `{kind, suggested_fix, recovery_commands}`.
- `bacmap_task_result` returns gate counts instead of per-sample verdicts under cloud.
- Tool handlers return only the exception **type** on unexpected failures, not the message/path.
- Plan read/revise is limited to the client that created the plan.
- Task cancellation is limited to tasks the same client submitted (directly or via its own plan).

## 7. Threat model

| Threat | Control |
|---|---|
| Cloud model sees sequences/D4 | data classes enforced in gateway + MCP profile |
| Prompt injection makes an agent confirm or sign | confirmation only on trusted surfaces; model has no confirmation tool |
| Agent swaps a plan before you confirm | plan ownership + version/hash binding + input fingerprints |
| Forged request writes metadata | record tasks + task layer; MCP D4 only on local-trusted |
| Malicious mine script escapes | network-less container, read-only mounts, no host mount |
| Web token leaked to a harness | separate Web/MCP tokens; docs and startup hints; operator surface is not for agents |
| Session theft / CSRF | signed HttpOnly cookie, SameSite=Strict, CSRF token + origin check |
| Path traversal via sample IDs | `^[A-Za-z0-9._-]+$`, reject `.`/`..`, validate at every interface |
| Database tampering | append-only run records/manifests; GOM immutability; hashes in manifests |

## 8. Deployment checklist for external agents

```bash
# dedicated account, private home
sudo useradd -r -m -d /srv/bacmap bacmap
sudo chmod 700 /srv/bacmap

# run services as that account, loopback only
BACMAP_HOME=/srv/bacmap bacmap web --host 127.0.0.1 --port 8800
BACMAP_HOME=/srv/bacmap BACMAP_MCP_TOKEN=... \
  bacmap mcp --transport http --host 127.0.0.1 --port 8765

# the harness runs as your normal user and gets only the MCP URL/token
```

MCP profiles cannot stop a harness's own shell from reading files. The OS account boundary is what
prevents that; bacmap cannot control files copied into the harness workspace or what a model provider
does with content it receives.
