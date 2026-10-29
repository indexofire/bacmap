# Troubleshooting

Start with the task message and `bacmap doctor`; most failures fall into a small set of categories.

## 1. First commands

```bash
bacmap doctor
bacmap task list
bacmap task show <task_id>
bacmap task show <task_id> --json | jq .state,.current_step,.message
```

For a failed pipeline, an MCP client can call `bio_diagnose` with the log path or stderr text; the
same classifier is used by the redacted `failure` block returned by `bacmap_task_status`.

Logs:

```text
$BACMAP_HOME/workflow_state/log/*.snakemake.log
$BACMAP_HOME/workspaces/<task_id>/      # mine stdout/stderr and context.json
```

## 2. Submission and validation

| Symptom | Cause / fix |
|---|---|
| `非法样本 ID` / invalid sample id | ID outside `A-Za-z0-9._-`, or a full-width comma; use ASCII `,` or newlines |
| `analyze requires samples or fasta_dir/fastq_dir` | provide exactly one input form |
| `directory must be an absolute path` | plans require absolute input paths |
| `dataset_id collision` | same ID with different content; rename to `<isolate>__<platform>__<date>` |
| `scope 必须是 JSON 对象` | pass `{"pathogen":"Salmonella"}`, not an array |
| `task_type 'mine' is not submittable via MCP` | use `bacmap_create_plan`; open paths are plan-only |

## 3. Confirmation and plans

| Symptom | Cause / fix |
|---|---|
| `plan hash mismatch` | you confirmed a different version; run `bacmap plan show` and use the current hash |
| `input ... changed since the plan was created` | inputs changed after planning; revise the plan and re-confirm |
| `plan ... is submitted; cannot revise` | already submitted; create a new plan |
| `forbidden` on `bacmap_get_plan` | plan belongs to another MCP client; use the same client |
| `confirm_url` unreachable | start `bacmap web`, or set `BACMAP_WEB_URL`; CLI confirmation still works |
| Local dialog does nothing | only stdio sessions with a GUI (zenity/kdialog); use the Web link otherwise |
| Auto-confirm never fires | policy disabled, non-analyze task, directory ingestion, or malformed `max_samples` (fail-safe) |

## 4. Pipeline failures

`bio_diagnose` classifies Snakemake stderr. The redacted cloud response also names the kind.

| Kind | Meaning | Fix |
|---|---|---|
| `missing_input` | FASTQ/FASTA path wrong or file absent | check `samples.tsv` and `gs/`; paths are relative to `BACMAP_HOME` |
| `missing_tool` | external tool not on PATH | run in the pixi environment; `pixi install` |
| `missing_db` | BLAST/reference DB index missing | rebuild the database or restore `refs/` |
| `lock` | `.snakemake` lock from an interrupted run | `snakemake --unlock -d "$BACMAP_HOME/workflows/bacmap"` |
| `oom` | out of memory | lower cores/threads; avoid running a local LLM concurrently |
| `disk_full` | no space | free space; clean old run directories deliberately |
| `sandbox_unavailable` | no Apptainer/Podman | install one; passthrough is dev-only |
| `timeout` | long/blocked pipeline | inspect processes, increase timeout, unlock |
| `permission` | file mode/ownership | `chmod -R u+rwX` on the affected tree |

The `snakemake_v8` diagnostic is historical; current pins are Snakemake 9 (see `pixi.lock`).

## 5. Sandbox and mine

| Symptom | Fix |
|---|---|
| `no apptainer/podman on PATH` | install Podman (`pixi global install podman`) or Apptainer |
| `image pull failed` | pre-pull the sandbox image on a networked machine, or use a local SIF |
| `input path not found` | `input_paths` must exist at plan creation; register files/directories, not globs |
| `dataset ... missing` on verify | the original file moved; re-register the correct path |
| Script has no network | by design; download data beforehand and register it |
| Artefacts not in report | the mining gate requires a human signature |

## 6. Web, API and auth

| Symptom | Fix |
|---|---|
| 401 in a browser (bearer mode) | browsers cannot set `Authorization`; use an SSH tunnel or `BACMAP_WEB_AUTH=cookie` |
| 403 CSRF | send `X-CSRF-Token` equal to the `bacmap_csrf` cookie in cookie mode |
| 409 on approve | task is already terminal or not `awaiting_approval`; refresh |
| 404 on a report | run the analysis/report first; check the sample ID |
| CORS/Origin error on login | the request's Origin must match the Host; use the same hostname |
| `/api/v1` token leaked to a harness | rotate `BACMAP_WEB_TOKEN`; harnesses must use MCP |

## 7. MCP clients

| Symptom | Fix |
|---|---|
| No tools discovered | check `bacmap mcp` starts; `bacmap_capabilities`; profile flag |
| HTTP 401 | `Authorization: Bearer $BACMAP_MCP_TOKEN`; token must match the server's env |
| `local-trusted` refuses to start | set `[mcp] allow_local_trusted = true` (boolean) |
| D3/D4 tools missing | you are on `cloud`; use a local model + `local-trusted` |
| Task message empty | cloud profile redaction; use `failure` block or local profile |
| Hermes fresh home fails | set `CMAKE_POLICY_VERSION_MINIMUM=3.5`, then `hermes auth add zai` |
| DSH entry ignored | wrap new entries in `insert:` |

## 8. Data and evidence

| Symptom | Fix |
|---|---|
| Result missing after an upgrade | run `bacmap results migrate`; check symlink targets |
| Two runs of the same sample differ | `bacmap run compare <a> <b>`; check `NOT_REPRODUCIBLE` |
| Baseline excludes a strain | inspect `excluded` reasons: species/QC/metadata/duplicate/representative |
| Citation gate rejects | approve the knowledge entry (`knowledge-approve`) or fix the citation |
| Knowledge approval overwritten? | impossible by design; approvals are single-shot |
| Task stuck `running` after a restore | ensure `dbos.sqlite` was included in the backup; otherwise re-submit |

## 9. Getting help

- `bacmap doctor --json` for a machine-readable snapshot.
- `bacmap overview` for versions, paths, policy, sandbox and endpoints.
- `bacmap run show` / `gom show` for evidence.
- External agents can call `bacmap_capabilities`, `bacmap_task_status` (redacted) and
  `bio_diagnose`; they cannot sign or confirm for you.
