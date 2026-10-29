# Task engine, DBOS and gates

bacmap's task layer wraps **DBOS Transact**, a durable-workflow library that stores workflow and
step state in SQLite. DBOS is an internal execution detail: the `tasks` table is the public source
of truth.

## 1. Why DBOS

Long-running bioinformatics work must survive process restarts, and writes must be retry-safe.
DBOS provides:

- workflows (`@DBOS.workflow`) and steps (`@DBOS.step`) with per-step checkpoints;
- deterministic workflow IDs (`SetWorkflowID(task_id)`) for idempotent plan submission;
- status/result retrieval and cancellation;
- recovery of unfinished workflows on `DBOS.launch()`.

The system database is `$BACMAP_HOME/dbos.sqlite`. It is included in `bacmap backup` so a restore can
resume in-flight work.

## 2. Workflows and steps

```python
@DBOS.workflow()
def analyze_workflow(params):
    rc = _step_run(params)                  # Snakemake
    run = _step_create_run(params)          # runs.sqlite
    _step_finish_run(run["run_id"], params) # manifest
    for sample in params["samples"]:
        summary = _load_summary(home, sample, run_dir)
        _step_ingest_gom(str(home), sample, run["run_id"], summary)
        gate = _step_gate(str(home), sample, text, str(run_dir))
        _step_report(sample, str(run_dir))
    _step_ingest_cgmlst_profiles(...)
    _step_ingest_cohorts(...)
```

| Workflow | Steps (abridged) |
|---|---|
| `analyze_workflow` | register inputs → pipeline → run record → GOM → gate → report → cohorts |
| `curate_workflow` | build candidate → release gate → audit |
| `mine_workflow` | register datasets → sandbox → artefacts → mining gate |
| `write_workflow` | draft → citation gate → audit |
| `record_workflow` | metadata / lab / knowledge import / approval |

`current_step` is updated inside step bodies (`pipeline`, `run_record`, `sandbox`, `draft`,
`curate_build`, `record`, …) so the Web/TUI show progress without changing the workflow sequence.

## 3. Task states and transitions

```text
pending ──► running ──► succeeded
                │
                ├──► failed
                ├──► cancelled
                └──► awaiting_approval ──► succeeded | failed
```

- Terminal states (`succeeded`, `failed`, `cancelled`) cannot be changed by `cancel`.
- `status()` reconciles DBOS state into `tasks` on read; list/count endpoints call the same
  reconciliation so dashboards do not stay on `running`.
- `approve()` is allowed only from `awaiting_approval`; a second approval is a conflict (HTTP 409).
- `cancel()` calls DBOS cancellation and marks the task `cancelled`.

## 4. Plans and deterministic submission

A plan is a versioned task set. Confirmation binds:

```text
(plan_id, version, plan_hash)
```

Then each task gets a deterministic ID:

```python
plan_task_id(plan_id, version, index) = sha256(f"plan:{plan_id}:{version}:{index}")[:32]
```

`TaskEngine.submit` uses `INSERT OR IGNORE` plus `SetWorkflowID(task_id)`, so a repeated confirmation,
a double-click in Web+CLI, or a crash-retry submits the same tasks once. A revision creates a new
version and supersedes the old one; the old hash can no longer be confirmed.

## 5. Gates

Gates are deterministic code checks in `tasks/gates.py`. They are not LLM judgments.

### 5.1 Analysis claims

Triggered at the end of `analyze` (and by `bio_verify_result`). Input: an optional interpretation
text + the pipeline summary.

- Unsupported species canonicalisation → `reject`.
- NLI reflector finds contradictions above threshold → `needs_human_review`.
- Otherwise → `pass`.

The gate details include verifiable/contradicted counts and the threshold.

### 5.2 Baseline release

Triggered by `curate`. Requires:

- non-empty candidate, no duplicate strains;
- supported species;
- isolation date, region (province or city) and sample source;
- no D4 keys in the feature whitelist (second line of defence).

Any problem → `reject`; the previous release is unchanged.

### 5.3 Mining

Triggered by `mine` at the end and again at approval:

- non-empty artefacts;
- every artefact marked reproducible;
- `signed_by` present (the approver).

Unsigned or empty → `reject`. A rejected approval leaves the task failed.

### 5.4 Citation

Triggered by `write`:

- extract PMIDs (`PMID:`, `[12345678]`) and DOIs from the draft;
- compare against approved knowledge identifiers (normalised);
- unknown citations → `reject` (the task fails and cannot be approved).

`known_citations=[]` loads the approved knowledge base automatically.

Gate results are persisted as GOM `gate.<name>` events on the analysis object or a task object, and
are visible through `bacmap gom show`, the Web, and `bacmap_task_result` (counts only under the
cloud profile).

## 6. Human confirmation and approval

These are **not** gates:

- **Plan confirmation** (before execution) — Web page, CLI, local dialog, or optional policy.
- **Task approval** (after a gate asks for a human) — Web approval card, TUI `Ctrl+Y`, CLI
  `task approve`.

The actor and timestamp are stored (`plans.confirmed_by/confirmed_at`, `approvals` table) and an
event is appended. MCP elicitation and harness tool approvals are never accepted as confirmation.

## 7. Events and audit

`tasks.sqlite.events` is an append-only log with a monotonic `seq`:

```bash
curl /api/v1/events?after=120
curl -N /api/v1/events/stream        # SSE, resumes from Last-Event-ID
bacmap events prune --days 180
```

Events are for coordination, not truth. After a disconnect, query tasks/plans. Events carry a
`data_class`; cloud interfaces filter by profile.

## 8. Recovery and concurrency

- Process crash → DBOS resumes the workflow from the last completed step; Snakemake resumes from
  `.snakemake`.
- Concurrent analyses of the same dataset → each run writes its own directory; post-pipeline steps
  read that directory, so they cannot see another run's latest-link switch.
- Workflow deployment → content hash; `samples.tsv` and `.snakemake` are preserved.
- `bacmap backup` includes `dbos.sqlite`, so a restore can resume in-flight tasks.

See [Security](security.md) for the trust boundaries around these mechanisms.
